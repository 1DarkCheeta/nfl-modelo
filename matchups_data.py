"""Datos para los matchups: presion y blitz por equipo y partido.

Fuentes (todas de nflverse, que redistribuye lo mismo que consultan PFR y rbsdm):
  - play-by-play (EPA por jugada, sacks, golpes al QB)            -> lo que usa rbsdm.com
  - FTN charting (cuantos jugadores blitzean en cada jugada)       -> 2022 en adelante
  - PFR advanced stats (presiones y hurries por partido)          -> lo que muestra pro-football-reference
  - Depth charts y lesiones                                        -> quien juega de titular (ourlads)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import db
from data import BASE, DATA, _download, norm_team

PBP_COLS = ["game_id", "play_id", "posteam", "defteam", "qb_dropback", "epa", "sack", "qb_hit", "wp", "season", "week"]
FIRST_FTN = 2022


def _agg_offense(pbp_path, ftn_path) -> pd.DataFrame:
    p = pd.read_csv(pbp_path, usecols=PBP_COLS, low_memory=False)
    p = p[(p.qb_dropback == 1) & p.epa.notna() & p.posteam.notna() & p.defteam.notna()]
    p = p[p.wp.isna() | p.wp.between(0.05, 0.95)].copy()
    p["posteam"], p["defteam"] = norm_team(p.posteam), norm_team(p.defteam)
    p["blitz"] = np.nan
    if ftn_path is not None:
        f = pd.read_csv(ftn_path, usecols=["nflverse_game_id", "nflverse_play_id", "n_blitzers"])
        f = f.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
        p = p.drop(columns="blitz").merge(f, on=["game_id", "play_id"], how="left")
        p["blitz"] = np.where(p.n_blitzers.isna(), np.nan, (p.n_blitzers >= 1).astype(float))
    p["hit"] = ((p.qb_hit == 1) | (p.sack == 1)).astype(int)
    g = p.groupby(["season", "week", "game_id", "posteam", "defteam"])
    out = g.agg(db=("epa", "size"), epa_sum=("epa", "sum"), sacks=("sack", "sum"), pres_vis=("hit", "sum")).reset_index()
    for lab, cond in (("bl", p.blitz == 1), ("nb", p.blitz == 0)):
        s = p[cond].groupby(["game_id", "posteam"]).agg(**{f"db_{lab}": ("epa", "size"), f"epa_{lab}": ("epa", "sum")}).reset_index()
        out = out.merge(s, on=["game_id", "posteam"], how="left")
    out[["db_bl", "epa_bl", "db_nb", "epa_nb"]] = out[["db_bl", "epa_bl", "db_nb", "epa_nb"]].fillna(0)
    return out.rename(columns={"posteam": "team", "defteam": "opp"})


def _agg_pfr(season: int) -> pd.DataFrame:
    """Presiones de PFR por equipo y partido (ataque: presiones sufridas; defensa: presiones generadas)."""
    parts = {}
    for kind, col in (("pass", "times_pressured"), ("def", "def_pressures")):
        path = DATA / f"_pfr_{kind}_{season}.csv"
        if _download(f"{BASE}/pfr_advstats/advstats_week_{kind}_{season}.csv", path) is False:
            return pd.DataFrame()
        d = pd.read_csv(path, usecols=["game_id", "team", col]).copy()
        path.unlink()
        d["team"] = norm_team(d.team)
        parts[kind] = d.groupby(["game_id", "team"])[col].sum(min_count=1).reset_index()
    a = parts["pass"].rename(columns={"times_pressured": "pfr_pres_suf"})
    b = parts["def"].rename(columns={"def_pressures": "pfr_pres_gen"})
    return a.merge(b, on=["game_id", "team"], how="outer")


def load_matchup_games(seasons, refresh_seasons=()) -> pd.DataFrame:
    """Una fila por equipo-partido (ataque): dropbacks, EPA, blitz y presion (tabla `matchup_games`)."""
    seasons = list(seasons)
    for s in seasons:
        if not db.hay("matchup_games", s):
            db.importar_csv_antiguo("matchup_games", DATA / f"mu_{s}.csv", temporada=s)
        if s in refresh_seasons or not db.hay("matchup_games", s):
            pbp, ftn = DATA / f"_mu_pbp_{s}.csv.gz", DATA / f"_mu_ftn_{s}.csv"
            try:
                if _download(f"{BASE}/pbp/play_by_play_{s}.csv.gz", pbp) is False:
                    print(f"  [aviso] no hay play-by-play {s}")
                    continue
                have_ftn = s >= FIRST_FTN and _download(f"{BASE}/ftn_charting/ftn_charting_{s}.csv", ftn) is not False
                off = _agg_offense(pbp, ftn if have_ftn else None)
                pfr = _agg_pfr(s) if s >= 2018 else pd.DataFrame()
                if len(pfr):
                    off = off.merge(pfr, on=["game_id", "team"], how="left")
                db.reemplazar("matchup_games", off, s, fuente="nflverse pbp + ftn + pfr_advstats")
                print(f"  matchups {s} listo")
            finally:
                pbp.unlink(missing_ok=True)
                ftn.unlink(missing_ok=True)
    return db.leer("matchup_games", seasons)
