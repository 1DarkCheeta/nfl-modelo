"""Metricas de evaluacion honesta de las probabilidades del modelo (ganador, spread, total).

Todo se calcula con predicciones FUERA DE MUESTRA (walk-forward): cada temporada T se predice con un modelo entrenado
solo con temporadas <= T-1 y calibrado solo con predicciones de temporadas anteriores (ver model.walk_forward_all).

Por mercado se mide:
  * log-loss y Brier del modelo y del mercado SIN margen de la casa (se le quita el vig a las dos cuotas);
  * ECE (error de calibracion esperado): promedio, ponderado por casos, de |lo que dijo el modelo - lo que paso|
    en grupos de partidos con probabilidad parecida (grupos de IGUAL tamano: con probabilidades tan cercanas a 50 %
    en spread y total, los grupos de igual ancho dejarian casi todo en uno solo);
  * acierto en dos vistas: «todas las elecciones» (el lado que el modelo ve mas probable) y «solo posibles valores»
    (apuestas con ventaja >= umbral sobre la cuota);
  * ROI por unidad apostada con su intervalo de confianza del 95 % por bootstrap (2,000 remuestreos).

Este modulo no depende de la pagina: lo usan Calidad (marcador.py) y los experimentos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

UMBRAL = 0.02
N_BOOT = 2000
MERCADOS = ("ganador", "spread", "total")
# columna de probabilidad (modelo B calibrado = el de decision), resultado observado, cuotas y como se gana cada lado
COLS = {
    "ganador": dict(p="pwin_B_cal", y="y_win", oa="home_moneyline", ob="away_moneyline"),
    "spread": dict(p="pcov_B_cal", y="y_cov", oa="home_spread_odds", ob="away_spread_odds"),
    "total": dict(p="pover_B_cal", y="y_over", oa="over_odds", ob="under_odds"),
}


def implied(o):
    o = np.asarray(o, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(o < 0, -o / (-o + 100), 100 / (o + 100))


def payout(o):
    o = np.asarray(o, float)
    return np.where(o < 0, 100 / np.abs(o), o / 100)


def devig(a, b):
    pa, pb = implied(a), implied(b)
    return pa / (pa + pb)


def logloss(p, y):
    p, y = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def curva(p, y, k: int = 10) -> pd.DataFrame:
    """Curva de confiabilidad: k grupos de IGUAL tamano ordenados por probabilidad -> (prob. media dicha, frecuencia real, casos)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return pd.DataFrame(columns=["dijo", "paso", "n"])
    k = max(1, min(k, len(p) // 10)) if len(p) >= 20 else 1
    o = np.argsort(p, kind="stable")
    filas = []
    for g in np.array_split(o, k):
        if len(g):
            filas.append((float(p[g].mean()), float(y[g].mean()), int(len(g))))
    return pd.DataFrame(filas, columns=["dijo", "paso", "n"])


def ece(p, y, k: int = 10) -> float:
    c = curva(p, y, k)
    return float((c.n * (c.dijo - c.paso).abs()).sum() / c.n.sum()) if len(c) else float("nan")


def ic_roi(u: np.ndarray, n_boot: int = N_BOOT, seed: int = 0) -> tuple[float, float]:
    """IC 95 % del ROI medio (unidades por apuesta) por bootstrap percentil."""
    u = np.asarray(u, float)
    if len(u) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(n_boot, len(u)))
    m = u[idx].mean(axis=1)
    return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))


def apuestas(ev: pd.DataFrame, mk: str, umbral: float = UMBRAL, solo_valor: bool = False) -> pd.DataFrame:
    """Una fila por partido con push excluido: lado elegido, ventaja, cuota, si gano y unidades.

    solo_valor=False -> «todas las elecciones»: el lado que el modelo ve mas probable (>= 50 %), con su cuota.
    solo_valor=True  -> «posibles valores»: el lado con mayor ventaja (P modelo - P implicita en la cuota) si ventaja >= umbral."""
    c = COLS[mk]
    d = ev[ev[c["p"]].notna() & ev[c["y"]].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["season", "p_lado", "cuota", "gana", "unid", "edge"])
    oa = d[c["oa"]].fillna(-110).values
    ob = d[c["ob"]].fillna(-110).values
    p = d[c["p"]].values
    ea, eb = p - implied(oa), (1 - p) - implied(ob)
    if solo_valor:
        lado_a = ea >= eb
    else:
        lado_a = p >= 0.5
    edge = np.where(lado_a, ea, eb)
    y = d[c["y"]].values
    gana = np.where(lado_a, y == 1.0, y == 0.0)
    cuota = np.where(lado_a, oa, ob)
    out = pd.DataFrame({"season": d.season.values, "p_lado": np.where(lado_a, p, 1 - p), "cuota": cuota,
                        "gana": gana, "unid": np.where(gana, payout(cuota), -1.0), "edge": edge})
    if solo_valor:
        out = out[out.edge >= umbral]
    return out.reset_index(drop=True)


def evaluar(oos: pd.DataFrame, temporadas, umbral: float = UMBRAL, cols: dict | None = None,
            n_boot: int = N_BOOT) -> dict:
    """Metricas por mercado en las temporadas dadas. `cols` permite evaluar otras columnas de probabilidad (experimentos)."""
    global COLS
    viejo = COLS
    if cols:
        COLS = {**COLS, **{m: {**COLS[m], **v} for m, v in cols.items()}}
    try:
        ev = oos[oos.season.isin(list(temporadas)) & oos.result.notna()]
        res = {}
        for mk in MERCADOS:
            c = COLS[mk]
            d = ev[ev[c["p"]].notna() & ev[c["y"]].notna()]
            if d.empty:
                continue
            y = d[c["y"]].values
            pm = devig(d[c["oa"]].fillna(-110).values, d[c["ob"]].fillna(-110).values)
            p = d[c["p"]].values
            r = {"n": len(d), "ll": logloss(p, y), "br": brier(p, y), "ece": ece(p, y),
                 "ll_mk": logloss(pm, y), "br_mk": brier(pm, y), "ece_mk": ece(pm, y)}
            for nombre, sv in (("todas", False), ("valor", True)):
                b = apuestas(ev, mk, umbral, sv)
                lo, hi = ic_roi(b.unid.values, n_boot)
                r[nombre] = {"n": len(b), "k": int(b.gana.sum()),
                             "acierto": float(b.gana.mean()) if len(b) else float("nan"),
                             "roi": float(b.unid.mean()) if len(b) else float("nan"), "lo": lo, "hi": hi,
                             "unid": float(b.unid.sum())}
            res[mk] = r
        return res
    finally:
        COLS = viejo


def tabla(res: dict, etiqueta: str = "") -> pd.DataFrame:
    filas = []
    for mk, r in res.items():
        filas.append({"mercado": mk, "n": r["n"], "ll": r["ll"], "ll_mk": r["ll_mk"], "br": r["br"], "br_mk": r["br_mk"],
                      "ece": r["ece"], "ece_mk": r["ece_mk"],
                      "acierto_todas": r["todas"]["acierto"], "roi_todas": r["todas"]["roi"] * 100,
                      "n_valor": r["valor"]["n"], "acierto_valor": r["valor"]["acierto"],
                      "roi_valor": r["valor"]["roi"] * 100, "ic_lo": r["valor"]["lo"] * 100, "ic_hi": r["valor"]["hi"] * 100})
    t = pd.DataFrame(filas)
    if etiqueta:
        t.insert(0, "variante", etiqueta)
    return t
