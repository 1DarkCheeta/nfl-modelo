"""Calcula probabilidades y ventajas (edges) para los partidos pendientes con linea publicada.

Se puede usar desde la terminal (python predict.py [--no-refresh] [--week N] [--all] [--min-edge 0.03])
o desde semana_nfl.py, que ademas genera el reporte con graficos.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from data import FIRST_SEASON, load_schedules, load_team_games
from features import build_dataset
from model import CAL_TARGETS, SPECS, Platt, devig_home, fit_final, implied, walk_forward_all

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
HIST = ROOT / "historial"
OUT.mkdir(exist_ok=True)
HIST.mkdir(exist_ok=True)


def fmt_line(x: float) -> str:
    return f"{x:+g}"


def _best(p_a, odds_a, odds_b, label_a, label_b):
    """Elige el lado (A o B) con mayor ventaja = P_modelo - P_implicita_en_la_cuota."""
    ia, ib = implied(odds_a), implied(odds_b)
    ea, eb = p_a - ia, (1 - p_a) - ib
    a = ea >= eb
    return {"edge": np.where(a, ea, eb), "lado": np.where(a, label_a, label_b),
            "p": np.where(a, p_a, 1 - p_a), "cuota": np.where(a, odds_a, odds_b),
            "imp": np.where(a, ia, ib), "es_a": a}


def compute(refresh: bool = True, week: int | None = None, show_all: bool = False,
            min_edge: float = 0.02) -> dict:
    games = load_schedules(refresh=refresh)
    cur = int(games.loc[games.result.notna(), "season"].max())
    tg = load_team_games(range(FIRST_SEASON, cur + 1), refresh_seasons=(cur,) if refresh else ())

    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {"k": 0.05, "shrink": 0.5}
    df, state = build_dataset(games, tg, return_state=True, **cfg)

    # Calibracion (Platt) con TODAS las predicciones fuera de muestra disponibles
    oos = walk_forward_all(df, list(range(2008, cur + 1)))
    cals = {}
    for p, y in CAL_TARGETS:
        for v in "AB":
            r = oos[oos[y].notna() & oos[f"{p}_{v}"].notna()]
            cals[f"{p}_{v}"] = Platt().fit(r[f"{p}_{v}"].values, r[y].values)

    final = {name: fit_final(df, feats, target) for name, (feats, target) in SPECS.items()}

    pend = df[df.result.isna() & df.spread_line.notna() & df.total_line.notna() & (df.season == cur)].copy()
    if pend.empty:
        return {"res": pend, "oos": oos, "cur": cur, "week": None, "min_edge": min_edge, "games": games, "state": state, "df": df, "final": final}
    if not show_all:
        wk = week if week else int(pend.week.min())
        pend = pend[pend.week == wk]
    wk = int(pend.week.min())
    pend = pend.sort_values(["gameday", "game_id"]).reset_index(drop=True)

    res = pend[["game_id", "season", "week", "gameday", "away_team", "home_team", "spread_line", "total_line",
                "home_moneyline", "away_moneyline"]].copy()
    for name, (feats, _) in SPECS.items():
        pipe, sigma = final[name]
        res[f"pred_{name}"] = pipe.predict(pend[feats])
        res[f"sig_{name}"] = sigma
    for v in "AB":
        res[f"pwin_{v}"] = norm.cdf(res[f"pred_m{v}"] / res[f"sig_m{v}"])
        res[f"pcov_{v}"] = norm.cdf((res[f"pred_m{v}"] - res.spread_line) / res[f"sig_m{v}"])
        res[f"pover_{v}"] = norm.cdf((res[f"pred_t{v}"] - res.total_line) / res[f"sig_t{v}"])
    # El modelo B (anclado al mercado) es el de decision: mejor logloss/Brier en el backtest
    for p, _ in CAL_TARGETS:
        res[f"{p}_F"] = cals[f"{p}_B"].predict(res[f"{p}_B"].values)

    odds = lambda c: pend[c].fillna(-110).values
    res["p_gana_local"] = res.pwin_F
    has_ml = pend.home_moneyline.notna().values
    res["p_gana_local_mercado"] = np.where(has_ml, devig_home(pend.home_moneyline, pend.away_moneyline), np.nan)
    res["p_cubre_local"], res["p_over"] = res.pcov_F, res.pover_F

    sp = _best(res.pcov_F.values, odds("home_spread_odds"), odds("away_spread_odds"),
               [f"{h} {fmt_line(-s)}" for h, s in zip(res.home_team, res.spread_line)],
               [f"{x} {fmt_line(s)}" for x, s in zip(res.away_team, res.spread_line)])
    to = _best(res.pover_F.values, odds("over_odds"), odds("under_odds"),
               [f"OVER {t:g}" for t in res.total_line], [f"UNDER {t:g}" for t in res.total_line])
    ml = _best(res.pwin_F.values, pend.home_moneyline.fillna(-110).values, pend.away_moneyline.fillna(-110).values,
               list(res.home_team + " ML"), list(res.away_team + " ML"))
    for key, d in (("sp", sp), ("to", to), ("ml", ml)):
        res[f"{key}_edge"] = d["edge"]
        res[f"{key}_lado"] = d["lado"]
        res[f"{key}_p"] = d["p"]
        res[f"{key}_cuota"] = d["cuota"]
        res[f"{key}_imp"] = d["imp"]
        res[f"{key}_es_a"] = d["es_a"]   # True = local (spread/ml) u over (total)
    for c in ("ml_edge", "ml_p", "ml_imp", "ml_cuota"):
        res[c] = np.where(has_ml, res[c], np.nan)
    res["ml_lado"] = np.where(has_ml, res.ml_lado, "")
    res["tiene_ml"] = has_ml
    res["margen_mercado"] = res.spread_line
    res["linea_local"] = -res.spread_line
    res["min_edge"] = min_edge
    return {"res": res, "oos": oos, "cur": cur, "week": wk, "min_edge": min_edge, "games": games, "state": state, "df": df, "final": final}


def veredicto(edge, lado, min_edge, tiene=True) -> str:
    if not tiene or pd.isna(edge):
        return "Sin cuota publicada"
    if edge >= min_edge:
        return f"POSIBLE VALOR: {lado}"
    return "Sin ventaja"


def tabla_csv(res: pd.DataFrame, min_edge: float) -> pd.DataFrame:
    """Tabla en espanol, una fila por partido, sin celdas vacias."""
    t = pd.DataFrame({
        "fecha": res.gameday.dt.strftime("%Y-%m-%d"), "semana": res.week,
        "visita": res.away_team, "local": res.home_team,
        "linea_local (negativa = local favorito)": res.linea_local,
        "margen_mercado (+ gana local)": res.margen_mercado,
        "margen_modelo_A (+ gana local)": res.pred_mA.round(1),
        "margen_modelo_B (+ gana local)": res.pred_mB.round(1),
        "prob_gana_local_modelo_%": (res.p_gana_local * 100).round(1),
        "prob_gana_local_mercado_%": (res.p_gana_local_mercado * 100).round(1),
        "prob_cubre_local_%": (res.p_cubre_local * 100).round(1),
        "spread_mejor_lado": res.sp_lado, "spread_ventaja_pts": (res.sp_edge * 100).round(1),
        "spread_veredicto": [veredicto(e, l, min_edge) for e, l in zip(res.sp_edge, res.sp_lado)],
        "total_mercado": res.total_line, "total_modelo_B": res.pred_tB.round(1),
        "prob_over_%": (res.p_over * 100).round(1),
        "total_mejor_lado": res.to_lado, "total_ventaja_pts": (res.to_edge * 100).round(1),
        "total_veredicto": [veredicto(e, l, min_edge) for e, l in zip(res.to_edge, res.to_lado)],
        "ml_mejor_lado": res.ml_lado.replace("", "n/d"), "ml_ventaja_pts": (res.ml_edge * 100).round(1),
        "ml_veredicto": [veredicto(e, l, min_edge, h) for e, l, h in zip(res.ml_edge, res.ml_lado, res.tiene_ml)],
    })
    return t.fillna("n/d")


def guardar_historial(res: pd.DataFrame, cur: int, week: int) -> Path:
    """Guarda las predicciones de la semana (sin pisar partidos ya guardados que siguen jugandose)."""
    path = HIST / f"prob_{cur}_s{week:02d}.csv"
    if path.exists():
        old = pd.read_csv(path, parse_dates=["gameday"])
        old = old[~old.game_id.isin(res.game_id)]
        res = pd.concat([old, res], ignore_index=True)
    res.to_csv(path, index=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--week", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--min-edge", type=float, default=0.02)
    a = ap.parse_args()
    r = compute(not a.no_refresh, a.week, a.all, a.min_edge)
    if r["res"].empty:
        print("No hay partidos pendientes con linea publicada.")
        return
    t = tabla_csv(r["res"], a.min_edge)
    path = OUT / f"probabilidades_{r['cur']}_semana{r['week']}.csv"
    t.to_csv(path, index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(t.to_string(index=False))
    print(f"\nGuardado en {path}")


if __name__ == "__main__":
    main()
