"""Backtest walk-forward: tunea hiperparametros (solo 2008-2014), evalua desde 2015.

Uso:  python backtest.py
Salidas: outputs/backtest_report.md, outputs/backtest_predictions.csv, config.json

`evaluate()` tambien la usa el reporte semanal (nfl_semana.py) para mostrar la fiabilidad historica.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data import FIRST_SEASON, load_schedules, load_team_games
from features import build_dataset
from model import (SPECS, bet_table, calibration_table, devig_home, prob_metrics,
                   walk_forward, walk_forward_all)

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"

TUNE_SEASONS = range(2008, 2015)   # solo aqui se eligen k y shrink
FIRST_TEST = 2015                  # nunca se usa para elegir nada
GRID_K = (0.02, 0.035, 0.05, 0.08, 0.12)
GRID_SHRINK = (0.35, 0.5, 0.65, 0.8)


def tune(games, tg):
    rows = []
    for k, s in itertools.product(GRID_K, GRID_SHRINK):
        df = build_dataset(games, tg, k, s)
        feats, target = SPECS["mA"]
        wf = walk_forward(df, feats, target, TUNE_SEASONS).merge(df[["game_id", "result"]], on="game_id")
        rows.append({"k": k, "shrink": s, "rmse": float(np.sqrt(((wf.pred - wf.result) ** 2).mean()))})
    return pd.DataFrame(rows).sort_values("rmse").reset_index(drop=True)


def evaluate(out: pd.DataFrame, test_seasons, thresholds=(0, .02, .04, .06, .08)) -> dict:
    """Metricas fuera de muestra del modelo vs el mercado en `test_seasons`.

    Devuelve DataFrames: margen, ganador, calibracion (modelo B), spread, total, ml
    (las tres ultimas con ROI por umbral de ventaja) y los conteos de partidos."""
    ev = out[out.season.isin(list(test_seasons)) & out.result.notna()].copy()
    for c in ("home_spread_odds", "away_spread_odds", "over_odds", "under_odds"):
        ev[c] = ev[c].fillna(-110)   # si falta la cuota se asume el estandar -110
    res = {}

    m = ev.dropna(subset=["spread_line", "pred_mA", "pred_mB"])
    err = lambda p: pd.Series({"RMSE": np.sqrt(((m.result - p) ** 2).mean()), "MAE": (m.result - p).abs().mean()})
    res["margen"] = pd.DataFrame({"Linea del mercado": err(m.spread_line), "Modelo A (solo ratings)": err(m.pred_mA),
                                  "Modelo B (ratings + mercado)": err(m.pred_mB)}).T.reset_index(names="modelo")
    res["n_margen"] = len(m)

    w = ev.dropna(subset=["y_win", "home_moneyline", "away_moneyline", "pwin_A_cal", "pwin_B_cal"]).copy()
    w["mkt"] = devig_home(w.home_moneyline, w.away_moneyline)
    rows = {"Mercado (sin margen de la casa)": w.mkt, "Modelo A cruda": w.pwin_A, "Modelo A calibrada": w.pwin_A_cal,
            "Modelo B calibrada (usado en predict.py)": w.pwin_B_cal}
    res["ganador"] = pd.DataFrame({k: prob_metrics(v, w.y_win) for k, v in rows.items()}).T.reset_index(names="modelo")
    res["n_ganador"] = len(w)
    res["calibracion"] = calibration_table(w.pwin_B_cal, w.y_win)

    def table(frame, pcols, odds_a, odds_b, win_a, win_b):
        parts = []
        for label, pc in pcols.items():
            tb = bet_table(frame[pc], frame[odds_a], frame[odds_b], frame[win_a], frame[win_b], thresholds)
            tb.insert(0, "modelo", label)
            parts.append(tb)
        return pd.concat(parts, ignore_index=True)

    s = ev.dropna(subset=["pcov_A_cal", "pcov_B_cal", "spread_line"]).copy()
    s["wa"], s["wb"] = s.result > s.spread_line, s.result < s.spread_line
    res["spread"] = table(s, {"A": "pcov_A_cal", "B": "pcov_B_cal"}, "home_spread_odds", "away_spread_odds", "wa", "wb")
    res["n_spread"] = len(s)

    o = ev.dropna(subset=["pover_A_cal", "pover_B_cal", "total_line"]).copy()
    o["wa"], o["wb"] = o.total > o.total_line, o.total < o.total_line
    res["total"] = table(o, {"A": "pover_A_cal", "B": "pover_B_cal"}, "over_odds", "under_odds", "wa", "wb")
    res["n_total"] = len(o)

    ml = w.copy()
    ml["wa"], ml["wb"] = ml.result > 0, ml.result < 0
    res["ml"] = table(ml, {"A": "pwin_A_cal", "B": "pwin_B_cal"}, "home_moneyline", "away_moneyline", "wa", "wb")
    res["n_ml"] = len(ml)
    return res


def md(df: pd.DataFrame, floatfmt=2) -> str:
    try:
        return df.round(floatfmt).to_markdown(index=False)
    except ImportError:  # falta `tabulate`
        return df.round(floatfmt).to_string(index=False)


def main():
    OUT.mkdir(exist_ok=True)
    games = load_schedules()
    cur = int(games.loc[games.result.notna(), "season"].max())
    tg = load_team_games(range(FIRST_SEASON, cur + 1))

    print("Tuneando k y shrink con 2008-2014 ...")
    grid = tune(games, tg)
    best = grid.iloc[0]
    k, shrink = float(best.k), float(best.shrink)
    print(grid.head(5).to_string(index=False))
    (ROOT / "config.json").write_text(json.dumps({"k": k, "shrink": shrink}, indent=2))

    df = build_dataset(games, tg, k, shrink)
    out = walk_forward_all(df, list(range(2008, cur + 1)))
    out.to_csv(OUT / "backtest_predictions.csv", index=False)

    test = range(FIRST_TEST, cur)   # temporadas completas
    r = evaluate(out, test)
    sub = f"{r['n_spread']} partidos; umbral = ventaja minima P_modelo - P_implicita"
    sections = [
        ("1. Error al predecir el margen (puntos, menor = mejor)", f"{r['n_margen']} partidos, {test[0]}-{test[-1]}", md(r["margen"])),
        ("2. Probabilidad de que gane el local (menor logloss/brier = mejor)", f"{r['n_ganador']} partidos", md(r["ganador"], 4)),
        ("3. Calibracion del Modelo B (prob. predicha vs frecuencia real)", "Si esta bien calibrado, prob_media y frec_real son parecidas", md(r["calibracion"], 3)),
        ("4. Apostar al spread (ROI con 1 unidad por apuesta, cuotas reales)", sub, md(r["spread"])),
        ("5. Apostar a totales (over/under)", f"{r['n_total']} partidos", md(r["total"])),
        ("6. Apostar al moneyline (ganador)", f"{r['n_ml']} partidos", md(r["ml"])),
    ]
    live = out[(out.season == cur) & out.result.notna() & out.pred_mA.notna()]
    report = ["# Backtest del modelo de equipos NFL\n",
              f"Hiperparametros elegidos con 2008-2014: k={k}, shrink={shrink}. Evaluacion fuera de muestra: "
              f"{test[0]}-{test[-1]} (cada temporada se predice con modelos entrenados solo con temporadas anteriores).\n"]
    for title, subt, body in sections:
        report += [f"## {title}\n_{subt}_\n", body + "\n"]
    if len(live):
        mk = np.sqrt(((live.result - live.spread_line) ** 2).mean())
        ma = np.sqrt(((live.result - live.pred_mA) ** 2).mean())
        report.append(f"## Temporada en curso ({cur}, {len(live)} partidos jugados)\nRMSE margen: mercado {mk:.2f} vs modelo A {ma:.2f}\n")
    (OUT / "backtest_report.md").write_text("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
