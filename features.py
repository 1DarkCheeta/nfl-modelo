"""Variables por partido: ratings adaptativos de ataque/defensa ajustados por rival.

Para cada metrica m (EPA/jugada de pase, EPA/jugada de carrera, puntos) cada equipo
tiene un rating de ataque y uno de defensa. Tras cada partido:

    esperado = media_liga + ataque[equipo] + defensa[rival]
    error    = observado - esperado
    ataque[equipo] += k * error ;  defensa[rival] += k * error

Defensa positiva = permite mas que el promedio. Los ratings se registran ANTES de
actualizarse con el partido, por lo que no hay fuga de informacion (data leakage).
Al empezar cada temporada los ratings se encogen hacia 0 (regresion a la media).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

METRICS = ("pass", "rush", "pts")
MU_INIT = {"pass": 0.08, "rush": -0.07, "pts": 20.5}
MU_HALFLIFE = 600  # observaciones (~1 temporada) para la media de liga


def build_ratings(games: pd.DataFrame, tg: pd.DataFrame, k: float = 0.05,
                  shrink: float = 0.65, return_state: bool = False):
    """Devuelve, por game_id, los ratings esperados de cada lado ANTES del partido.

    Con return_state=True devuelve ademas los ratings actuales de cada equipo."""
    games = games.sort_values(["gameday", "game_id"])
    obs = {(r.game_id, r.team): {"pass": r.epa_pass, "rush": r.epa_rush}
           for r in tg.itertuples(index=False)}

    off = {m: defaultdict(float) for m in METRICS}
    dff = {m: defaultdict(float) for m in METRICS}
    mu = dict(MU_INIT)
    alpha = 1 - 0.5 ** (1 / MU_HALFLIFE)

    rows, last_season = [], None
    for r in games.itertuples(index=False):
        if r.season != last_season:
            if last_season is not None:  # regresion a la media entre temporadas
                for m in METRICS:
                    for t in list(off[m]):
                        off[m][t] *= shrink
                        dff[m][t] *= shrink
            last_season = r.season
        h, a = r.home_team, r.away_team

        feat = {"game_id": r.game_id, "mu_pts": mu["pts"]}
        for m in METRICS:
            feat[f"{m}_h"] = off[m][h] + dff[m][a]   # produccion esperada del local
            feat[f"{m}_a"] = off[m][a] + dff[m][h]   # produccion esperada del visitante
        rows.append(feat)

        # Actualizar solo si el partido ya se jugo y hay play-by-play de ambos lados
        if pd.isna(r.home_score) or (r.game_id, h) not in obs or (r.game_id, a) not in obs:
            continue
        for team, opp, pts in ((h, a, r.home_score), (a, h, r.away_score)):
            o = obs[(r.game_id, team)]
            vals = {"pass": o["pass"], "rush": o["rush"], "pts": pts}
            for m in METRICS:
                v = vals[m]
                if pd.isna(v):
                    continue
                err = v - (mu[m] + off[m][team] + dff[m][opp])
                off[m][team] += k * err
                dff[m][opp] += k * err
                mu[m] += alpha * (v - mu[m])
    feats = pd.DataFrame(rows)
    if return_state:
        return feats, {"off": off, "dff": dff, "mu": mu}
    return feats


def power_table(state: dict) -> pd.DataFrame:
    """Fuerza actual de cada equipo (contra un rival promedio).

    pts_net: puntos por partido por encima/debajo del promedio (ataque - puntos permitidos).
    pass_net / rush_net: EPA por jugada neto (ataque - EPA permitido)."""
    rows = []
    for t in state["off"]["pts"]:
        r = {"team": t}
        for m in METRICS:
            r[f"{m}_net"] = state["off"][m][t] - state["dff"][m][t]
        rows.append(r)
    return pd.DataFrame(rows).sort_values("pts_net", ascending=False).reset_index(drop=True)


def build_dataset(games: pd.DataFrame, tg: pd.DataFrame, k: float = 0.05,
                  shrink: float = 0.65, return_state: bool = False):
    """Une calendario + ratings y crea las variables que usan los modelos."""
    feats, state = build_ratings(games, tg, k, shrink, return_state=True)
    df = games.merge(feats, on="game_id", how="left")

    # Diferencias (positivo = favorece al local) -> modelo de margen / ganador
    for m in METRICS:
        df[f"{m}_diff"] = df[f"{m}_h"] - df[f"{m}_a"]
        df[f"{m}_sum"] = df[f"{m}_h"] + df[f"{m}_a"]   # -> modelo de totales

    df["rest_diff"] = (df.home_rest.fillna(7) - df.away_rest.fillna(7)).clip(-7, 7)
    df["neutral"] = (df.location == "Neutral").astype(int)
    df["dome"] = df.roof.isin(["dome", "closed"]).astype(int)
    df["wind_eff"] = np.where(df.dome == 1, 0.0, df.wind.fillna(0.0))
    return (df, state) if return_state else df
