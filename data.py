"""Descarga y cache de datos de nflverse (calendario/lineas y play-by-play).

El play-by-play (~20 MB por temporada) se agrega a nivel equipo-partido y solo se
guarda el resumen, asi el proyecto ocupa pocos MB.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

import db

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)

# Abreviaturas historicas -> franquicia actual (mantiene la continuidad de los ratings)
TEAM_MAP = {"STL": "LA", "LAR": "LA", "SD": "LAC", "OAK": "LV", "ARZ": "ARI",
            "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "JAC": "JAX", "WSH": "WAS"}

PBP_COLS = ["game_id", "posteam", "defteam", "play_type", "epa", "wp"]
FIRST_SEASON = 1999


def _download(url: str, dest: Path, retries: int = 3) -> bool:
    """Descarga `url` a `dest`. Devuelve False si no existe (404)."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            err = e
        except Exception as e:  # red inestable: reintentar
            err = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {err}")


def norm_team(s: pd.Series) -> pd.Series:
    return s.replace(TEAM_MAP)


def _guardar_games(g: pd.DataFrame, fuente: str, cuando=None) -> None:
    for c in ("home_team", "away_team"):
        g[c] = norm_team(g[c])
    db.reemplazar("games", g, fuente=fuente, cuando=cuando)


def load_schedules(refresh: bool = False) -> pd.DataFrame:
    """Calendario, resultados y lineas de mercado (spread, total, moneyline). Vive en la tabla `games`."""
    existe = db.hay("games")
    viejo = DATA / "games.csv"
    if not existe and viejo.exists():                      # viene de una version anterior (CSV): lo migra
        db.importar_csv_antiguo("games", viejo, lambda d: d.assign(home_team=norm_team(d.home_team),
                                                                   away_team=norm_team(d.away_team)))
        existe = True
    if refresh or not existe:
        tmp = DATA / "_games.csv"
        try:
            _download(f"{BASE}/schedules/games.csv", tmp)
            _guardar_games(pd.read_csv(tmp), "nflverse schedules")
        except RuntimeError as e:
            if not existe:
                raise
            print(f"  [aviso] sin conexion, uso el calendario guardado ({e.__class__.__name__})")
        finally:
            tmp.unlink(missing_ok=True)
    g = db.leer("games", ordenar=None)
    g["gameday"] = pd.to_datetime(g["gameday"])
    return g.sort_values(["gameday", "game_id"]).reset_index(drop=True)


def _aggregate_pbp(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=PBP_COLS, low_memory=False)
    df = df[df.play_type.isin(["pass", "run"]) & df.epa.notna()
            & df.posteam.notna() & df.defteam.notna()]
    # Filtro de "garbage time": jugadas con prob. de victoria entre 5% y 95%
    df = df[df.wp.isna() | df.wp.between(0.05, 0.95)].copy()
    df["posteam"] = norm_team(df.posteam)
    df["defteam"] = norm_team(df.defteam)
    df["kind"] = np.where(df.play_type == "pass", "pass", "rush")
    agg = (df.groupby(["game_id", "posteam", "defteam", "kind"]).epa
             .agg(["mean", "size"]).unstack("kind"))
    agg.columns = [f"{'epa' if stat == 'mean' else 'n'}_{kind}" for stat, kind in agg.columns]
    return agg.reset_index().rename(columns={"posteam": "team", "defteam": "opp"})


def load_team_games(seasons, refresh_seasons=()) -> pd.DataFrame:
    """EPA por jugada (pase/carrera) de cada equipo en cada partido (tabla `team_games`).

    Las temporadas pasadas se descargan una sola vez; las de `refresh_seasons`
    (normalmente la temporada en curso) se vuelven a bajar.
    """
    seasons = list(seasons)
    for season in seasons:
        if not db.hay("team_games", season):
            db.importar_csv_antiguo("team_games", DATA / f"tg_{season}.csv", temporada=season)
        if season in refresh_seasons or not db.hay("team_games", season):
            raw = DATA / f"_pbp_{season}.csv.gz"
            try:
                ok = _download(f"{BASE}/pbp/play_by_play_{season}.csv.gz", raw)
            except RuntimeError:
                if not db.hay("team_games", season):
                    raise
                print(f"  [aviso] sin conexion, uso el play-by-play guardado de {season}")
                ok = None
            if ok is False:
                print(f"  [aviso] todavia no hay play-by-play para {season}")
            elif ok:
                db.reemplazar("team_games", _aggregate_pbp(raw), season, fuente="nflverse pbp")
                print(f"  play-by-play {season} listo")
            raw.unlink(missing_ok=True)
    return db.leer("team_games", seasons).drop(columns="season")


if __name__ == "__main__":
    g = load_schedules(refresh=True)
    cur = int(g.loc[g.result.notna(), "season"].max())
    tg = load_team_games(range(FIRST_SEASON, cur + 1), refresh_seasons=(cur,))
    print(g.shape, tg.shape)
