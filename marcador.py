"""MARCADOR: ¿el modelo gana de verdad? Califica cada prediccion guardada contra lo que paso y contra el mercado.

Idea: cada vez que corre el modelo guarda (en la base de datos) su prediccion y la linea de ese momento
(tablas `predicciones_modelo` y `lineas_historial`). Aqui se toma, para cada partido ya jugado, la ULTIMA prediccion
hecha ANTES del kickoff (asi nunca se califica una prediccion hecha con el resultado a la vista) y se mide:

  * Acierto del lado que favorece el modelo (ganador, spread, total) con su intervalo de confianza.
  * Log-loss y Brier frente al mercado (que tan buenas son las probabilidades, no solo si pego o no).
  * Error medio en puntos: modelo A, modelo B y la propia linea del mercado.
  * Unidades ganadas o perdidas apostando 1 unidad con las cuotas reales: a todos los partidos y solo a los
    «posibles valores» (los que el reporte marco).
  * CLV (valor frente a la linea de cierre): si la linea se movio hacia el lado que eligio el modelo. Es la
    prueba mas rapida de ventaja real, porque no depende de la suerte de un partido.
  * Calibracion: cuando dice 70 %, ¿pasa ~70 %?
  * Referencia del backtest (fuera de muestra, historico) para comparar contra lo que va en vivo.

Con pocos partidos TODO esto es ruido: la pagina lo dice y muestra cuantos partidos hacen falta.
Si hay archivos en semilla/ (predicciones_modelo.csv, lineas_historial.csv) se suman a lo guardado: son las
predicciones hechas en la laptop antes de pasar el modelo a la nube.
"""
from __future__ import annotations

import html
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
SEMILLA = AQUI / "semilla"
UMBRAL = 0.02
PUSH_ODDS = -110.0


# ------------------------------------------------------------------------------------------ utilidades
def _implied(o):
    o = np.asarray(o, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(o < 0, -o / (-o + 100), 100 / (o + 100))


def _payout(o):
    o = np.asarray(o, float)
    return np.where(o < 0, 100 / np.abs(o), o / 100)


def _devig(h, a):
    ph, pa = _implied(h), _implied(a)
    return ph / (ph + pa)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def _ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def _kickoff_utc(gameday, gametime) -> pd.Timestamp:
    d = pd.Timestamp(gameday).strftime("%Y-%m-%d")
    t = gametime if isinstance(gametime, str) and ":" in gametime else "12:00"
    return pd.Timestamp(f"{d} {t}").tz_localize("America/New_York", ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")


# ------------------------------------------------------------------------------------------ carga
def _leer(con, tabla: str) -> pd.DataFrame:
    try:
        return pd.read_sql(f"SELECT * FROM {tabla}", con)
    except Exception:
        return pd.DataFrame()


def cargar(con: sqlite3.Connection, games: pd.DataFrame | None = None, semilla: Path = SEMILLA):
    """Devuelve (predicciones, lineas, games) con las semillas ya sumadas y sin duplicados."""
    P, L = _leer(con, "predicciones_modelo"), _leer(con, "lineas_historial")
    for nombre, destino in (("predicciones_modelo", "P"), ("lineas_historial", "L")):
        f = semilla / f"{nombre}.csv"
        if f.exists():
            s = pd.read_csv(f)
            if destino == "P":
                P = pd.concat([P, s], ignore_index=True)
            else:
                L = pd.concat([L, s], ignore_index=True)
    if len(P):
        P = P.drop_duplicates(subset=["capturado", "game_id"], keep="last")
    if len(L):
        L = L.drop_duplicates(subset=["capturado", "game_id"], keep="last")
    if games is None:
        games = pd.read_sql("SELECT * FROM games", con)
    return P, L, games


def tabla_juegos(P: pd.DataFrame, L: pd.DataFrame, games: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Una fila por partido: ultima prediccion antes del kickoff + linea de ese momento + resultado y cierre.

    Devuelve tambien cuantos partidos tienen prediccion guardada pero aun no se juegan."""
    if P is None or P.empty:
        return pd.DataFrame(), 0
    g = games[["game_id", "gameday", "gametime", "home_team", "away_team", "result", "total", "home_score", "away_score",
               "spread_line", "total_line", "home_moneyline", "away_moneyline", "home_spread_odds", "away_spread_odds",
               "over_odds", "under_odds"]].copy()
    g = g.rename(columns={c: f"{c}_cierre" for c in ("spread_line", "total_line", "home_moneyline", "away_moneyline")})
    g["kick"] = [_kickoff_utc(a, b) for a, b in zip(g.gameday, g.gametime)]
    p = P.copy()
    p["cap"] = pd.to_datetime(p.capturado, utc=True)
    p = p.merge(g[["game_id", "kick"]], on="game_id", how="inner")
    p = p[p.cap < p.kick]                                   # solo predicciones hechas antes del partido
    p = p.sort_values("cap").groupby("game_id").tail(1).reset_index(drop=True)
    if p.empty:
        return pd.DataFrame(), 0
    if L is not None and len(L):
        l = L[["capturado", "game_id", "spread_line", "total_line", "home_moneyline", "away_moneyline"]].copy()
        l["cap_l"] = pd.to_datetime(l.capturado, utc=True)
        l = l.sort_values("cap_l")
        p = pd.merge_asof(p.sort_values("cap"), l.drop(columns="capturado"), left_on="cap", right_on="cap_l",
                          by="game_id", direction="backward")
    else:
        for c in ("spread_line", "total_line", "home_moneyline", "away_moneyline"):
            p[c] = np.nan
    t = p.merge(g.drop(columns=["kick"]), on="game_id", how="left")
    for c in ("spread_line", "total_line", "home_moneyline", "away_moneyline"):   # sin linea guardada: usa la de cierre
        t[c] = t[c].fillna(t[f"{c}_cierre"])
    pend = int(t.result.isna().sum())
    t = t[t.result.notna()].copy()
    t["gameday"] = pd.to_datetime(t.gameday)
    t["origen"] = "en vivo"
    return t.sort_values(["gameday", "game_id"]).reset_index(drop=True), pend


def _lado(p_a, odds_a, odds_b):
    ia, ib = _implied(odds_a), _implied(odds_b)
    ea, eb = p_a - ia, (1 - p_a) - ib
    a = ea >= eb
    return np.where(a, ea, eb), a


def reconstruidas(oos: pd.DataFrame | None, games: pd.DataFrame, cur: int, excluir=()) -> pd.DataFrame:
    """Partidos de la temporada actual que se jugaron ANTES de que el modelo empezara a guardar sus predicciones.

    Se usan las predicciones fuera de muestra (walk-forward): modelo entrenado solo con temporadas anteriores y ratings de
    cada equipo calculados solo con lo ocurrido antes de ese partido. No tienen linea al momento de la prediccion
    (se usa la de cierre), asi que no hay CLV para ellas."""
    if oos is None or oos.empty:
        return pd.DataFrame()
    d = oos[(oos.season == cur) & oos.result.notna() & ~oos.game_id.isin(list(excluir))].copy()
    if d.empty:
        return pd.DataFrame()
    col = lambda b: f"{b}_B_cal" if f"{b}_B_cal" in d.columns else f"{b}_B"
    d["p_gana_local"], d["p_cubre_local"], d["p_over"] = d[col("pwin")], d[col("pcov")], d[col("pover")]
    d = d.merge(games[["game_id", "home_score", "away_score"]], on="game_id", how="left")
    for c in ("spread_line", "total_line", "home_moneyline", "away_moneyline"):
        d[f"{c}_cierre"] = np.nan                                  # sin foto de la linea de ese momento: sin CLV
    ho, ao = d.home_spread_odds.fillna(PUSH_ODDS).values, d.away_spread_odds.fillna(PUSH_ODDS).values
    d["sp_edge"], a = _lado(d.p_cubre_local.values, ho, ao)
    d["sp_lado"] = np.where(a, d.home_team, d.away_team)
    ov, un = d.over_odds.fillna(PUSH_ODDS).values, d.under_odds.fillna(PUSH_ODDS).values
    d["to_edge"], a = _lado(d.p_over.values, ov, un)
    d["to_lado"] = np.where(a, "OVER", "UNDER")
    has = d.home_moneyline.notna() & d.away_moneyline.notna()
    e, a = _lado(d.p_gana_local.values, d.home_moneyline.fillna(-110).values, d.away_moneyline.fillna(-110).values)
    d["ml_edge"] = np.where(has, e, np.nan)
    d["ml_lado"] = np.where(a, d.home_team + " ML", d.away_team + " ML")
    d["gameday"] = pd.to_datetime(d.gameday)
    d["origen"] = "reconstruida"
    return d


# ------------------------------------------------------------------------------------------ calificacion
def _apuestas(t: pd.DataFrame, umbral: float) -> pd.DataFrame:
    """Una fila por (partido, mercado) con lado elegido, resultado, unidades y CLV. 'valor' = el reporte lo marco."""
    filas = []
    for r in t.itertuples():
        for mk in ("ganador", "spread", "total"):
            if mk == "ganador":
                if pd.isna(r.p_gana_local) or r.result == 0 or pd.isna(r.home_moneyline):
                    continue
                home = r.p_gana_local >= 0.5
                pick_p = r.p_gana_local if home else 1 - r.p_gana_local
                odds = r.home_moneyline if home else r.away_moneyline
                win, push = (r.result > 0) == home, False
                edge = getattr(r, "ml_edge", np.nan)
                valor = pd.notna(edge) and edge >= umbral
                if valor and isinstance(r.ml_lado, str):          # el lado de valor puede ser el otro
                    home = r.ml_lado.split()[0] == r.home_team
                    pick_p = r.p_gana_local if home else 1 - r.p_gana_local
                    odds, win = (r.home_moneyline if home else r.away_moneyline), (r.result > 0) == home
                clv = (_devig(r.home_moneyline_cierre, r.away_moneyline_cierre) - _devig(r.home_moneyline, r.away_moneyline)) \
                    if pd.notna(r.home_moneyline_cierre) and pd.notna(r.away_moneyline_cierre) else np.nan
                clv = None if pd.isna(clv) else float((clv if home else -clv) * 100)       # puntos de % de probabilidad
                filas.append((r.game_id, r.gameday, mk, bool(valor), pick_p, float(odds), win, False, clv))
            elif mk == "spread":
                if pd.isna(r.p_cubre_local) or pd.isna(r.spread_line):
                    continue
                s = r.spread_line
                home = (r.pred_mB > s) if (pd.notna(getattr(r, "pred_mB", np.nan)) and r.pred_mB != s) else r.p_cubre_local >= 0.5
                edge = getattr(r, "sp_edge", np.nan)
                valor = pd.notna(edge) and edge >= umbral
                if valor and isinstance(r.sp_lado, str):
                    home = r.sp_lado.split()[0] == r.home_team
                pick_p = r.p_cubre_local if home else 1 - r.p_cubre_local
                push = r.result == s
                win = (r.result > s) if home else (r.result < s)
                odds = (r.home_spread_odds if home else r.away_spread_odds)
                odds = PUSH_ODDS if pd.isna(odds) else odds
                sc = r.spread_line_cierre
                clv = None if pd.isna(sc) else float((sc - s) if home else (s - sc))        # puntos de linea a favor
                filas.append((r.game_id, r.gameday, mk, bool(valor), pick_p, float(odds), bool(win), bool(push), clv))
            else:
                if pd.isna(r.p_over) or pd.isna(r.total_line):
                    continue
                tl = r.total_line
                over = (r.pred_tB > tl) if (pd.notna(getattr(r, "pred_tB", np.nan)) and r.pred_tB != tl) else r.p_over >= 0.5
                edge = getattr(r, "to_edge", np.nan)
                valor = pd.notna(edge) and edge >= umbral
                if valor and isinstance(r.to_lado, str):
                    over = r.to_lado.upper().startswith("OVER")
                pick_p = r.p_over if over else 1 - r.p_over
                push = r.total == tl
                win = (r.total > tl) if over else (r.total < tl)
                odds = r.over_odds if over else r.under_odds
                odds = PUSH_ODDS if pd.isna(odds) else odds
                tc = r.total_line_cierre
                clv = None if pd.isna(tc) else float((tc - tl) if over else (tl - tc))
                filas.append((r.game_id, r.gameday, mk, bool(valor), pick_p, float(odds), bool(win), bool(push), clv))
    b = pd.DataFrame(filas, columns=["game_id", "fecha", "mercado", "valor", "p_lado", "cuota", "gana", "push", "clv"])
    b["clv"] = pd.to_numeric(b.clv, errors="coerce")
    b["unid"] = np.where(b.push, 0.0, np.where(b.gana, _payout(b.cuota), -1.0))
    return b


def _resumen(b: pd.DataFrame) -> dict:
    d = b[~b.push]
    n = len(d)
    k = int(d.gana.sum())
    lo, hi = wilson(k, n)
    return {"n": n, "k": k, "acierto": k / n if n else np.nan, "lo": lo, "hi": hi,
            "unid": float(b.unid.sum()), "roi": float(b.unid.sum() / len(b)) if len(b) else np.nan,
            "push": int(b.push.sum()),
            "clv": float(b.clv.mean()) if b.clv.notna().any() else np.nan,
            "clv_pos": int((b.clv > 0).sum()), "clv_neg": int((b.clv < 0).sum()), "clv_n": int(b.clv.notna().sum())}


def _calibracion(p: np.ndarray, y: np.ndarray, cortes=(0, .4, .5, .6, .7, 1.0001)) -> list[dict]:
    out = []
    p, y = np.asarray(p, float), np.asarray(y, float)
    for a, b in zip(cortes[:-1], cortes[1:]):
        m = (p >= a) & (p < b)
        if m.sum():
            out.append({"rango": f"{a * 100:.0f}–{min(b, 1) * 100:.0f} %", "n": int(m.sum()),
                        "dijo": float(p[m].mean()), "paso": float(y[m].mean())})
    return out


def calificar(t: pd.DataFrame, umbral: float = UMBRAL) -> dict:
    """Todas las metricas del marcador a partir de la tabla de partidos jugados."""
    if t.empty:
        return {"n": 0}
    out = {"n": len(t), "desde": t.gameday.min(), "hasta": t.gameday.max()}
    # --- calidad de las probabilidades
    pr = {}
    g = t[(t.result != 0) & t.p_gana_local.notna()]
    if len(g):
        y = (g.result > 0).astype(float).values
        pm = _devig(g.home_moneyline, g.away_moneyline) if g.home_moneyline.notna().all() else np.full(len(g), np.nan)
        ok = ~np.isnan(pm)
        pr["ganador"] = {"n": len(g), "ll": _ll(g.p_gana_local, y), "br": _brier(g.p_gana_local, y),
                         "ll_mk": _ll(pm[ok], y[ok]) if ok.any() else np.nan, "br_mk": _brier(pm[ok], y[ok]) if ok.any() else np.nan,
                         "n_mk": int(ok.sum()), "cal": _calibracion(g.p_gana_local.values, y),
                         "ll_mod_mk": _ll(g.p_gana_local.values[ok], y[ok]) if ok.any() else np.nan}
    c = t[(t.result != t.spread_line) & t.p_cubre_local.notna() & t.spread_line.notna()]
    if len(c):
        y = (c.result > c.spread_line).astype(float).values
        pr["spread"] = {"n": len(c), "ll": _ll(c.p_cubre_local, y), "br": _brier(c.p_cubre_local, y), "ll_mk": float(np.log(2)),
                        "br_mk": 0.25, "cal": _calibracion(c.p_cubre_local.values, y)}
    o = t[(t.total != t.total_line) & t.p_over.notna() & t.total_line.notna()]
    if len(o):
        y = (o.total > o.total_line).astype(float).values
        pr["total"] = {"n": len(o), "ll": _ll(o.p_over, y), "br": _brier(o.p_over, y), "ll_mk": float(np.log(2)),
                       "br_mk": 0.25, "cal": _calibracion(o.p_over.values, y)}
    out["prob"] = pr
    # --- ¿acierta mas cuando discrepa mas de la linea?
    dis = {}
    for mk, pc, lc, ycol in (("spread", "pred_mB", "spread_line", "result"), ("total", "pred_tB", "total_line", "total")):
        x = t[t[pc].notna() & t[lc].notna() & (t[ycol] != t[lc]) & (t[pc] != t[lc])].copy()
        if x.empty:
            continue
        gap = (x[pc] - x[lc]).abs()
        hit = ((x[pc] > x[lc]) == (x[ycol] > x[lc]))
        filas = []
        for a, b_, nom in ((0, 1, "menos de 1 pt"), (1, 2, "1 a 2 pts"), (2, 3, "2 a 3 pts"), (3, 99, "3 pts o más")):
            m = (gap >= a) & (gap < b_)
            if m.sum():
                filas.append({"rango": nom, "n": int(m.sum()), "acierto": float(hit[m].mean())})
        dis[mk] = filas
    out["discrep"] = dis
    # --- error en puntos
    mae = {}
    m = t[t.spread_line.notna()]
    if len(m):
        e = lambda x: float(np.mean(np.abs(m.result - x)))
        mae["margen"] = {"n": len(m), "mercado": e(m.spread_line), "B": e(m.pred_mB) if m.pred_mB.notna().all() else np.nan,
                         "A": e(m.pred_mA) if m.pred_mA.notna().all() else np.nan}
    m = t[t.total_line.notna() & t.pred_tB.notna()]
    if len(m):
        mae["total"] = {"n": len(m), "mercado": float(np.mean(np.abs(m.total - m.total_line))),
                        "B": float(np.mean(np.abs(m.total - m.pred_tB)))}
    out["mae"] = mae
    # --- apuestas
    b = _apuestas(t, umbral)
    out["apuestas"] = b
    # referencia ingenua: lo que habria pasado apostando siempre al mismo lado (sin modelo)
    ing = {}
    x = t[(t.result != 0)]
    if len(x):
        ing["local_gana"] = float((x.result > 0).mean())
    x = t[(t.result != t.spread_line) & t.spread_line.notna()]
    if len(x):
        ing["local_cubre"] = float((x.result > x.spread_line).mean())
    x = t[(t.total != t.total_line) & t.total_line.notna()]
    if len(x):
        ing["over"] = float((x.total > x.total_line).mean())
    out["ingenuo"] = ing
    out["todas"] = {mk: _resumen(b[b.mercado == mk]) for mk in ("ganador", "spread", "total") if (b.mercado == mk).any()}
    v = b[b.valor]
    out["valor"] = {mk: _resumen(v[v.mercado == mk]) for mk in ("ganador", "spread", "total") if (v.mercado == mk).any()}
    out["valor_total"] = _resumen(v) if len(v) else None
    # semana por semana y por origen (en vivo / reconstruida)
    wk = t.set_index("game_id")[["week", "origen"]]
    bb = b.join(wk, on="game_id")
    filas = []
    for k, x in bb.groupby("week"):
        row = {"semana": int(k), "partidos": int(x.game_id.nunique())}
        for mk in ("ganador", "spread", "total"):
            y = x[(x.mercado == mk) & ~x.push]
            row[mk] = float(y.gana.mean()) if len(y) else np.nan
        row["unid"] = float(x.unid.sum())
        row["unid_valor"] = float(x[x.valor].unid.sum())
        row["n_valor"] = int(x.valor.sum())
        row["en_vivo"] = int((t[t.week == k].origen == "en vivo").sum())
        filas.append(row)
    out["semanas"] = pd.DataFrame(filas)
    po = {}
    for k, x in bb.groupby("origen"):
        y = {"partidos": int(x.game_id.nunique()), "unid": float(x.unid.sum()), "unid_valor": float(x[x.valor].unid.sum()),
             "n_valor": int(x.valor.sum())}
        for mk in ("ganador", "spread", "total"):
            z = x[(x.mercado == mk) & ~x.push]
            y[mk] = float(z.gana.mean()) if len(z) else np.nan
        po[k] = y
    out["origen"] = po
    out["todas_total"] = _resumen(b) if len(b) else None
    return out


def referencia_backtest(oos: pd.DataFrame | None, desde: int = 2013, umbral: float = UMBRAL) -> dict | None:
    """Mismas metricas con las predicciones fuera de muestra (walk-forward) de temporadas pasadas."""
    if oos is None or oos.empty:
        return None
    d = oos[(oos.season >= desde) & oos.result.notna()].copy()
    col = lambda b: f"{b}_B_cal" if f"{b}_B_cal" in d.columns else f"{b}_B"
    out = {"desde": desde, "hasta": int(d.season.max())}
    pw, pc, po = col("pwin"), col("pcov"), col("pover")
    r = {}
    g = d[(d.result != 0) & d[pw].notna()]
    if len(g):
        y = (g.result > 0).astype(float)
        hit = ((g[pw] >= .5) == (g.result > 0)).mean()
        mk = g[g.home_moneyline.notna() & g.away_moneyline.notna()]
        r["ganador"] = {"n": len(g), "acierto": float(hit), "ll": _ll(g[pw], y),
                        "ll_mk": _ll(_devig(mk.home_moneyline, mk.away_moneyline), (mk.result > 0).astype(float)) if len(mk) else np.nan}
    c = d[(d.result != d.spread_line) & d[pc].notna()]
    if len(c):
        y = (c.result > c.spread_line).astype(float)
        r["spread"] = {"n": len(c), "acierto": float(((c[pc] >= .5) == (y > 0)).mean()), "ll": _ll(c[pc], y), "ll_mk": float(np.log(2))}
    o = d[(d.total != d.total_line) & d[po].notna()]
    if len(o):
        y = (o.total > o.total_line).astype(float)
        r["total"] = {"n": len(o), "acierto": float(((o[po] >= .5) == (y > 0)).mean()), "ll": _ll(o[po], y), "ll_mk": float(np.log(2))}
    # ROI de los «posibles valores» (lado con ventaja >= umbral) con las cuotas de la epoca
    roi = {}
    for mk, pcol, oa, ob, wa, wb in (
            ("spread", pc, "home_spread_odds", "away_spread_odds", lambda x: x.result > x.spread_line, lambda x: x.result < x.spread_line),
            ("total", po, "over_odds", "under_odds", lambda x: x.total > x.total_line, lambda x: x.total < x.total_line)):
        x = d[d[pcol].notna()].copy()
        oa_, ob_ = x[oa].fillna(PUSH_ODDS).values, x[ob].fillna(PUSH_ODDS).values
        ea, eb = x[pcol].values - _implied(oa_), (1 - x[pcol].values) - _implied(ob_)
        lado_a = ea >= eb
        edge = np.where(lado_a, ea, eb)
        win = np.where(lado_a, wa(x), wb(x))
        push = ~(wa(x) | wb(x))
        cuota = np.where(lado_a, oa_, ob_)
        sel = edge >= umbral
        u = np.where(push, 0.0, np.where(win, _payout(cuota), -1.0))
        roi[mk] = {"n": int(sel.sum()), "unid": float(u[sel].sum()), "roi": float(u[sel].mean()) if sel.any() else np.nan,
                   "se": float(u[sel].std() * np.sqrt(sel.sum())) if sel.sum() > 1 else np.nan,
                   "acierto": float(win[sel & ~push].mean()) if (sel & ~push).any() else np.nan}
    out["prob"], out["valor"] = r, roi
    m = d[d.spread_line.notna() & d.pred_mB.notna()]
    out["mae"] = {"margen": {"n": len(m), "mercado": float(np.mean(np.abs(m.result - m.spread_line))),
                             "B": float(np.mean(np.abs(m.result - m.pred_mB))),
                             "A": float(np.mean(np.abs(m.result - m.pred_mA)))}} if len(m) else {}
    return out


def calcular(con: sqlite3.Connection, games: pd.DataFrame | None = None, oos: pd.DataFrame | None = None,
             umbral: float = UMBRAL, semilla: Path = SEMILLA) -> dict | None:
    P, L, G = cargar(con, games, semilla)
    t, pend = tabla_juegos(P, L, G)
    cur = int(G.loc[G.result.notna(), "season"].max()) if G.result.notna().any() else None
    rec = reconstruidas(oos, G, cur, excluir=set(t.game_id) if len(t) else ()) if cur is not None else pd.DataFrame()
    if len(rec):
        t = pd.concat([t, rec], ignore_index=True, sort=False).sort_values(["gameday", "game_id"]).reset_index(drop=True)
    res = calificar(t, umbral)
    res["pendientes"] = pend
    res["tabla"] = t
    res["umbral"] = umbral
    res["ref"] = referencia_backtest(oos, umbral=umbral)
    return res


# ------------------------------------------------------------------------------------------ HTML
MK_NOMBRE = {"ganador": "Ganador del partido", "spread": "Cubrir el spread", "total": "Over / under del total"}
MK_BREAK = {"ganador": None, "spread": 0.524, "total": 0.524}


def _pc(x, d=0):
    return "–" if x is None or pd.isna(x) else f"{x * 100:.{d}f} %"


def _un(x):
    if x is None or pd.isna(x):
        return "–"
    c = "#0a7d3c" if x > 0.005 else ("#b3261e" if x < -0.005 else "inherit")
    return f'<span style="color:{c}">{x:+.2f}</span>'


def _veredicto(res: dict) -> str:
    n = res["n"]
    if n < 30:
        return (f'<p class="mc-v"><b>Muestra todavía muy pequeña ({n} partidos calificados).</b> Con tan pocos partidos cualquier resultado '
                f'—bueno o malo— es azar: un solo fin de semana puede inclinar todo. Úsalo para ver que el sistema funciona, no para concluir nada.</p>')
    ev = res.get("valor_total")
    ac = res.get("todas_total")
    base = ac["roi"] if ac else np.nan
    txt = f"<b>{n} partidos calificados.</b> "
    if ev and ev["n"] >= 20:
        txt += f"En los «posibles valores» el resultado es {ev['unid']:+.1f} unidades en {len(res['apuestas'][res['apuestas'].valor])} apuestas (ROI {ev['roi'] * 100:+.1f} %). "
    txt += "Para confirmar una ventaja real de 2–3 puntos sobre el punto de equilibrio hacen falta más de 1,000 apuestas; antes de eso, el CLV es la señal más rápida."
    return f'<p class="mc-v">{txt}</p>'


def _ingenuo(res: dict) -> str:
    i = res.get("ingenuo") or {}
    if not i:
        return ""
    partes = []
    if "local_gana" in i:
        partes.append(f"el local ganó {_pc(i['local_gana'])}")
    if "local_cubre" in i:
        partes.append(f"el local cubrió el spread {_pc(i['local_cubre'])} (la visita {_pc(1 - i['local_cubre'])})")
    if "over" in i:
        partes.append(f"el over pegó {_pc(i['over'])}")
    return ('<p class="explain"><b>Para no engañarnos:</b> en estos mismos partidos ' + ", ".join(partes) + ". Si una racha del modelo se parece a "
            "apostar siempre al mismo lado, lo más probable es que el mercado se haya desviado esas semanas y no que el modelo sepa algo.</p>")


def _fila_mercado(mk: str, res: dict) -> str:
    a, v = res["todas"].get(mk), res["valor"].get(mk)
    pr = res["prob"].get(mk)
    if not a:
        return ""
    ci = f"{_pc(a['lo'])}–{_pc(a['hi'])}"
    clv = "–"
    if a["clv_n"]:
        u = "pts de %" if mk == "ganador" else "pts"
        clv = f"{a['clv']:+.2f} {u} ({a['clv_pos']}↑ / {a['clv_neg']}↓ de {a['clv_n']})"
    llm = f"{pr['ll']:.3f} vs {pr['ll_mk']:.3f}" if pr and pd.notna(pr.get("ll_mk")) else (f"{pr['ll']:.3f}" if pr else "–")
    val = (f"{v['n']} apuestas · {_pc(v['acierto'])} · {_un(v['unid'])} u") if v else "ninguna marcada"
    return (f"<tr><td><b>{MK_NOMBRE[mk]}</b></td><td>{a['n']}</td><td>{_pc(a['acierto'])}<br><small>95 %: {ci}</small></td>"
            f"<td>{_un(a['unid'])} u<br><small>ROI {a['roi'] * 100:+.1f} %</small></td><td>{val}</td><td>{llm}</td><td>{clv}</td></tr>")


def _dis_html(res: dict) -> str:
    bl = []
    for mk, ttl in (("spread", "Spread"), ("total", "Total")):
        f = res.get("discrep", {}).get(mk)
        if not f:
            continue
        filas = "".join(f"<tr><td>{c['rango']}</td><td>{c['n']}</td><td>{_pc(c['acierto'])}</td></tr>" for c in f)
        bl.append(f"<div><h4>{ttl}: acierto según cuánto se aleja el modelo de la línea</h4><table><thead><tr><th>Diferencia modelo vs línea</th><th>Partidos</th><th>Acierto</th></tr></thead><tbody>{filas}</tbody></table></div>")
    if not bl:
        return ""
    return (f'<div class="grid2" style="margin-top:1em">{"".join(bl)}</div>'
            '<p class="explain">Si el modelo supiera algo que el mercado no, el acierto debería subir cuando se aleja más de la línea. Si es plano o baja, esa diferencia es ruido.</p>')


def _cal_html(res: dict) -> str:
    bloques = []
    for mk in ("ganador",):
        pr = res["prob"].get(mk)
        if not pr or not pr["cal"]:
            continue
        filas = "".join(f"<tr><td>{c['rango']}</td><td>{c['n']}</td><td>{_pc(c['dijo'])}</td><td>{_pc(c['paso'])}</td></tr>" for c in pr["cal"])
        bloques.append(f"<div><h4>{MK_NOMBRE[mk]}</h4><table><thead><tr><th>Probabilidad dada al local / over</th><th>Partidos</th><th>Promedio que dijo</th><th>Pasó</th></tr></thead><tbody>{filas}</tbody></table></div>")
    return f'<div class="grid2">{"".join(bloques)}</div>' if bloques else ""


def _grafica(b: pd.DataFrame) -> str:
    """Unidades acumuladas por fecha: todas las apuestas al lado del modelo vs solo los posibles valores."""
    if b.empty:
        return ""
    series = []
    for nombre, x, col in (("Todas las apuestas (lado que favorece el modelo)", b, "#2a78d6"),
                           ("Solo «posibles valores»", b[b.valor], "#eb6834")):
        if x.empty:
            continue
        s = x.groupby("fecha").unid.sum().sort_index().cumsum()
        series.append((nombre, s, col))
    if not series:
        return ""
    fechas = sorted(set().union(*[set(s.index) for _, s, _ in series]))
    if len(fechas) < 2:
        return '<p class="explain">La gráfica de unidades acumuladas aparece cuando haya partidos de al menos dos fechas distintas.</p>'
    W, H, pl, pr_, pt, pb = 640, 230, 46, 14, 14, 28
    allv = [0.0] + [float(v) for _, s, _ in series for v in s.values]
    lo, hi = min(allv), max(allv)
    pad = max(1.0, (hi - lo) * 0.1)
    lo, hi = lo - pad, hi + pad
    X = lambda i: pl + (W - pl - pr_) * i / (len(fechas) - 1)
    Y = lambda v: pt + (H - pt - pb) * (hi - v) / (hi - lo)
    svg = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:{W}px;height:auto" role="img" aria-label="Unidades acumuladas">']
    for v in np.linspace(lo, hi, 5):
        svg.append(f'<line x1="{pl}" x2="{W - pr_}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="currentColor" opacity=".12"/>'
                   f'<text x="{pl - 6}" y="{Y(v) + 4:.1f}" font-size="11" text-anchor="end" fill="currentColor" opacity=".7">{v:+.0f}</text>')
    svg.append(f'<line x1="{pl}" x2="{W - pr_}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="currentColor" opacity=".55" stroke-dasharray="4 3"/>')
    for nombre, s, col in series:
        s = s.reindex(fechas).ffill().fillna(0)
        pts = " ".join(f"{X(i):.1f},{Y(float(v)):.1f}" for i, v in enumerate(s.values))
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="round"/>')
        svg.append(f'<circle cx="{X(len(fechas) - 1):.1f}" cy="{Y(float(s.values[-1])):.1f}" r="3.5" fill="{col}"/>')
    for i in (0, len(fechas) - 1):
        svg.append(f'<text x="{X(i):.1f}" y="{H - 8}" font-size="11" text-anchor="{"start" if i == 0 else "end"}" fill="currentColor" opacity=".7">{pd.Timestamp(fechas[i]).strftime("%d/%m")}</text>')
    svg.append("</svg>")
    leyenda = "".join(f'<span style="margin-right:14px"><i style="display:inline-block;width:14px;height:3px;background:{c};vertical-align:middle;margin-right:5px"></i>{html.escape(n)}</span>'
                      for n, _, c in series)
    return f'<div class="chart" style="color:var(--ink)">{"".join(svg)}<div class="explain" style="font-size:.85rem">{leyenda}</div></div>'


def _mae_html(res: dict) -> str:
    m = res.get("mae", {})
    filas = []
    if "margen" in m:
        x = m["margen"]
        filas.append(f"<tr><td>Margen del partido</td><td>{x['n']}</td><td>{x['mercado']:.2f}</td><td>{x['B']:.2f}</td><td>{x['A']:.2f}</td></tr>")
    if "total" in m:
        x = m["total"]
        filas.append(f"<tr><td>Total de puntos</td><td>{x['n']}</td><td>{x['mercado']:.2f}</td><td>{x['B']:.2f}</td><td>–</td></tr>")
    if not filas:
        return ""
    return ('<h3 style="margin-top:1.2em">Error medio en puntos (menos es mejor)</h3>'
            '<table><thead><tr><th></th><th>Partidos</th><th>Línea del mercado</th><th>Modelo B (el de decisión)</th><th>Modelo A (sin mercado)</th></tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table>'
            '<p class="explain">Si el modelo B no baja del error de la línea, no está viendo nada que el mercado no vea.</p>')


def _semanas_html(res: dict) -> str:
    w = res.get("semanas")
    if w is None or w.empty:
        return ""
    filas = []
    for r in w.itertuples():
        filas.append(f"<tr><td><b>{r.semana}</b></td><td>{r.partidos}</td><td>{_pc(r.ganador)}</td><td>{_pc(r.spread)}</td><td>{_pc(r.total)}</td>"
                     f"<td>{_un(r.unid)} u</td><td>{r.n_valor} · {_un(r.unid_valor)} u</td>"
                     f"<td>{'en vivo' if r.en_vivo == r.partidos else ('reconstruida' if r.en_vivo == 0 else 'mixta')}</td></tr>")
    po = res.get("origen", {})
    ori = ""
    if len(po) > 1:
        nom = {"en vivo": "Guardadas antes del partido (en vivo)", "reconstruida": "Reconstruidas (semanas previas al primer guardado)"}
        f2 = "".join(f"<tr><td>{nom.get(k, k)}</td><td>{v['partidos']}</td><td>{_pc(v['ganador'])}</td><td>{_pc(v['spread'])}</td><td>{_pc(v['total'])}</td>"
                     f"<td>{_un(v['unid'])} u</td></tr>" for k, v in po.items())
        ori = ('<h4 style="margin-top:1em">Según el origen de la predicción</h4><table><thead><tr><th>Origen</th><th>Partidos</th><th>Ganador</th><th>Spread</th><th>Total</th>'
               f'<th>Unidades (apostando a todos)</th></tr></thead><tbody>{f2}</tbody></table>')
    return ('<h3 style="margin-top:1.2em">Semana por semana</h3><div style="overflow-x:auto"><table><thead><tr><th>Semana</th><th>Partidos</th><th>Ganador</th><th>Spread</th><th>Total</th>'
            '<th>Unidades (todos)</th><th>«Posibles valores»</th><th>Predicción</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table></div>"
            '<p class="explain">El acierto es el del lado que favorecía el modelo. Semana a semana hay solo ~14 partidos: un fin de semana bueno o malo no significa nada por sí solo.</p>' + ori)


def _recientes(t: pd.DataFrame, nombre, n: int = 16) -> str:
    if t.empty:
        return ""
    filas = []
    for r in t.sort_values("gameday", ascending=False).head(n).itertuples():
        marc = f"{int(r.away_score)}–{int(r.home_score)}" if pd.notna(r.home_score) else "–"
        tiene_m = pd.notna(getattr(r, "pred_mB", np.nan)) and r.pred_mB != r.spread_line
        sl = (r.pred_mB > r.spread_line) if tiene_m else (r.p_cubre_local >= .5)
        d_m = f" ({r.pred_mB - r.spread_line:+.1f} vs línea)" if tiene_m else ""
        cub = ("local" if sl else "visita") + d_m
        rc = "push" if r.result == r.spread_line else ("local" if r.result > r.spread_line else "visita")
        tiene_t = pd.notna(getattr(r, "pred_tB", np.nan)) and r.pred_tB != r.total_line
        ol = (r.pred_tB > r.total_line) if tiene_t else (r.p_over >= .5)
        d_t = f" ({r.pred_tB - r.total_line:+.1f} vs línea)" if tiene_t else ""
        ov = ("over" if ol else "under") + d_t
        ro = "push" if r.total == r.total_line else ("over" if r.total > r.total_line else "under")
        ok_c = "" if rc == "push" else (" ✔" if (rc == "local") == sl else " ✘")
        ok_o = "" if ro == "push" else (" ✔" if (ro == "over") == ol else " ✘")
        gan = "–" if pd.isna(r.p_gana_local) else (f"{nombre(r.home_team)} {_pc(r.p_gana_local)}" if r.p_gana_local >= .5 else f"{nombre(r.away_team)} {_pc(1 - r.p_gana_local)}")
        ok_g = "" if r.result == 0 or pd.isna(r.p_gana_local) else (" ✔" if (r.result > 0) == (r.p_gana_local >= .5) else " ✘")
        filas.append(f"<tr><td>{pd.Timestamp(r.gameday).strftime('%d/%m')}</td><td>{html.escape(nombre(r.away_team))} @ {html.escape(nombre(r.home_team))}</td>"
                     f"<td>{marc}</td><td>{gan}{ok_g}</td><td>{cub}{ok_c}<br><small>línea {r.spread_line:+g}</small></td>"
                     f"<td>{ov}{ok_o}<br><small>línea {r.total_line:g} · total {r.total:g}</small></td></tr>")
    return ('<h3 style="margin-top:1.2em">Últimos partidos calificados</h3><div style="overflow-x:auto"><table><thead><tr><th>Fecha</th><th>Partido</th><th>Marcador</th>'
            '<th>Ganador (modelo)</th><th>Spread: lado del modelo</th><th>Total: lado del modelo</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table></div>")


def _ref_html(ref: dict | None) -> str:
    if not ref or not ref.get("prob"):
        return ""
    filas = []
    for mk in ("ganador", "spread", "total"):
        p = ref["prob"].get(mk)
        if not p:
            continue
        v = ref["valor"].get(mk)
        vt = (f"{v['n']:,} apuestas · acierto {_pc(v['acierto'], 1)} · {_un(v['unid'])} u (ROI {v['roi'] * 100:+.1f} %)"
              f"<br><small>el azar solo mueve ±{v['se']:.0f} u; resultado = {v['unid'] / v['se']:+.1f} veces ese margen</small>") if v and v.get("se") else "–"
        llm = f"{p['ll']:.3f} vs {p['ll_mk']:.3f}" if pd.notna(p.get("ll_mk")) else f"{p['ll']:.3f}"
        filas.append(f"<tr><td><b>{MK_NOMBRE[mk]}</b></td><td>{p['n']:,}</td><td>{_pc(p['acierto'], 1)}</td><td>{llm}</td><td>{vt if mk != 'ganador' else '–'}</td></tr>")
    return (f'<details class="mc-ref"><summary><b>Referencia: el mismo examen en el historial {ref["desde"]}–{ref["hasta"]} (fuera de muestra)</b></summary>'
            '<p class="explain">Predicciones hechas solo con datos anteriores a cada partido (walk-forward), con cuotas de la época. '
            'Es la vara contra la que se compara lo que va en vivo: con miles de partidos el azar casi desaparece. '
            'Ojo con los «posibles valores»: se eligen por ventaja sobre el precio, y con probabilidades cercanas a 50 % eso favorece a los lados con cuota asimétrica (por ejemplo +105 contra −125). '
            'Un resultado de 1–2 veces el margen del azar <b>no confirma</b> una ventaja; para fiarse hace falta que se repita en vivo y con CLV positivo.</p>'
            '<div style="overflow-x:auto"><table><thead><tr><th>Mercado</th><th>Partidos</th><th>Acierto del lado del modelo</th><th>Log-loss modelo vs mercado</th>'
            f'<th>«Posibles valores» (ventaja ≥ {UMBRAL * 100:.0f} pts)</th></tr></thead><tbody>{"".join(filas)}</tbody></table></div></details>')


def _origen_txt(res: dict) -> str:
    po = res.get("origen", {})
    v, r = po.get("en vivo", {}).get("partidos", 0), po.get("reconstruida", {}).get("partidos", 0)
    if r and v:
        return f"{v} con la predicción guardada antes del partido y {r} reconstruidos"
    return f"{v} con la predicción guardada antes del partido" if v else f"{r} reconstruidos"


def _nota_reconstruidas(res: dict) -> str:
    if not res.get("origen", {}).get("reconstruida"):
        return ""
    return ('<p class="explain"><b>Reconstruidos:</b> el modelo empezó a guardar sus predicciones en la semana 9; para las semanas anteriores se reconstruyó lo que habría dicho con solo '
            'datos previos a cada partido (modelo entrenado con temporadas anteriores, ratings con lo ocurrido antes de ese juego) y se compara con la línea de cierre. Es una buena aproximación, '
            'pero no es lo mismo que una predicción hecha en tiempo real: no hay CLV para esos partidos.</p>')


# ------------------------------------------------------------------------------------------ RECORD DE ELECCIONES
def registro(t: pd.DataFrame) -> pd.DataFrame:
    """Una fila por partido jugado con la ELECCION del modelo en cada mercado y si acerto (True/False/None si empate/push).

    Ganador: el equipo con mas de 50 % de probabilidad de ganar. Spread: el lado hacia el que apunta el margen esperado
    del modelo B (si no hay, el de mas de 50 % de cubrir). Total: over o under igual. Spread y total coinciden con la
    tabla de acierto; en ganador aqui se cuenta siempre al favorito del modelo (la tabla cambia al lado «de valor» cuando
    el reporte marco uno, por eso puede diferir un poco)."""
    filas = []
    for r in t.sort_values(["gameday", "game_id"]).itertuples():
        d = {"game_id": r.game_id, "fecha": r.gameday, "week": getattr(r, "week", np.nan), "origen": getattr(r, "origen", ""),
             "away": r.away_team, "home": r.home_team, "marcador": (f"{int(r.away_score)}–{int(r.home_score)}" if pd.notna(r.home_score) else "–")}
        if pd.notna(r.p_gana_local) and r.result != 0:
            home = r.p_gana_local >= 0.5
            d.update(g_eq=(r.home_team if home else r.away_team), g_p=(r.p_gana_local if home else 1 - r.p_gana_local),
                     g_ok=bool((r.result > 0) == home))
        if pd.notna(r.p_cubre_local) and pd.notna(r.spread_line):
            pm = getattr(r, "pred_mB", np.nan)
            home = (pm > r.spread_line) if (pd.notna(pm) and pm != r.spread_line) else r.p_cubre_local >= 0.5
            d.update(s_eq=(r.home_team if home else r.away_team), s_linea=(-r.spread_line if home else r.spread_line),
                     s_ok=(None if r.result == r.spread_line else bool((r.result > r.spread_line) == home)))
        if pd.notna(r.p_over) and pd.notna(r.total_line):
            pt = getattr(r, "pred_tB", np.nan)
            over = (pt > r.total_line) if (pd.notna(pt) and pt != r.total_line) else r.p_over >= 0.5
            d.update(t_lado=("OVER" if over else "UNDER"), t_linea=r.total_line, t_total=r.total,
                     t_ok=(None if r.total == r.total_line else bool((r.total > r.total_line) == over)))
        filas.append(d)
    return pd.DataFrame(filas)


def _wl(x: pd.Series) -> tuple[int, int, int]:
    """(ganadas, perdidas, empates) de una serie True/False/None."""
    ok = x.dropna()
    return int(ok.sum()), int((~ok.astype(bool)).sum()), int(x.isna().sum())


def _racha(x: pd.Series) -> str:
    ok = [bool(v) for v in x.dropna().tolist()]
    if not ok:
        return "–"
    n = 1
    while n < len(ok) and ok[-1 - n] == ok[-1]:
        n += 1
    return f"{'G' if ok[-1] else 'P'}{n}"


def _marca(v) -> str:
    return '<span class="rk-pu">push</span>' if v is None or (isinstance(v, float) and np.isnan(v)) else (
        '<span class="rk-w">✔ ganó</span>' if v else '<span class="rk-l">✘ perdió</span>')


def _record_html(res: dict, nombre=lambda t: t) -> str:
    t = res.get("tabla")
    if t is None or t.empty:
        return ""
    R = registro(t)
    if R.empty:
        return ""
    tarjetas = []
    for col, ttl, sub in (("g_ok", "Ganador del partido", "el equipo que el modelo eligió para ganar"),
                          ("s_ok", "Spread", "el lado de la línea que eligió el modelo"),
                          ("t_ok", "Over / Under", "el lado del total que eligió el modelo")):
        if col not in R.columns or R[col].dropna().empty:
            continue
        w, l, e = _wl(R[col])
        n = w + l
        vivo = R[R.origen == "en vivo"][col]
        extra = ""
        if len(vivo) and len(vivo) < len(R):
            wv, lv, _ = _wl(vivo)
            extra = f'<br><small>solo guardadas antes del partido: {wv}-{lv}</small>'
        ult = "".join(('<i class="rk-w">●</i>' if bool(v) else '<i class="rk-l">●</i>') for v in R[col].dropna().tail(10))
        tarjetas.append(
            f'<div class="rk-card"><span class="rk-t">{ttl}</span><b class="rk-n">{w}-{l}{f"-{e}" if e else ""}</b>'
            f'<span class="rk-p">{_pc(w / n) if n else "–"} de aciertos · racha {_racha(R[col])}</span>'
            f'<span class="rk-d">{sub}{extra}</span><span class="rk-f" title="últimas 10 elecciones, la más reciente a la derecha">{ult}</span></div>')
    if not tarjetas:
        return ""
    # --- por semana
    filas = []
    for k, x in R.groupby("week"):
        celdas = []
        for col in ("g_ok", "s_ok", "t_ok"):
            if col in x.columns:
                w, l, e = _wl(x[col])
                celdas.append(f"<td><b>{w}-{l}</b>{f'-{e}' if e else ''}</td>")
            else:
                celdas.append("<td>–</td>")
        filas.append(f"<tr><td><b>{int(k)}</b></td><td>{len(x)}</td>{''.join(celdas)}</tr>")
    semanas = ('<h3 style="margin-top:1em">Récord semana por semana</h3><div style="overflow-x:auto"><table><thead><tr><th>Semana</th><th>Partidos</th>'
               '<th>Ganador</th><th>Spread</th><th>Over / Under</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table></div>")
    # --- cada eleccion
    lin = []
    for r in R.sort_values(["fecha", "game_id"], ascending=False).itertuples():
        g = "–" if not isinstance(getattr(r, "g_eq", None), str) else (
            f"<b>{html.escape(nombre(r.g_eq))}</b> ({_pc(r.g_p)})<br>{_marca(r.g_ok)}")
        s = "–" if not isinstance(getattr(r, "s_eq", None), str) else (
            f"<b>{html.escape(nombre(r.s_eq))} {r.s_linea:+g}</b><br>{_marca(r.s_ok)}")
        o = "–" if not isinstance(getattr(r, "t_lado", None), str) else (
            f"<b>{r.t_lado} {r.t_linea:g}</b> <small>(total {r.t_total:g})</small><br>{_marca(r.t_ok)}")
        lin.append(f"<tr><td>{pd.Timestamp(r.fecha).strftime('%d/%m')}</td><td>{html.escape(nombre(r.away))} @ {html.escape(nombre(r.home))}<br><small>{r.marcador}</small></td>"
                   f"<td>{g}</td><td>{s}</td><td>{o}</td></tr>")
    detalle = (f'<details class="rk-det"><summary><b>Ver cada elección ({len(R)} partidos)</b></summary><div style="overflow-x:auto"><table><thead><tr><th>Fecha</th><th>Partido</th>'
               '<th>Ganador elegido</th><th>Spread elegido</th><th>Total elegido</th></tr></thead><tbody>' + "".join(lin) + "</tbody></table></div></details>")
    return (f'<h3 id="record" style="margin-top:1em">Récord de elecciones del modelo en la temporada</h3>'
            '<p class="explain">En cada partido el modelo elige un lado; aquí se cuenta cuántas veces acertó (<b>ganadas-perdidas</b>, y empates/push al final si los hay). '
            'El récord de «Ganador» es el de las veces que el equipo elegido ganó el partido, sin importar cuánto pagaba: elegir al favorito acierta mucho más que apostar con ventaja. '
            'Para saber si de verdad hay ventaja hay que ver también las unidades y el CLV de más abajo. (La columna «Ganador» de la tabla de abajo puede diferir un poco: ahí, si el reporte marcó un «posible valor», se cuenta el lado con ventaja aunque no sea el favorito.)</p>'
            f'<div class="rk-grid">{"".join(tarjetas)}</div>{semanas}{detalle}')


def html_marcador(res: dict | None, nombre=lambda t: t) -> str:
    if not res or res.get("n", 0) == 0:
        pend = (res or {}).get("pendientes", 0)
        extra = f" Hay {pend} partido(s) con predicción guardada esperando su resultado." if pend else ""
        return ('<h2 id="marcador">Marcador: ¿el modelo gana de verdad?</h2><p class="explain">Aún no hay partidos jugados con una predicción guardada antes del kickoff. '
                f'Desde la próxima corrida después de los partidos aparecerá aquí.{extra}</p>')
    filas = "".join(_fila_mercado(mk, res) for mk in ("ganador", "spread", "total"))
    d0, d1 = pd.Timestamp(res["desde"]).strftime("%d/%m/%Y"), pd.Timestamp(res["hasta"]).strftime("%d/%m/%Y")
    vt = res.get("valor_total")
    cab = ""
    if vt:
        nb = int(res["apuestas"].valor.sum())
        clv_txt = "–" if pd.isna(vt["clv"]) else "%+.2f" % vt["clv"]
        cab = (f'<div class="mc-kpis"><div><b>{nb}</b><span>apuestas «con valor» marcadas</span></div>'
               f'<div><b>{_un(vt["unid"])}</b><span>unidades (1 u por apuesta)</span></div>'
               f'<div><b>{_pc(vt["acierto"])}</b><span>acierto (equilibrio ≈ 52 %)</span></div>'
               f'<div><b>{clv_txt}</b><span>CLV medio (solo en vivo)</span></div></div>')
    return f"""<h2 id="marcador">Marcador: ¿el modelo gana de verdad?</h2>
<p class="explain">Cada predicción se guarda <b>antes</b> del partido y aquí se califica contra el resultado real y contra el mercado. Las guardadas en vivo solo cuentan si se hicieron antes del kickoff; las reconstruidas usan únicamente datos previos al partido.
Calificados <b>{res['n']}</b> partidos de la temporada ({d0} – {d1}), {_origen_txt(res)}{f" · {res['pendientes']} más esperan su resultado" if res['pendientes'] else ""}.</p>
{_record_html(res, nombre)}
{_nota_reconstruidas(res)}
{_veredicto(res)}
{_ingenuo(res)}
{cab}
<div style="overflow-x:auto"><table class="mc-t"><thead><tr><th>Mercado</th><th>Partidos</th><th>Acierto del lado que favorece el modelo</th><th>Unidades (apostando a todos)</th><th>«Posibles valores»</th><th>Log-loss (modelo vs mercado)</th><th>CLV (línea de cierre)</th></tr></thead><tbody>{filas}</tbody></table></div>
<details class="mc-ayuda"><summary><b>Cómo leer cada columna</b></summary>
<ul><li><b>Acierto</b>: % de veces que pasó lo que el modelo veía más probable (en spread y total, el lado al que apunta el modelo B: si su margen o total esperado queda por encima o por debajo de la línea). En spread y total el punto de equilibrio con cuota −110 es <b>52.4 %</b>; el intervalo del 95 % muestra cuánto puede ser solo azar.</li>
<li><b>Unidades</b>: ganancia o pérdida apostando 1 unidad a ese lado con la cuota real (+ si gana, − si pierde, 0 si hay push).</li>
<li><b>Posibles valores</b>: solo las apuestas que el reporte marcó con ventaja ≥ {res['umbral'] * 100:.0f} puntos sobre lo que paga el mercado.</li>
<li><b>Log-loss</b>: mide qué tan buenas son las probabilidades (menos es mejor; 0.693 = lanzar una moneda). Frente al mercado importa que sea <i>menor</i>.</li>
<li><b>CLV</b>: si la línea se movió a favor del lado que eligió el modelo entre su predicción y el cierre (positivo = el mercado terminó dándole la razón). Quien tiene ventaja real casi siempre tiene CLV positivo, aun antes de que se note en las ganancias.</li></ul></details>
{_grafica(res['apuestas'])}
{_semanas_html(res)}
{_mae_html(res)}
{_dis_html(res)}
{_cal_html(res)}
{_recientes(res['tabla'], nombre)}
{_ref_html(res.get('ref'))}
<p class="explain" style="font-size:.85rem">Falta todavía calificar las proyecciones de jugadores (props); hoy este marcador cubre ganador, spread y total. Nada de esto es asesoría financiera.</p>"""


CSS = """
.mc-v{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--orange);border-radius:10px;padding:10px 14px;margin:.6em 0}
.mc-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:.8em 0}.mc-kpis div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.mc-kpis b{display:block;font-size:1.5rem}.mc-kpis span{color:var(--ink2);font-size:.82rem}@media(max-width:700px){.mc-kpis{grid-template-columns:1fr 1fr}}
.mc-t small,.mc-ref small{color:var(--ink2)}.mc-ayuda,.mc-ref{margin:.6em 0}
.rk-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:.8em 0}.rk-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.rk-t{font-weight:700}.rk-n{font-size:2.3rem;line-height:1.1;letter-spacing:.5px}.rk-p{font-size:.9rem}.rk-d,.rk-d small{color:var(--ink2);font-size:.8rem}
.rk-f{margin-top:4px;letter-spacing:2px;font-size:.9rem}.rk-f i{font-style:normal}.rk-w{color:#0a7d3c}.rk-l{color:#b3261e}.rk-pu{color:var(--ink2)}.rk-det{margin:.8em 0}
@media(max-width:700px){.rk-grid{grid-template-columns:1fr}}
"""
