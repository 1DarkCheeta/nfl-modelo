"""Modelos de equipo (margen/spread/ganador y totales), calibracion y evaluacion vs mercado.

Dos versiones de cada modelo:
  A = solo ratings propios (mide si el modelo aporta senal independiente del mercado)
  B = ratings + linea del mercado como variable (modelo "anclado" al mercado)
Las probabilidades salen de una distribucion normal alrededor de la prediccion y luego
se calibran con escalado de Platt usando SOLO temporadas anteriores (walk-forward).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

F_MARGIN = ["pass_diff", "rush_diff", "pts_diff", "rest_diff", "neutral"]
F_TOTAL = ["pass_sum", "rush_sum", "pts_sum", "mu_pts", "wind_eff", "dome"]
SPECS = {  # nombre -> (variables, objetivo)
    "mA": (F_MARGIN, "result"),
    "mB": (F_MARGIN + ["spread_line"], "result"),
    "tA": (F_TOTAL, "total"),
    "tB": (F_TOTAL + ["total_line"], "total"),
}
TRAIN_START = 2003   # 1999-2002 sirven solo de "calentamiento" de los ratings
MIN_CAL = 500        # partidos minimos previos para calibrar


def make_pipe(alpha: float = 50.0):
    return make_pipeline(StandardScaler(), Ridge(alpha=alpha))


def fit_final(df: pd.DataFrame, feats, target):
    """Ajusta con todos los partidos jugados. Devuelve (modelo, sigma de residuos)."""
    tr = df[(df.season >= TRAIN_START) & df[target].notna()].dropna(subset=feats)
    pipe = make_pipe().fit(tr[feats], tr[target])
    sigma = float((tr[target] - pipe.predict(tr[feats])).std())
    return pipe, sigma


def walk_forward(df: pd.DataFrame, feats, target, seasons) -> pd.DataFrame:
    """Para cada temporada y: ajusta con [TRAIN_START, y) y predice y."""
    out = []
    for y in seasons:
        tr = df[(df.season >= TRAIN_START) & (df.season < y) & df[target].notna()].dropna(subset=feats)
        te = df[df.season == y].dropna(subset=feats)
        if len(tr) == 0 or len(te) == 0:
            continue
        pipe = make_pipe().fit(tr[feats], tr[target])
        sigma = float((tr[target] - pipe.predict(tr[feats])).std())
        out.append(pd.DataFrame({"game_id": te.game_id.values,
                                 "pred": pipe.predict(te[feats]), "sigma": sigma}))
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- probabilidades
def add_probs(out: pd.DataFrame) -> pd.DataFrame:
    """Probabilidades crudas (normal) y resultados observados (NaN si hay push/no jugado)."""
    for v in "AB":
        out[f"pwin_{v}"] = norm.cdf(out[f"pred_m{v}"] / out[f"sig_m{v}"])
        out[f"pcov_{v}"] = norm.cdf((out[f"pred_m{v}"] - out.spread_line) / out[f"sig_m{v}"])
        out[f"pover_{v}"] = norm.cdf((out[f"pred_t{v}"] - out.total_line) / out[f"sig_t{v}"])
    out["y_win"] = np.where(out.result > 0, 1.0, np.where(out.result < 0, 0.0, np.nan))
    out["y_cov"] = np.where(out.result > out.spread_line, 1.0,
                            np.where(out.result < out.spread_line, 0.0, np.nan))
    out["y_over"] = np.where(out.total > out.total_line, 1.0,
                             np.where(out.total < out.total_line, 0.0, np.nan))
    return out


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p)).reshape(-1, 1)


class Platt:
    """Calibracion logistica: P_cal = sigmoide(a + b * logit(P))."""

    def fit(self, p, y):
        self.lr = LogisticRegression(C=1e6).fit(_logit(p), y)
        return self

    def predict(self, p):
        return self.lr.predict_proba(_logit(p))[:, 1]


CAL_TARGETS = [("pwin", "y_win"), ("pcov", "y_cov"), ("pover", "y_over")]


def calibrate_walk_forward(out: pd.DataFrame, seasons) -> pd.DataFrame:
    """Columnas *_cal: calibradas con las predicciones fuera de muestra de temporadas previas."""
    for p, y in CAL_TARGETS:
        for v in "AB":
            col = f"{p}_{v}"
            out[col + "_cal"] = np.nan
            for s in seasons:
                tr = out[(out.season < s) & out[y].notna() & out[col].notna()]
                if len(tr) < MIN_CAL:
                    continue
                m = (out.season == s) & out[col].notna()
                out.loc[m, col + "_cal"] = Platt().fit(tr[col].values, tr[y].values).predict(out.loc[m, col].values)
    return out


def walk_forward_all(df: pd.DataFrame, seasons) -> pd.DataFrame:
    """Predicciones fuera de muestra de los 4 modelos + probabilidades crudas y calibradas."""
    keep = ["game_id", "season", "week", "gameday", "home_team", "away_team", "result", "total",
            "spread_line", "total_line", "home_spread_odds", "away_spread_odds", "over_odds",
            "under_odds", "home_moneyline", "away_moneyline"]
    out = df.loc[df.season.isin(seasons), keep].copy()
    for name, (feats, target) in SPECS.items():
        wf = walk_forward(df, feats, target, seasons).rename(
            columns={"pred": f"pred_{name}", "sigma": f"sig_{name}"})
        out = out.merge(wf, on="game_id", how="left")
    out = add_probs(out)
    return calibrate_walk_forward(out, seasons)


# --------------------------------------------------------------------------- mercado y apuestas
def implied(odds):
    o = np.asarray(odds, float)
    with np.errstate(divide="ignore", invalid="ignore"):  # np.where evalua ambas ramas
        return np.where(o < 0, -o / (-o + 100), 100 / (o + 100))


def payout(odds):
    o = np.asarray(odds, float)
    return np.where(o < 0, 100 / np.abs(o), o / 100)


def devig_home(home_ml, away_ml):
    ph, pa = implied(home_ml), implied(away_ml)
    return ph / (ph + pa)


def bet_table(p_a, odds_a, odds_b, win_a, win_b, thresholds=(0, .02, .04, .06, .08)) -> pd.DataFrame:
    """ROI de apostar 1 unidad al lado con ventaja > umbral (ventaja = P_modelo - P_implicita).

    p_a: prob. del lado A; el lado B tiene 1 - p_a. win_a/win_b: resultado observado
    (si ninguno es True hubo push y se devuelve la apuesta)."""
    p_a, win_a, win_b = np.asarray(p_a, float), np.asarray(win_a, bool), np.asarray(win_b, bool)
    odds_a, odds_b = np.asarray(odds_a, float), np.asarray(odds_b, float)
    edge_a = p_a - implied(odds_a)
    edge_b = (1 - p_a) - implied(odds_b)
    rows = []
    for t in thresholds:
        bet_a = (edge_a > t) & (edge_a >= edge_b)
        bet_b = (edge_b > t) & (edge_b > edge_a)
        ret = np.where(bet_a, np.where(win_a, payout(odds_a), np.where(win_b, -1.0, 0.0)),
                       np.where(bet_b, np.where(win_b, payout(odds_b), np.where(win_a, -1.0, 0.0)), np.nan))
        won = np.where(bet_a, win_a, np.where(bet_b, win_b, False))
        lost = np.where(bet_a, win_b, np.where(bet_b, win_a, False))
        r = ret[~np.isnan(ret)]
        n = len(r)
        rows.append({"umbral": t, "apuestas": n,
                     "%acierto": won.sum() / max(won.sum() + lost.sum(), 1) * 100,
                     "ROI%": r.mean() * 100 if n else np.nan,
                     "error_est%": r.std(ddof=1) / np.sqrt(n) * 100 if n > 1 else np.nan})
    return pd.DataFrame(rows)


def prob_metrics(p, y) -> dict:
    p, y = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4), np.asarray(y, float)
    return {"n": len(y), "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "brier": float(np.mean((p - y) ** 2)), "acierto%": float(np.mean((p > .5) == (y == 1)) * 100)}


def calibration_table(p, y, bins=(0, .2, .35, .5, .65, .8, 1.0)) -> pd.DataFrame:
    d = pd.DataFrame({"p": p, "y": y})
    d["rango"] = pd.cut(d.p, bins, include_lowest=True)
    t = d.groupby("rango", observed=True).agg(n=("y", "size"), prob_media=("p", "mean"), frec_real=("y", "mean"))
    return t.round(3).reset_index()
