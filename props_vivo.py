"""Calificación en vivo de props (E8): la proyección que el modelo GUARDÓ antes del kickoff contra lo que pasó.

Reglas para que no haya trampa:
  * Solo cuenta una captura hecha ANTES del kickoff (gameday + gametime, hora del Este → UTC). Si la captura
    es posterior, se descarta (no es una predicción).
  * De varias capturas previas al kickoff se toma la ÚLTIMA (la que vio el público antes del partido).
  * La línea «normal» es la del propio modelo (promedio reciente), NO la de una casa de apuestas; por eso aquí se mide
    acierto de lado (Más de / Menos de) y precisión, no ganancias reales.
  * Empates exactos con la línea (push) no cuentan para el acierto.
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd

import db

NOMBRE = {"pass_yds": "Yardas por pase", "pass_cmp": "Pases completos", "pass_td": "TD de pase", "pass_int": "Intercepciones",
          "rush_yds": "Yardas por tierra", "rush_att": "Acarreos", "rec_yds": "Yardas por recepción", "rec": "Recepciones",
          "tgt": "Targets", "td": "Anotar touchdown"}
ORDEN = ["pass_yds", "pass_cmp", "pass_td", "pass_int", "rush_yds", "rush_att", "rec_yds", "rec", "tgt", "td"]
_REAL = {"pass_yds": "w.pass_yds", "pass_cmp": "w.cmp", "pass_td": "w.pass_td", "pass_int": "w.pass_int", "rush_yds": "w.rush_yds",
         "rush_att": "w.car", "rec_yds": "w.rec_yds", "rec": "w.rec", "tgt": "w.tgt", "td": "(w.rush_td + w.rec_td)"}
_CASE = "CASE p.market " + " ".join(f"WHEN '{m}' THEN {c}" for m, c in _REAL.items()) + " END"


def cargar() -> pd.DataFrame:
    """Capturas previas al kickoff, ya con el resultado real. Devuelve vacío si aún no hay nada calificable."""
    if not db.hay("props_proyecciones"):
        return pd.DataFrame()
    t = db.consulta(f"""
        SELECT p.capturado, p.season, p.week, p.game_id, p.player_id, p.name, p.team, p.market,
               p.base, p.mu, p.line_n, p.p_td, {_CASE} AS real, g.gameday, g.gametime
        FROM props_proyecciones p
        JOIN games g ON g.game_id = p.game_id
        JOIN player_weeks w ON w.player_id = p.player_id AND w.season = p.season AND w.week = p.week""")
    if t.empty:
        return t
    hora = t.gametime.fillna("13:00")
    ko = pd.to_datetime(t.gameday + " " + hora, errors="coerce") + pd.Timedelta(hours=5)   # ET (noviembre-enero) → UTC
    t = t.assign(kickoff_utc=ko, cap=pd.to_datetime(t.capturado, errors="coerce"))
    t = t[t.cap.notna() & t.kickoff_utc.notna() & (t.cap < t.kickoff_utc) & t.real.notna()]
    return t.sort_values("cap").drop_duplicates(["season", "week", "player_id", "market"], keep="last").reset_index(drop=True)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def resumen(t: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for m in ORDEN:
        x = t[t.market == m]
        if x.empty:
            continue
        if m == "td":
            y = (x.real > 0).astype(float).to_numpy()
            p = x.p_td.astype(float).clip(0.01, 0.99).to_numpy()
            filas.append(dict(mercado=m, n=len(x), tasa_real=y.mean(), prob_media=p.mean(),
                              brier=float(np.mean((p - y) ** 2))))
            continue
        d = x[x.real != x.line_n]
        lado_mas = (d.mu > d.line_n).to_numpy()
        gano = np.where(lado_mas, d.real > d.line_n, d.real < d.line_n)
        k = int(gano.sum())
        lo, hi = wilson(k, len(d))
        filas.append(dict(mercado=m, n=len(x), n_lado=len(d), aciertos=k, acierto=k / len(d) if len(d) else np.nan, lo=lo, hi=hi,
                          mae_mod=float((x.mu - x.real).abs().mean()), mae_base=float((x.base - x.real).abs().mean())))
    return pd.DataFrame(filas)


def html_bloque() -> str:
    t = cargar()
    tit = '<h2 id="props-vivo">Calificación en vivo de props (proyecciones guardadas antes del partido)</h2>'
    if t.empty:
        return (tit + '<p class="explain keep">Todavía no hay proyecciones guardadas antes del kickoff con resultado final. '
                'Esta tabla se llena sola: cada corrida del reporte guarda la proyección de cada jugador y, cuando termina el partido, se califica.</p>')
    r = resumen(t)
    juegos = t.game_id.nunique()
    filas = []
    for x in r.itertuples():
        nom = NOMBRE[x.mercado]
        if x.mercado == "td":
            filas.append(f'<tr><td>{nom}</td><td class="num">{x.n}</td><td>anotó {x.tasa_real * 100:.0f}% (modelo decía {x.prob_media * 100:.0f}%)</td>'
                         f'<td>Brier {x.brier:.3f}</td><td>—</td></tr>')
        else:
            filas.append(f'<tr><td>{nom}</td><td class="num">{x.n}</td>'
                         f'<td>{int(x.aciertos)}/{int(x.n_lado)} = {x.acierto * 100:.0f}% <small>(IC95 {x.lo * 100:.0f}–{x.hi * 100:.0f}%)</small></td>'
                         f'<td>error {x.mae_mod:.2f}</td><td>error {x.mae_base:.2f}</td></tr>')
    z = r[r.mercado != "td"]
    if len(z):
        K, N = int(z.aciertos.sum()), int(z.n_lado.sum())
        lo, hi = wilson(K, N)
        filas.append(f'<tr><td><b>Todos (sin TD)</b></td><td class="num"><b>{int(z.n.sum())}</b></td>'
                     f'<td><b>{K}/{N} = {K / N * 100:.0f}%</b> <small>(IC95 {lo * 100:.0f}–{hi * 100:.0f}%)</small></td><td></td><td></td></tr>')
    return (tit +
            f'<p class="explain keep">Solo cuentan proyecciones guardadas <b>antes del kickoff</b> (las capturas posteriores se descartan). '
            f'Muestra actual: {len(t)} proyecciones de {juegos} partido(s). Es una muestra <b>muy chica</b>: ningún porcentaje de aquí es una conclusión, '
            f'el intervalo (IC95) lo muestra. «Acierto» = el jugador quedó del lado que el modelo recomendó (Más de / Menos de) frente a la línea normal '
            f'(la del propio modelo, no la de una casa), sin contar empates exactos.</p>'
            '<div class="scroll"><table><tr><th>Mercado</th><th>Proyecciones</th><th>Acierto Más de / Menos de</th><th>Error del modelo</th>'
            '<th>Error del promedio reciente</th></tr>' + "".join(filas) + '</table></div>')
