"""Probabilidad de que un jugador «Questionable» juegue, y cuanto rinde si juega.

Se midio con el historial de lesiones de nflverse (2016-2025, solo jugadores habituales: 4+ apariciones en los ultimos 6 juegos
de su equipo). Hallazgos:
  * La practica de la semana predice mucho: Questionable que no practico juega ~42 %, con practica limitada ~69 %, completa ~86 %.
  * Si juega, rinde un poco menos (receptores/corredores -4 a -8 %); el QB no cambia.
  * Validado fuera de muestra (entrenando con temporadas anteriores, 2019-2025): error Brier de «juega seguro» 0.345,
    tasa unica 0.227, practica + posicion 0.212.
`ajustar(d, flag)` anade p_juega y baja la proyeccion de los Questionable que juegan; `evaluar()` repite la validacion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Regresion logistica ajustada con 2016-2025 (Questionable, jugadores habituales). QB = posicion base.
INTERCEPTO = 0.19465
COEF = {"p_Full": 1.10, "p_Limited": 0.07, "p_DNP": -1.09, "pos_RB": 0.40, "pos_WR": 0.75, "pos_TE": 0.43}
PESO_PRACTICA = {"Full": 0.17, "Limited": 0.66, "DNP": 0.17}      # para cuando no hay dato de practica
P_DOUBTFUL = 0.02
# Cuanto rinde un Questionable que juega frente a un sano (cociente medido; QB ~1)
FACTOR_SI_JUEGA = {"pass_yds": 1.0, "pass_cmp": 1.0, "pass_td": 1.0, "pass_int": 1.0, "rush_yds": 0.93, "rush_att": 0.95,
                   "rec_yds": 0.94, "rec": 0.96, "td": 0.96}
PRACT = {"Full Participation in Practice": "Full", "Limited Participation in Practice": "Limited", "Did Not Participate In Practice": "DNP"}


def _p(practica: str, pos: str) -> float:
    z = INTERCEPTO + COEF.get("p_" + practica, 0.0) + COEF.get("pos_" + pos, 0.0)
    return float(1 / (1 + np.exp(-z)))


def p_juega(estado: str, practica: str, pos: str) -> float:
    """P(el jugador aparece en el partido) segun el reporte oficial. Sano o sin reporte = 1; Out = 0."""
    if estado == "Out":
        return 0.0
    if estado == "Doubtful":
        return P_DOUBTFUL
    if estado != "Questionable":
        return 1.0
    pr = PRACT.get(practica, practica)
    if pr in PESO_PRACTICA:
        return _p(pr, pos)
    return float(sum(w * _p(k, pos) for k, w in PESO_PRACTICA.items()))


def ajustar(d: pd.DataFrame, market: str) -> pd.DataFrame:
    """`d` debe traer estado, practica y position. Anade p_juega y reduce mu/mu_n de los Questionable (proyeccion «si juega»)."""
    d = d.copy()
    d["p_juega"] = [p_juega(e, p, pos) for e, p, pos in zip(d.estado, d.practica, d.position)]
    f = np.where(d.estado == "Questionable", FACTOR_SI_JUEGA.get(market, 1.0), 1.0)
    d["mu"] = np.clip(d.mu * f, 1e-3, None)
    if "mu_n" in d:
        d["mu_n"] = np.clip(d.mu_n * f, 1e-3, None)
    return d


# ---------------------------------------------------------------- validacion (necesita internet la primera vez)
def construir_historial(desde: int = 2016, hasta: int | None = None) -> pd.DataFrame:
    """Un renglon por jugador habitual con reporte de lesion: estado, practica, si aparecio y sus numeros reales vs su promedio previo."""
    import data as D
    import jugadores_data as J
    games = D.load_schedules(False)
    hasta = hasta or int(games[games.result.notna()].season.max())
    inj = pd.concat([J.load_injuries(s, False) for s in range(desde, hasta + 1)])
    pw = J.load_player_weeks(range(J.FIRST_PLAYER_SEASON, hasta + 1), refresh_seasons=())
    pw = pw[pw.season_type == "REG"].copy()
    tg = pw[["team", "season", "week"]].drop_duplicates().sort_values(["team", "season", "week"]).reset_index(drop=True)
    tg["g"] = tg.groupby("team").cumcount()
    pw = pw.merge(tg, on=["team", "season", "week"]).sort_values(["player_id", "g"])
    pw["key"] = pw.player_id + "|" + pw.team
    stats = ["pass_yds", "att", "car", "rush_yds", "tgt", "rec", "rec_yds", "td", "cmp"]
    pset = set(zip(pw.key, pw.g))
    inj = inj[inj.position.isin(["QB", "RB", "WR", "TE"])].copy()
    inj["practica"] = inj.practice_status.map(PRACT).fillna("sin dato")
    inj["estado"] = inj.report_status.fillna("sin estado")
    inj = inj.merge(tg, on=["team", "season", "week"])
    inj["key"] = inj.gsis_id + "|" + inj.team
    inj["prev"] = [sum((k, g - j) in pset for j in range(1, 7)) for k, g in zip(inj.key, inj.g)]
    inj = inj[inj.prev >= 4]
    gr = {k: v for k, v in pw.groupby("key")}
    rows = []
    for r in inj.itertuples():
        sub = gr[r.key]
        b = sub[sub.g < r.g].tail(6)[stats].mean()
        cur = sub[sub.g == r.g]
        rows.append([int(len(cur) > 0)] + [b[s] for s in stats] + [cur[s].iloc[0] if len(cur) else np.nan for s in stats])
    cols = ["aparece"] + ["b_" + s for s in stats] + ["y_" + s for s in stats]
    return pd.concat([inj.reset_index(drop=True), pd.DataFrame(rows, columns=cols)], axis=1)


def evaluar(h: pd.DataFrame | None = None) -> pd.DataFrame:
    """Brier fuera de muestra (entrena con temporadas anteriores) de: juega seguro / tasa unica / practica + posicion."""
    from sklearn.linear_model import LogisticRegression
    h = construir_historial() if h is None else h
    q = h[h.estado == "Questionable"]

    def X(t):
        o = pd.DataFrame(index=t.index)
        for p in ("Full", "Limited", "DNP"):
            o["p_" + p] = (t.practica == p).astype(float)
        for p in ("RB", "WR", "TE"):
            o["pos_" + p] = (t.position == p).astype(float)
        return o
    out = []
    for s in range(int(q.season.min()) + 3, int(q.season.max()) + 1):
        tr, te = q[q.season < s], q[q.season == s]
        pm = LogisticRegression(C=1.0, max_iter=500).fit(X(tr), tr.aparece).predict_proba(X(te))[:, 1]
        y = te.aparece.to_numpy()
        out.append({"temporada": s, "n": len(te), "siempre_juega": ((y - 1) ** 2).mean(),
                    "tasa_unica": ((y - tr.aparece.mean()) ** 2).mean(), "practica_y_posicion": ((y - pm) ** 2).mean()})
    return pd.DataFrame(out)


if __name__ == "__main__":
    print(evaluar().round(4).to_string(index=False))
