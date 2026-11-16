"""¿Le gana el modelo al MERCADO? Compara, partido por partido, la probabilidad del modelo con el precio de Kalshi justo antes
del partido (usando solo informacion previa: el modelo de cada temporada se entrena con temporadas anteriores).

Mide: Brier y log-loss (modelo, mercado, mezclas), calibracion del mercado, ROI simulado de apostar donde el modelo ve ventaja,
y cuanto pesa cada uno (regresion logistica del resultado sobre ambos) para saber con que peso mezclarlos.
Datos: data/kalshi_hist.db (lo baja bajar_historial_kalshi.py).
"""
from __future__ import annotations

import datetime as dt
import pickle
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import nbinom

import kalshi_historial as KH
import props as P
from data import DATA
from fuentes_web import nombre_norm

CAL_SEASONS = (2021, 2022, 2023, 2024)       # para elegir encogimiento, dispersion y recalibracion de TD
EVAL_SEASONS = (2025, 2026)                  # temporadas con precios de Kalshi
COMISION = 0.07
ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------- predicciones fuera de muestra
def predicciones_oos(X: pd.DataFrame, log=print, todas: bool = False) -> pd.DataFrame:
    """mu por jugador-partido-mercado de las temporadas CAL y EVAL, cada una con modelos entrenados solo con temporadas previas."""
    salida = []
    for m, spec in P.MARKETS.items():
        d = P._rows(X, spec)
        d = d[d.played == 1]
        y_, e_ = spec["y"], "e_" + spec["y"]
        partes = []
        for s in CAL_SEASONS + EVAL_SEASONS:
            tr, te = d[d.season < s], d[d.season == s]
            if te.empty:
                continue
            mu = P.make_model().fit(tr[P.FEATS], tr[y_].clip(lower=0)).predict(te[P.FEATS])
            partes.append(pd.DataFrame({"player_id": te.player_id.values, "season": s, "week": te.week.values, "team": te.team.values,
                                        "y": te[y_].clip(lower=0).values, "mu_raw": mu, "base": te[e_].values}))
        o = pd.concat(partes, ignore_index=True)
        cal = o[o.season.isin(CAL_SEASONS)]
        mejor = None
        for lam in (0.4, 0.6, 0.8, 1.0):
            mu_l = np.clip(cal.base + lam * (cal.mu_raw - cal.base), 1e-3, None)
            ph = P.estimar_phi(cal.y, mu_l)
            n_, p_ = P.nb_pn(mu_l, ph)
            ll = float(nbinom.logpmf(np.round(cal.y), n_, p_).mean())
            if mejor is None or ll > mejor[0]:
                mejor = (ll, lam, ph)
        _, lam, phi = mejor
        o["mu"] = np.clip(o.base + lam * (o.mu_raw - o.base), 1e-3, None)
        o["phi"], o["mercado"] = phi, m
        if m == "td":
            from sklearn.linear_model import LogisticRegression
            c = o[o.season.isin(CAL_SEASONS)]
            p = np.clip(P.p_over(c.mu, phi, 0.5), 1e-4, 1 - 1e-4)
            lr = LogisticRegression(C=1e6, max_iter=500).fit(P._logit(p).reshape(-1, 1), (c.y >= 1).astype(float))
            platt = (float(lr.intercept_[0]), float(lr.coef_[0][0]))
            o["p_td"] = P.calibrar_td(P.p_over(o.mu, phi, 0.5), platt)
        else:
            o["p_td"] = np.nan
        salida.append(o if todas else o[o.season.isin(EVAL_SEASONS)])
        log(f"  {spec['label']}: encogimiento {lam}, dispersion {phi:.3f}")
    return pd.concat(salida, ignore_index=True)


def predicciones_oos_cache(X, log=print, refrescar=False) -> pd.DataFrame:
    ruta = DATA / "mercado_oos_v2.pkl"
    import time
    if ruta.exists() and not refrescar and time.time() - ruta.stat().st_mtime < 3 * 86400:     # se recalcula cada 3 dias (llegan semanas nuevas)
        return pickle.loads(ruta.read_bytes())
    o = predicciones_oos(X, log)
    ruta.write_bytes(pickle.dumps(o))
    return o


# ---------------------------------------------------------------- precios de Kalshi antes del partido
def _inicio_utc(gameday: str, gametime: str) -> int:
    h, mi = (int(x) for x in str(gametime).split(":")[:2])
    d = dt.datetime.fromisoformat(gameday).replace(hour=h, minute=mi, tzinfo=ET)
    return int(d.timestamp())


def precios_previos(H: pd.DataFrame, games: pd.DataFrame, pw: pd.DataFrame) -> pd.DataFrame:
    """Cada escalon de Kalshi con: temporada/semana, jugador (id), precio de cierre (ultima vela antes del partido) y 24 h antes."""
    g = games[["game_id", "season", "week", "gameday", "gametime", "home_team", "away_team"]].copy()
    g["gameday"] = g.gameday.astype(str)
    lj = pd.concat([g.assign(team=g.home_team, opp=g.away_team), g.assign(team=g.away_team, opp=g.home_team)])
    lj = lj[["game_id", "season", "week", "gameday", "gametime", "team", "opp"]].rename(columns={"gameday": "fecha_juego"})
    H = H.merge(lj, left_on=["fecha_juego", "equipo"], right_on=["fecha_juego", "team"], how="inner")
    q = pw.assign(nn=pw.name.map(nombre_norm))[["season", "week", "team", "nn", "player_id"]].drop_duplicates(["season", "week", "team", "nn"])
    H["nn"] = H.jugador.map(nombre_norm)
    H = H.merge(q, on=["season", "week", "team", "nn"], how="inner")          # solo jugadores que SI jugaron
    filas = []
    for r in H.itertuples():
        ko = _inicio_utc(r.fecha_juego, r.gametime)
        v = [x for x in r.velas if x[0] <= ko and x[1] == x[1] and x[2] == x[2] and x[2] >= x[1]]
        if not v:
            continue
        c = v[-1]
        t24 = [x for x in v if x[0] <= ko - 24 * 3600]
        e = t24[-1] if t24 else None
        filas.append({"ticker": r.ticker, "game_id": r.game_id, "season": r.season, "week": r.week, "player_id": r.player_id,
                      "equipo": r.team, "rival": r.opp, "jugador": r.jugador, "mercado": r.mercado, "umbral": r.umbral, "linea": r.linea,
                      "resultado": r.resultado, "volumen": r.volumen, "bid": c[1], "ask": c[2], "mid": (c[1] + c[2]) / 2,
                      "spread": c[2] - c[1], "hora_cierre": (ko - c[0]) / 3600,
                      "bid24": e[1] if e else np.nan, "ask24": e[2] if e else np.nan})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- comparacion
def probabilidad_modelo(K: pd.DataFrame, O: pd.DataFrame) -> pd.DataFrame:
    d = K.merge(O[["player_id", "season", "week", "mercado", "mu", "phi", "p_td"]], on=["player_id", "season", "week", "mercado"], how="inner")
    n = 1 / d.phi.values
    p = n / (n + d.mu.values)
    pm = 1 - nbinom.cdf(np.floor(d.linea.values), n, p)
    d["p_modelo"] = np.where(d.mercado == "td", np.where(d.linea == 0.5, d.p_td, np.nan), pm)
    return d.dropna(subset=["p_modelo"])


def _ll(y, p):
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _brier(y, p):
    return float(((y - p) ** 2).mean())


def _apuestas(d: pd.DataFrame, umbral: float, tope_disc: float | None = None) -> pd.DataFrame:
    """Apuesta 1 contrato donde el modelo ve ventaja neta >= umbral (despues de comision). Devuelve costo y ganancia por apuesta."""
    fee = lambda p: COMISION * p * (1 - p)
    ev_si = d.p_modelo - d.ask - fee(d.ask)
    ev_no = d.bid - d.p_modelo - fee(d.bid)
    lado = np.where((ev_si >= umbral) & (ev_si >= ev_no), "si", np.where(ev_no >= umbral, "no", ""))
    x = d.assign(lado=lado)
    x = x[x.lado != ""].copy()
    if tope_disc is not None:
        x = x[(x.p_modelo - x.mid).abs() < tope_disc]
    costo = np.where(x.lado == "si", x.ask, 1 - x.bid)
    gana = np.where(x.lado == "si", x.resultado, 1 - x.resultado)
    x["costo"] = costo + fee(costo)
    x["neto"] = gana - x.costo
    return x


def _roi(x: pd.DataFrame, rng, n_boot=400):
    if x.empty:
        return None
    roi = x.neto.sum() / x.costo.sum()
    juegos = x.game_id.unique()
    por = x.groupby("game_id").agg(n=("neto", "sum"), c=("costo", "sum"))
    bs = []
    for _ in range(n_boot):
        s = por.loc[rng.choice(juegos, len(juegos))]
        bs.append(s.n.sum() / s.c.sum())
    lo, hi = np.percentile(bs, [5, 95])
    return {"n": int(len(x)), "roi": float(roi), "lo90": float(lo), "hi90": float(hi), "gan_prom": float(x.neto.mean())}


def _dif_brier(d: pd.DataFrame, rng, n_boot=500):
    """Brier(modelo) - Brier(mercado) por partido y su intervalo al 90 % (remuestreando partidos). Negativo = el modelo es mejor."""
    x = d.assign(dm=(d.resultado - d.p_modelo) ** 2, dk=(d.resultado - d.mid) ** 2).groupby("game_id").agg(dm=("dm", "sum"), dk=("dk", "sum"), n=("dm", "size"))
    if len(x) < 8:
        return None
    ids = x.index.to_numpy()
    base = (x.dm.sum() - x.dk.sum()) / x.n.sum()
    bs = []
    for _ in range(n_boot):
        z = x.loc[rng.choice(ids, len(ids))]
        bs.append((z.dm.sum() - z.dk.sum()) / z.n.sum())
    lo, hi = np.percentile(bs, [5, 95])
    return {"dif": float(base), "lo90": float(lo), "hi90": float(hi), "partidos": int(len(ids))}


def evaluar(D: pd.DataFrame, max_spread: float = 0.10, log=print) -> dict:
    """D = salida de probabilidad_modelo. Devuelve metricas por mercado y globales."""
    from sklearn.linear_model import LogisticRegression
    d = D[(D.spread <= max_spread) & (D.mid > 0.02) & (D.mid < 0.98)].copy()
    d["y"] = d.resultado
    rng = np.random.default_rng(0)
    res = {"n": int(len(d)), "juegos": int(d.game_id.nunique()), "semanas": int(d.groupby(["season", "week"]).ngroups), "por_mercado": {}}
    y = d.y.to_numpy()
    g = {"mercado": {"brier": _brier(y, d.mid), "ll": _ll(y, d.mid)}, "modelo": {"brier": _brier(y, d.p_modelo), "ll": _ll(y, d.p_modelo)}}
    for w in (0.15, 0.2, 0.25, 0.5, 0.75):
        mix = w * d.p_modelo + (1 - w) * d.mid
        g[f"mezcla_{int(w * 100)}"] = {"brier": _brier(y, mix), "ll": _ll(y, mix)}
    res["global"] = g
    res["dif_brier"] = _dif_brier(d, rng)
    res["dif_brier_mezcla25"] = _dif_brier(d.assign(p_modelo=0.25 * d.p_modelo + 0.75 * d.mid), rng)
    res["dif_brier_mezcla15"] = _dif_brier(d.assign(p_modelo=0.15 * d.p_modelo + 0.85 * d.mid), rng)
    res["dif_brier_mezcla20"] = _dif_brier(d.assign(p_modelo=0.20 * d.p_modelo + 0.80 * d.mid), rng)
    lg = lambda p: np.log(np.clip(p, 1e-3, 1 - 1e-3) / (1 - np.clip(p, 1e-3, 1 - 1e-3)))
    Z = np.c_[lg(d.mid), lg(d.p_modelo)]
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(Z, y)
    res["pesos_logit"] = {"mercado": float(lr.coef_[0][0]), "modelo": float(lr.coef_[0][1]), "intercepto": float(lr.intercept_[0])}
    # por mercado
    for m, s in d.groupby("mercado"):
        yy = s.y.to_numpy()
        if len(s) < 60:
            continue
        res["por_mercado"][m] = {"n": int(len(s)), "tasa": float(yy.mean()),
                                  "brier_mercado": _brier(yy, s.mid), "brier_modelo": _brier(yy, s.p_modelo),
                                  "brier_mezcla50": _brier(yy, 0.5 * s.p_modelo + 0.5 * s.mid),
                                  "ll_mercado": _ll(yy, s.mid), "ll_modelo": _ll(yy, s.p_modelo), "dif_brier": _dif_brier(s, rng)}
    res["por_semana"] = [{"season": int(a), "week": int(b), "n": int(len(z)), "brier_mercado": _brier(z.y.to_numpy(), z.mid),
                          "brier_modelo": _brier(z.y.to_numpy(), z.p_modelo)} for (a, b), z in d.groupby(["season", "week"])]
    # ¿hay sesgo en el precio? ROI de comprar siempre «Si» (al ask) o siempre «No» (a 1 - bid) por tramo de precio
    fee = lambda p: COMISION * p * (1 - p)
    tr = pd.cut(d.mid, [0, .15, .3, .45, .55, .7, .85, 1.0], include_lowest=True)
    filas = []
    for t, z in d.groupby(tr, observed=True):
        c_si, c_no = z.ask + fee(z.ask), (1 - z.bid) + fee(1 - z.bid)
        filas.append({"tramo": str(t), "n": int(len(z)), "precio": float(z.mid.mean()), "real": float(z.y.mean()),
                      "roi_si": float((z.y - c_si).sum() / c_si.sum()), "roi_no": float(((1 - z.y) - c_no).sum() / c_no.sum())})
    res["por_precio"] = filas
    # calibracion del mercado y del modelo
    cortes = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0]
    for nombre, col in (("mercado", "mid"), ("modelo", "p_modelo")):
        b = pd.cut(d[col], cortes, include_lowest=True)
        t = d.groupby(b, observed=True).agg(n=("y", "size"), pred=(col, "mean"), real=("y", "mean")).reset_index(drop=True)
        res[f"calibracion_{nombre}"] = t.round(3).to_dict("list")
    # apuestas simuladas
    res["apuestas"] = {}
    for u in (0.03, 0.05, 0.08, 0.12):
        res["apuestas"][f"todas_{int(u * 100)}"] = _roi(_apuestas(d, u), rng)
        res["apuestas"][f"filtro10_{int(u * 100)}"] = _roi(_apuestas(d, u, 0.10), rng)
    # CLV: precio de compra 24 h antes vs. cierre
    e = d.dropna(subset=["ask24", "bid24"])
    clv = []
    for u in (0.03, 0.05):
        x = _apuestas(e.assign(ask=e.ask24, bid=e.bid24), u)
        if len(x):
            cierre = np.where(x.lado == "si", x.mid, 1 - x.mid)
            compra = np.where(x.lado == "si", x.ask, 1 - x.bid)
            clv.append({"umbral": u, "n": int(len(x)), "clv_medio": float((cierre - compra).mean())})
    res["clv"] = clv
    res["d"] = d
    return res
