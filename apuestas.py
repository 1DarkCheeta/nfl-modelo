"""Registro y liquidacion de TUS apuestas: mide con tu dinero si el metodo funciona (ROI, acierto, calibracion, CLV).

Se guardan en data/mis_apuestas.csv (se abre en Excel). Tipos: prop (jugador), ml (ganador), spread (handicap), total (puntos).
La liquidacion es automatica con los resultados reales de nflverse (props: estadisticas y snaps del jugador).
CLV = si apostaste a un precio mejor que el de cierre (el mejor indicador temprano de que tu metodo tiene valor).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import numpy as np
import pandas as pd

from data import DATA

RUTA = DATA / "mis_apuestas.csv"
COLS = ["id", "fecha", "temporada", "semana", "game_id", "tipo", "jugador", "player_id", "equipo", "rival", "mercado", "linea", "lado",
        "cuota", "casa", "monto", "prob_modelo", "cierre", "resultado", "estadistica", "ganancia", "clv", "nota"]
STAT = {"pass_yds": "pass_yds", "pass_cmp": "cmp", "pass_td": "pass_td", "pass_int": "pass_int", "rush_yds": "rush_yds", "rush_att": "car",
        "rec_yds": "rec_yds", "rec": "rec", "tgt": "tgt", "td": "td"}
COMISION_KALSHI = 0.07


# ---------------------------------------------------------------- cuotas
def _num(x):
    try:
        return float(str(x).replace(",", ".").replace("¢", "").replace("c", "").strip())
    except Exception:
        return np.nan


def parse_cuota(x, casa: str = "") -> tuple[float, float, bool]:
    """Devuelve (prob_implicita, ganancia_por_unidad_si_gana, es_precio_kalshi). Acepta americana (+150, -110), decimal (2.5) o precio de Kalshi (44c, 0.44)."""
    s = str(x).strip().lower()
    v = _num(s)
    if np.isnan(v):
        return np.nan, np.nan, False
    if s.endswith("c") or s.endswith("¢") or (0 < v < 1) or (str(casa).lower() == "kalshi" and 0 < v < 100 and abs(v) < 100 and not s.startswith(("+", "-"))):
        p = v / 100 if v >= 1 else v
        return p, (1 - p) / p, True
    if 1.01 <= v < 20 and not s.startswith(("+", "-")):          # cuota decimal
        return 1 / v, v - 1, False
    if v >= 100:
        return 100 / (v + 100), v / 100, False
    if v <= -100:
        return -v / (-v + 100), 100 / -v, False
    return np.nan, np.nan, False


def _ganancia(monto: float, cuota, casa: str, resultado: str) -> float:
    if resultado in ("anulada", "empate", "pendiente"):
        return 0.0
    p, b, kal = parse_cuota(cuota, casa)
    if np.isnan(b):
        return np.nan
    if resultado == "perdio":
        return -monto
    if kal:      # contratos = monto / precio; comision de Kalshi por contrato
        n = monto / p
        return n * (1 - p) - COMISION_KALSHI * p * (1 - p) * n
    return monto * b


# ---------------------------------------------------------------- archivo
def cargar() -> pd.DataFrame:
    if not RUTA.exists():
        return pd.DataFrame(columns=COLS)
    d = pd.read_csv(RUTA, dtype=str, keep_default_na=False)
    for c in COLS:
        if c not in d:
            d[c] = ""
    return d[COLS]


def guardar(d: pd.DataFrame) -> None:
    RUTA.parent.mkdir(exist_ok=True)
    d[COLS].to_csv(RUTA, index=False, encoding="utf-8-sig")


def agregar(filas: list[dict]) -> pd.DataFrame:
    d = cargar()
    nid = (pd.to_numeric(d.id, errors="coerce").max() if len(d) else 0)
    nid = 0 if pd.isna(nid) else int(nid)
    nuevas = []
    for f in filas:
        nid += 1
        r = {c: "" for c in COLS}
        r.update({k: ("" if v is None else str(v)) for k, v in f.items() if k in COLS})
        r["id"], r["resultado"] = str(nid), r["resultado"] or "pendiente"
        r["fecha"] = r["fecha"] or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        nuevas.append(r)
    d = pd.concat([d, pd.DataFrame(nuevas)], ignore_index=True)
    guardar(d)
    return d


_BET = re.compile(r"^NFLBET\|")


def desde_portapapeles(texto: str) -> list[dict]:
    """Lineas «NFLBET|game_id|tipo|jugador|player_id|equipo|mercado|linea|lado|cuota|prob_modelo|casa» copiadas desde el reporte."""
    out = []
    for ln in texto.splitlines():
        ln = ln.strip()
        if not _BET.match(ln):
            continue
        p = ln.split("|")[1:]
        if len(p) < 11:
            continue
        gid, tipo, jug, pid, eq, mk, lin, lado, cuota, prob, casa = p[:11]
        m = re.match(r"(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)$", gid)
        rival = ""
        if m:
            a, h = m.group(3), m.group(4)
            rival = h if eq == a else a
        out.append(dict(temporada=m.group(1) if m else "", semana=str(int(m.group(2))) if m else "", game_id=gid, tipo=tipo, jugador=jug,
                        player_id=pid, equipo=eq, rival=rival, mercado=mk, linea=lin, lado=lado, cuota=cuota, prob_modelo=prob, casa=casa))
    return out


# ---------------------------------------------------------------- liquidacion
def _marcador(games: pd.DataFrame) -> dict:
    g = games[games.result.notna()]
    return {r.game_id: r for r in g.itertuples()}


def _estadistica(r, pw: pd.DataFrame, snaps_ok: set, jugo_pw: dict):
    """(valor, jugo). Si no hay fila de estadisticas pero hubo snaps: 0. Sin snaps: no jugo."""
    col = STAT.get(r.mercado)
    if col is None:
        return np.nan, False
    k = (r.player_id, int(float(r.temporada)), int(float(r.semana)))
    if k in jugo_pw:
        return float(jugo_pw[k][col]), True
    if (r.player_id, r.game_id) in snaps_ok:
        return 0.0, True
    return np.nan, False


def liquidar(games: pd.DataFrame, pw: pd.DataFrame, snaps: pd.DataFrame | None = None) -> pd.DataFrame:
    """Marca resultado, estadistica, ganancia y CLV de cada apuesta pendiente cuyo partido ya termino. Devuelve la tabla guardada."""
    global _HK
    _HK = None
    d = cargar()
    if d.empty:
        return d
    G = _marcador(games)
    Gall = {r.game_id: r for r in games.itertuples()}
    pwi = pw.assign(_k=list(zip(pw.player_id, pw.season, pw.week))).drop_duplicates("_k", keep="last").set_index("_k")
    jugo_pw = {k: row for k, row in pwi.iterrows()}
    snaps_ok = set()
    if snaps is not None and len(snaps):
        s = snaps[snaps.offense_snaps > 0]
        snaps_ok = set(zip(s.player_id, s.game_id))
    for i, r in d.iterrows():
        if r.resultado not in ("pendiente", ""):
            if r.clv == "" and r.resultado != "pendiente":
                d.at[i, "clv"] = _clv(r, Gall)
            continue
        g = G.get(r.game_id)
        if g is None:
            continue
        res, stat = None, ""
        linea = _num(r.linea)
        casa = str(r.casa).lower()
        if r.tipo == "prop":
            v, jugo = _estadistica(r, pw, snaps_ok, jugo_pw)
            if not jugo:
                if casa == "kalshi":                      # en Kalshi, si no juega el «Si» pierde
                    v, jugo = 0.0, True
                else:
                    res = "anulada"
            if jugo:
                stat = f"{v:g}"
                lado = r.lado.lower()
                over = lado in ("over", "si")
                if v == linea:
                    res = "empate"
                else:
                    res = "gano" if ((v > linea) == over) else "perdio"
        elif r.tipo == "ml":
            hs, as_ = g.home_score, g.away_score
            if hs == as_:
                res = "empate"
            else:
                gana_local = hs > as_
                res = "gano" if ((r.equipo == g.home_team) == gana_local) else "perdio"
            stat = f"{as_:g}-{hs:g}"
        elif r.tipo == "spread":
            hs, as_ = g.home_score, g.away_score
            mi, su = (hs, as_) if r.equipo == g.home_team else (as_, hs)
            m = mi - su + linea
            res = "empate" if m == 0 else ("gano" if m > 0 else "perdio")
            stat = f"{mi - su:+g}"
        elif r.tipo == "total":
            tot = g.home_score + g.away_score
            if tot == linea:
                res = "empate"
            else:
                res = "gano" if ((tot > linea) == (r.lado.lower() == "over")) else "perdio"
            stat = f"{tot:g}"
        if res:
            d.at[i, "resultado"], d.at[i, "estadistica"] = res, stat
            d.at[i, "ganancia"] = f"{_ganancia(float(r.monto or 0), r.cuota, casa, res):.2f}"
            d.at[i, "clv"] = _clv(r, Gall)
    guardar(d)
    return d


def _clv(r, Gall) -> str:
    """Ventaja sobre el cierre: puntos de probabilidad (props/ML) o puntos de linea (spread/total). Positivo = mejor que el cierre."""
    try:
        p_apuesta, _, _ = parse_cuota(r.cuota, r.casa)
        if r.cierre not in ("", None) and not np.isnan(parse_cuota(r.cierre, r.casa)[0]):
            return f"{(parse_cuota(r.cierre, r.casa)[0] - p_apuesta) * 100:+.1f} pts prob"
        g = Gall.get(r.game_id)
        if g is None:
            return ""
        linea = _num(r.linea)
        if r.tipo == "ml":
            ml = g.home_moneyline if r.equipo == g.home_team else g.away_moneyline
            pc = parse_cuota(f"{ml:+.0f}", "")[0] if pd.notna(ml) else np.nan
            return "" if np.isnan(pc) else f"{(pc - p_apuesta) * 100:+.1f} pts prob"
        if r.tipo == "spread" and pd.notna(g.spread_line):
            cierre = -g.spread_line if r.equipo == g.home_team else g.spread_line
            return f"{linea - cierre:+.1f} pts linea"
        if r.tipo == "total" and pd.notna(g.total_line):
            return f"{(g.total_line - linea) if r.lado.lower() == 'over' else (linea - g.total_line):+.1f} pts linea"
        if r.tipo == "prop":
            c = _cierre_kalshi(r)
            return "" if c is None else f"{(c - p_apuesta) * 100:+.1f} pts prob (vs Kalshi)"
    except Exception:
        pass
    return ""


_HK = None


def _cierre_kalshi(r):
    """Probabilidad de cierre (mitad bid/ask de la ultima vela antes del partido) del mismo jugador, mercado y linea en Kalshi."""
    import kalshi_historial as KH
    from fuentes_web import nombre_norm
    global _HK
    if not KH.RUTA.exists():
        return None
    if _HK is None:
        _HK = KH.cargar()
    H = _HK
    H = H[(H.mercado == r.mercado) & (H.umbral == _num(r.linea)) & (H.jugador.map(nombre_norm) == nombre_norm(r.jugador))]
    if H.empty or not r.fecha:
        return None
    v = H.iloc[0].velas
    pre = [x for x in v if x[1] is not None and x[2] is not None and not (np.isnan(x[1]) or np.isnan(x[2]))]
    if not pre:
        return None
    mid = (pre[-1][1] + pre[-1][2]) / 2
    return mid if r.lado.lower() in ("over", "si") else 1 - mid


# ---------------------------------------------------------------- resumen
def numericas(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    for c in ("monto", "ganancia", "prob_modelo", "linea"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    pi = [parse_cuota(c, k)[0] for c, k in zip(x.cuota, x.casa)]
    x["p_impl"] = pi
    x["gano"] = (x.resultado == "gano").astype(float)
    return x


def resumen(d: pd.DataFrame, n_boot: int = 2000) -> dict:
    x = numericas(d)
    liq = x[x.resultado.isin(["gano", "perdio"])].copy()
    out = {"total": len(x), "pendientes": int((x.resultado == "pendiente").sum()), "anuladas": int(x.resultado.isin(["anulada", "empate"]).sum()),
           "liquidadas": len(liq)}
    if liq.empty:
        return out
    monto, gan = liq.monto.fillna(0).to_numpy(), liq.ganancia.fillna(0).to_numpy()
    out.update(monto=float(monto.sum()), ganancia=float(gan.sum()), roi=float(gan.sum() / monto.sum()) if monto.sum() else np.nan,
               acierto=float(liq.gano.mean()), p_impl=float(liq.p_impl.mean()))
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(liq), (n_boot, len(liq)))
    roi_b = gan[idx].sum(1) / np.maximum(monto[idx].sum(1), 1e-9)
    out["roi_lo90"], out["roi_hi90"] = float(np.percentile(roi_b, 5)), float(np.percentile(roi_b, 95))
    m = liq.dropna(subset=["prob_modelo"])
    if len(m):
        pm = m.prob_modelo.where(m.prob_modelo <= 1, m.prob_modelo / 100)
        out.update(n_prob=len(m), brier_modelo=float(((m.gano - pm) ** 2).mean()), brier_precio=float(((m.gano - m.p_impl) ** 2).mean()),
                   prob_modelo_media=float(pm.mean()), acierto_con_prob=float(m.gano.mean()))
    clv = pd.to_numeric(liq.clv.str.extract(r"([+-]?\d+\.?\d*)")[0], errors="coerce")
    unidad = liq.clv.str.contains("prob", na=False)
    if unidad.any():
        c = clv[unidad].dropna()
        out.update(clv_prob_medio=float(c.mean()), clv_prob_pos=float((c > 0).mean()), clv_n=len(c))
    # por categoria
    def tabla(col):
        t = liq.groupby(col).apply(lambda g: pd.Series({"n": len(g), "monto": g.monto.sum(), "ganancia": g.ganancia.sum(),
                                                         "roi": g.ganancia.sum() / g.monto.sum() if g.monto.sum() else np.nan,
                                                         "acierto": g.gano.mean()})).reset_index()
        return t.to_dict("list")
    out["por_tipo"], out["por_mercado"], out["por_casa"] = tabla("tipo"), tabla("mercado"), tabla("casa")
    return out


def apuestas_para_detectar(roi_objetivo: float = 0.03, sd_unidad: float = 1.0) -> int:
    """Apuestas necesarias para distinguir un ROI verdadero de +3 % del azar (90 % de confianza, apuestas a cuota ~ par)."""
    return int(np.ceil((1.645 * sd_unidad / roi_objetivo) ** 2))
