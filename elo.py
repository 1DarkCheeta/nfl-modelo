"""ELO mejorado para la NFL (equipo + quarterback, con incertidumbre y ancla opcional al mercado).

Que arregla respecto al Elo clasico (que solo tiene un numero por equipo):

  1. QUARTERBACK: la fuerza de un partido = Elo del EQUIPO + Elo del QB que juega. Si cambia el
     titular (o se lesiona el QB), la prediccion cambia ese mismo dia. El QB se lleva su Elo si
     cambia de equipo.
  2. INCERTIDUMBRE: un QB nuevo (pocos partidos) o un equipo al inicio de temporada se mueve mas por
     cada resultado; con muchos partidos el rating se estabiliza (idea parecida a Glicko).
  3. SORPRESA (lo que pidio el usuario): cambio = K * (resultado - esperado)
         favorito pierde -> baja MUCHO | favorito gana -> sube POCO | no favorito gana -> sube MAS
  4. MARGEN: ganar por mas puntos pesa mas, con rendimientos decrecientes y corregido para que el
     favorito que gana por paliza no infle su Elo.
  5. DESCANSO / LOCALIA / CAMPO NEUTRAL entran en la probabilidad esperada.
  6. ANCLA AL MERCADO (opcional, w_mercado): la "sorpresa" se mide contra una mezcla de la
     probabilidad del Elo y la de las casas (moneyline o spread). Con 0 el Elo es 100% independiente.
  7. REGRESION entre temporadas: el equipo y el QB se acercan al promedio (hay cambios de plantilla).

Todo se guarda ANTES del partido -> sin fuga de informacion; sirve para el backtest walk-forward.
Elo ~ 25 puntos de Elo equivalen a ~1 punto de spread.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.stats import norm

ELO_INI = 1500.0
PTS_POR_PUNTO = 25.0      # 25 puntos de Elo ~ 1 punto en el spread
PARAMS = {
    "k_eq": 10.0,         # velocidad del Elo del equipo (afinado en backtest 2003-2012)
    "k_qb": 6.0,          # velocidad del Elo del QB
    "boost_eq": 0.0,      # extra de velocidad al inicio de temporada (equipo): no ayudo en el backtest
    "boost_qb": 2.0,      # extra de velocidad para QB con pocos partidos
    "tau_eq": 4.0,        # partidos para que el extra del equipo se reduzca a la mitad
    "tau_qb": 8.0,        # partidos del QB para reducir a la mitad su extra
    "hfa": 48.0,          # ventaja de local (Elo)
    "descanso": 2.0,      # Elo por dia de descanso extra (limitado a +-7)
    "reg_eq": 0.40,       # regresion a 1500 entre temporadas
    "reg_qb": 0.10,       # regresion del QB a 0 entre temporadas
    "mov": True,
    "w_mercado": 0.0,     # 0 = Elo independiente; 1 = la sorpresa se mide solo contra el mercado
    "usar_qb": True,
    "desde": None,        # temporada desde la que se calcula el Elo (None = todo el historial)
}


def _p_mercado(r) -> float:
    ml_h, ml_a = r.home_moneyline, r.away_moneyline
    if pd.notna(ml_h) and pd.notna(ml_a):
        f = lambda o: -o / (-o + 100) if o < 0 else 100 / (o + 100)
        ph, pa = f(ml_h), f(ml_a)
        return ph / (ph + pa)
    if pd.notna(r.spread_line):                       # spread_line = margen esperado del local
        return float(norm.cdf(r.spread_line / 13.5))
    return np.nan


def _mult_margen(margen: float, dif_ganador: float) -> float:
    return np.log(abs(margen) + 1.0) * 2.2 / (dif_ganador * 0.001 + 2.2)


def elo_historial(games: pd.DataFrame, **kw) -> pd.DataFrame:
    """Una fila por partido con el Elo previo de cada lado, su probabilidad y el cambio posterior."""
    p = {**PARAMS, **kw}
    games = games.sort_values(["gameday", "game_id"])
    if p.get("desde"):                               # empezar a contar desde esa temporada (todos en 1500)
        games = games[games.season >= p["desde"]]
    T = defaultdict(lambda: ELO_INI)        # Elo del equipo
    Q = defaultdict(float)                  # Elo (extra) del QB, 0 = QB promedio
    n_qb = defaultdict(int)                 # partidos jugados por el QB
    n_eq = defaultdict(int)                 # partidos del equipo en la temporada
    ultimo_qb: dict[str, str] = {}
    rows, last_season = [], None
    for r in games.itertuples(index=False):
        if r.season != last_season:
            if last_season is not None:
                for t in list(T):
                    T[t] = ELO_INI + (1 - p["reg_eq"]) * (T[t] - ELO_INI)
                for q in list(Q):
                    Q[q] *= (1 - p["reg_qb"])
                for t in list(n_eq):
                    n_eq[t] = 0
            last_season = r.season
        h, a = r.home_team, r.away_team
        qh = r.home_qb_id if pd.notna(r.home_qb_id) else ultimo_qb.get(h)
        qa = r.away_qb_id if pd.notna(r.away_qb_id) else ultimo_qb.get(a)
        q_h = Q[qh] if (p["usar_qb"] and qh) else 0.0
        q_a = Q[qa] if (p["usar_qb"] and qa) else 0.0
        eh, ea = T[h] + q_h, T[a] + q_a
        neutral = getattr(r, "location", "") == "Neutral"
        rest = float(np.clip((r.home_rest if pd.notna(r.home_rest) else 7) -
                             (r.away_rest if pd.notna(r.away_rest) else 7), -7, 7))
        dif = eh - ea + (0.0 if neutral else p["hfa"]) + p["descanso"] * rest
        p_elo = 1.0 / (1.0 + 10 ** (-dif / 400.0))
        p_mkt = _p_mercado(r)
        esperado = p_elo if (pd.isna(p_mkt) or p["w_mercado"] <= 0) else \
            p["w_mercado"] * p_mkt + (1 - p["w_mercado"]) * p_elo
        row = {"game_id": r.game_id, "elo_h": eh, "elo_a": ea, "elo_diff": dif, "p_elo": p_elo,
               "p_mkt": p_mkt, "p_esperada": esperado, "qb_h": qh, "qb_a": qa,
               "elo_eq_h": T[h], "elo_eq_a": T[a], "elo_qb_h": q_h, "elo_qb_a": q_a,
               "d_h": np.nan, "d_a": np.nan, "dq_h": 0.0, "dq_a": 0.0}
        if pd.notna(r.home_score) and pd.notna(r.away_score):
            res = r.home_score - r.away_score
            s = 1.0 if res > 0 else (0.5 if res == 0 else 0.0)
            m = _mult_margen(res, dif if res > 0 else -dif) if (p["mov"] and res != 0) else 1.0
            err = m * (s - esperado)
            bt_h = 1 + p["boost_eq"] * 0.5 ** (n_eq[h] / p["tau_eq"])
            bt_a = 1 + p["boost_eq"] * 0.5 ** (n_eq[a] / p["tau_eq"])
            dt_h, dt_a = p["k_eq"] * bt_h * err, -p["k_eq"] * bt_a * err
            T[h] += dt_h
            T[a] += dt_a
            if p["usar_qb"]:
                if qh:
                    row["dq_h"] = p["k_qb"] * (1 + p["boost_qb"] * 0.5 ** (n_qb[qh] / p["tau_qb"])) * err
                    Q[qh] += row["dq_h"]
                if qa:
                    row["dq_a"] = -p["k_qb"] * (1 + p["boost_qb"] * 0.5 ** (n_qb[qa] / p["tau_qb"])) * err
                    Q[qa] += row["dq_a"]
                if qh: n_qb[qh] += 1
                if qa: n_qb[qa] += 1
            n_eq[h] += 1
            n_eq[a] += 1
            row["d_h"], row["d_a"] = dt_h, dt_a
            if qh: ultimo_qb[h] = qh
            if qa: ultimo_qb[a] = qa
        else:                                        # pendiente: recordar el QB anunciado
            if qh: ultimo_qb.setdefault(h, qh)
            if qa: ultimo_qb.setdefault(a, qa)
        rows.append(row)
    return pd.DataFrame(rows)


def margen_elo(elo_diff) -> np.ndarray:
    """Margen esperado del local en puntos, a partir de la diferencia de Elo."""
    return np.asarray(elo_diff, float) / PTS_POR_PUNTO


# --------------------------------------------------------------------------- para el reporte
# Parametros del Elo "desde la temporada pasada" (afinados con backtest: para cada temporada, Elo empezando
# en la anterior). Con poco historial conviene un K de equipo algo mayor.
PARAMS_REC = {"k_eq": 14.0, "k_qb": 6.0, "reg_eq": 0.40}


def calcular(games: pd.DataFrame, cur: int, desde: int | None = None) -> dict:
    """Elo desde la temporada pasada (o `desde`). Devuelve la tabla por equipo y el Elo de cada partido."""
    desde = cur - 1 if desde is None else desde
    h = elo_historial(games, desde=desde, **PARAMS_REC)
    g = games.merge(h, on="game_id").sort_values(["gameday", "game_id"])
    jug = g[g.home_score.notna() & (g.season == cur)]
    filas = []
    for lado, rival, side in (("home_team", "away_team", "h"), ("away_team", "home_team", "a")):
        d = pd.DataFrame({"game_id": jug.game_id, "gameday": jug.gameday, "week": jug.week, "equipo": jug[lado],
                          "rival": jug[rival], "elo_eq": jug[f"elo_eq_{side}"], "elo_qb": jug[f"elo_qb_{side}"],
                          "dT": jug[f"d_{side}"], "dQ": jug[f"dq_{side}"], "qb": jug[f"qb_{side}"],
                          "p_esp": jug.p_esperada if side == "h" else 1 - jug.p_esperada})
        filas.append(d)
    x = pd.concat(filas).sort_values(["gameday", "game_id"])
    x["cambio"] = x.dT + x.dQ
    x["elo_post"] = x.elo_eq + x.elo_qb + x.cambio
    out = []
    for t, d in x.groupby("equipo"):
        u = d.iloc[-1]
        ini = d.iloc[0]
        out.append({"equipo": t, "elo": u.elo_post, "elo_eq": u.elo_eq + u.dT, "elo_qb": u.elo_qb + u.dQ,
                    "qb": u.qb, "ultimo": u.cambio, "rival": u.rival, "p_esp": u.p_esp,
                    "cambio_4": d.cambio.tail(4).sum(), "cambio_temp": u.elo_post - (ini.elo_eq + ini.elo_qb),
                    "juegos": len(d)})
    tabla = pd.DataFrame(out).sort_values("elo", ascending=False).reset_index(drop=True)
    tabla["rank"] = np.arange(1, len(tabla) + 1)
    # nombres de los QB (ultimo partido jugado)
    nombres = {}
    for r in jug.itertuples():
        nombres[r.home_qb_id] = r.home_qb_name
        nombres[r.away_qb_id] = r.away_qb_name
    tabla["qb_nombre"] = tabla.qb.map(nombres).fillna("")
    pend = g[g.home_score.isna() & (g.season == cur)]
    return {"tabla": tabla, "partidos": pend, "desde": desde, "cur": cur}


CSS = """
.elo td.up{color:#0a7d3c;font-weight:600}.elo td.dn{color:#b3261e;font-weight:600}
.elo td.l,.elo th.l{text-align:left}.elo small{color:#666}
"""


def _fmt(x, d=0, signo=False):
    if pd.isna(x):
        return "n/d"
    return f"{x:+,.{d}f}" if signo else f"{x:,.{d}f}"


def _cls(x):
    return "up" if x > 0.5 else ("dn" if x < -0.5 else "")


def html_elo(E: dict, res: pd.DataFrame, nombre=lambda t: t) -> str:
    """Seccion del reporte: ranking de Elo y Elo de los partidos de la semana."""
    if not E or E["tabla"].empty:
        return ""
    t = E["tabla"]
    filas = []
    for r in t.itertuples():
        sorpresa = ""
        if abs(r.ultimo) >= 25:
            sorpresa = " <small>(sorpresa)</small>"
        filas.append(
            f"<tr><td>{r.rank}</td><td class='l'><b>{nombre(r.equipo)}</b></td><td><b>{_fmt(r.elo)}</b></td>"
            f"<td class='{_cls(r.cambio_temp)}'>{_fmt(r.cambio_temp, 0, True)}</td>"
            f"<td class='{_cls(r.cambio_4)}'>{_fmt(r.cambio_4, 0, True)}</td>"
            f"<td class='{_cls(r.ultimo)}'>{_fmt(r.ultimo, 1, True)}{sorpresa}<br><small>vs {r.rival}, esperaba ganar {r.p_esp * 100:.0f}%</small></td>"
            f"<td class='l'>{r.qb_nombre or 'n/d'} <small>({_fmt(r.elo_qb, 0, True)})</small></td></tr>")
    rank = ('<div class="scroll"><table class="elo"><thead><tr><th>#</th><th class="l">Equipo</th><th>Elo</th>'
            '<th>Cambio en la temporada</th><th>Últimos 4</th><th>Último partido</th><th class="l">QB (aporte al Elo)</th></tr></thead><tbody>'
            + "".join(filas) + "</tbody></table></div>")
    # partidos de la semana
    ee = t.set_index("equipo")
    pf = []
    pend = E["partidos"].set_index("game_id")
    for x in res.itertuples():
        if x.game_id not in pend.index:
            continue
        q = pend.loc[x.game_id]
        pm = getattr(x, "p_gana_local", np.nan)
        pk = getattr(x, "p_gana_local_mercado", np.nan)
        pf.append(
            f"<tr><td class='l'><b>{x.away_team}</b> @ <b>{x.home_team}</b></td>"
            f"<td>{_fmt(q.elo_a)}<br><small>{x.away_team}</small></td><td>{_fmt(q.elo_h)}<br><small>{x.home_team}</small></td>"
            f"<td><b>{q.p_elo * 100:.0f}%</b></td><td>{_fmt(pm * 100) + '%' if pd.notna(pm) else 'n/d'}</td>"
            f"<td>{_fmt(pk * 100) + '%' if pd.notna(pk) else 'n/d'}</td></tr>")
    juegos = ('<div class="scroll"><table class="elo"><thead><tr><th class="l">Partido</th><th>Elo visita</th><th>Elo local</th>'
              '<th>Gana local según Elo</th><th>Gana local según el modelo</th><th>Gana local según el mercado</th></tr></thead><tbody>'
              + "".join(pf) + "</tbody></table></div>") if pf else ""
    return f"""<h2 id="elo">Elo de los equipos (desde la temporada {E['desde']})</h2>
<p class="explain">El Elo es un número de fuerza por equipo (1500 = promedio). Se mueve según la <b>sorpresa</b> del resultado:
si un <b>favorito pierde</b>, baja mucho; si un <b>favorito gana</b>, sube poco; si un <b>no favorito gana</b>, sube más.
Ganar por más puntos pesa más. El número incluye el aporte del <b>quarterback</b> que jugó (entre paréntesis): si cambia el titular, cambia el Elo del equipo.
Se calcula desde la temporada {E['desde']} (todos arrancaron en 1500), así que las primeras semanas de esa temporada son poco confiables.
Unos 25 puntos de Elo equivalen a ~1 punto de spread.</p>
{rank}
{('<h3>Elo de los partidos de esta semana</h3>' + juegos) if juegos else ''}
<p class="explain"><b>Para qué sirve y para qué no:</b> en el backtest el Elo mejora al modelo que no usa el mercado, pero <b>no aporta nada nuevo al modelo B</b> (el spread ya contiene esa información). Úsalo como lectura rápida de quién va bien o mal, no como señal de apuesta.</p>"""
