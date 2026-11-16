"""Descarga y cache de estadisticas por jugador y reportes de lesiones (nflverse)."""
from __future__ import annotations

import pandas as pd

import db
from data import BASE, DATA, _download, norm_team

FIRST_PLAYER_SEASON = 2012
POS_MAP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE"}
KEEP = ["player_id", "player_display_name", "position", "season", "week", "season_type", "team",
        "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "receptions", "targets", "receiving_yards", "target_share", "wopr",
        "rushing_tds", "receiving_tds"]
RENAME = {"player_display_name": "name", "completions": "cmp", "attempts": "att", "passing_yards": "pass_yds",
          "passing_tds": "pass_td", "passing_interceptions": "pass_int", "carries": "car",
          "rushing_yards": "rush_yds", "receptions": "rec", "targets": "tgt", "receiving_yards": "rec_yds",
          "target_share": "tshare", "rushing_tds": "rush_td", "receiving_tds": "rec_td"}


def _reduce(path) -> pd.DataFrame:
    d = pd.read_csv(path, usecols=lambda c: c in KEEP, low_memory=False)
    d["position"] = d.position.map(POS_MAP)
    d = d[d.position.notna()].copy()
    num = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries",
           "rushing_yards", "receptions", "targets", "receiving_yards", "target_share", "wopr", "rushing_tds", "receiving_tds"]
    d[num] = d[num].fillna(0)
    d = d[(d.attempts + d.carries + d.targets) > 0]
    d["team"] = norm_team(d.team)
    return d.rename(columns=RENAME)


def load_player_weeks(seasons, refresh_seasons=()) -> pd.DataFrame:
    """Una fila por jugador-partido (QB/RB/WR/TE) con volumen ofensivo > 0 (tabla `player_weeks`).
    Incluye touchdowns por tierra (rush_td), por recepcion (rec_td) y `td` = rush_td + rec_td (anotar, sin TD de pase)."""
    seasons = list(seasons)
    for s in seasons:
        if not db.hay("player_weeks", s):
            db.importar_csv_antiguo("player_weeks", DATA / f"pw_{s}.csv", temporada=s)
    # bases creadas antes de existir los TD: se vuelven a bajar una vez todas las temporadas
    migrar = db.hay("player_weeks") and not db.tiene_columna("player_weeks", "rush_td")
    if migrar:
        print("  Actualizando estadisticas de jugadores para incluir touchdowns (una sola vez) ...")
    for s in seasons:
        if s in refresh_seasons or migrar or not db.hay("player_weeks", s):
            raw = DATA / f"_pw_{s}.csv"
            if not _download(f"{BASE}/stats_player/stats_player_week_{s}.csv", raw):
                print(f"  [aviso] no hay estadisticas de jugadores para {s}")
                continue
            db.reemplazar("player_weeks", _reduce(raw), s, fuente="nflverse stats_player")
            raw.unlink(missing_ok=True)
            print(f"  jugadores {s} listo")
    d = db.leer("player_weeks", seasons)
    for c in ("rush_td", "rec_td"):
        d[c] = d[c].fillna(0) if c in d else 0.0
    d["td"] = d.rush_td + d.rec_td
    return d


_INJ_COLS = ("season", "week", "team", "gsis_id", "full_name", "position", "report_status",
             "report_primary_injury", "practice_status")


def load_injuries(season: int, refresh: bool = True) -> pd.DataFrame:
    """Reporte de lesiones de la temporada (report_status: Out/Doubtful/Questionable). Tabla `injuries`."""
    if not db.hay("injuries", season):
        db.importar_csv_antiguo("injuries", DATA / f"inj_{season}.csv", temporada=season,
                                transformar=lambda d: d[[c for c in d.columns if c in _INJ_COLS]])
    if refresh or not db.hay("injuries", season):
        tmp = DATA / f"_inj_{season}.csv"
        try:
            if _download(f"{BASE}/injuries/injuries_{season}.csv", tmp) is False:
                return pd.DataFrame()
            d = pd.read_csv(tmp, usecols=lambda c: c in _INJ_COLS)
            db.reemplazar("injuries", d, season, fuente="nflverse injuries")
        except Exception as e:  # sin internet: usa lo guardado si existe
            if not db.hay("injuries", season):
                print(f"  [aviso] no pude bajar lesiones ({e})")
                return pd.DataFrame()
        finally:
            tmp.unlink(missing_ok=True)
    d = db.leer("injuries", [season]).drop(columns="season")
    d.insert(0, "season", season)
    d["team"] = norm_team(d.team)
    return d


def load_depth(season: int, refresh: bool = True) -> pd.DataFrame:
    """Depth chart mas reciente por equipo (QB/RB/WR/TE), tabla `depth`. El archivo completo es grande
    (~70 MB), asi que se descarga como maximo una vez cada 20 horas y solo se guarda la ultima version."""
    if not db.hay("depth", season):
        db.importar_csv_antiguo("depth", DATA / f"depth_{season}.csv", temporada=season)
    fresh = db.hay("depth", season) and db.horas_desde("depth", season) < 20
    if refresh and not fresh:
        raw = DATA / f"_depth_{season}.csv"
        try:
            ok = _download(f"{BASE}/depth_charts/depth_charts_{season}.csv", raw)
            if ok is not False:
                d = pd.read_csv(raw, usecols=["dt", "team", "player_name", "gsis_id", "pos_abb", "pos_rank"], low_memory=False)
                d = d[d.pos_abb.isin(["QB", "RB", "FB", "WR", "TE"])]
                d = d[d.dt == d.groupby("team").dt.transform("max")]
                db.reemplazar("depth", d, season, fuente="nflverse depth_charts")
        except Exception as e:
            print(f"  [aviso] no pude bajar el depth chart ({e})")
        finally:
            raw.unlink(missing_ok=True)
    if not db.hay("depth", season):
        return pd.DataFrame()
    d = db.leer("depth", [season]).drop(columns="season")
    d["team"] = norm_team(d.team)
    return d


# ---------------------------------------------------------------- snaps ofensivos (variables de rol)
def load_players_map(refresh: bool = True) -> dict:
    """pfr_id -> gsis_id (para cruzar los snaps, que traen el id de Pro Football Reference). Copia local, se renueva cada 20 dias."""
    ruta = DATA / "players_min.csv"
    viejo = (not ruta.exists()) or (pd.Timestamp.now().timestamp() - ruta.stat().st_mtime > 20 * 86400)
    if refresh and viejo:
        tmp = DATA / "_players.csv"
        try:
            if _download(f"{BASE}/players/players.csv", tmp):
                pd.read_csv(tmp, usecols=["gsis_id", "pfr_id"]).dropna().to_csv(ruta, index=False)
        except Exception as e:
            print(f"  [aviso] no pude bajar el catalogo de jugadores ({e})")
        finally:
            tmp.unlink(missing_ok=True)
    if not ruta.exists():
        return {}
    d = pd.read_csv(ruta)
    return dict(zip(d.pfr_id, d.gsis_id))


def load_snaps(seasons, refresh_seasons=()) -> pd.DataFrame:
    """Snaps ofensivos por jugador-partido (tabla `snaps`): player_id (gsis), game_id, offense_snaps, offense_pct.
    nflverse los publica desde 2013; sin internet usa lo guardado."""
    seasons = [s for s in seasons if s >= 2013]
    mp = None
    for s in seasons:
        if s in refresh_seasons or not db.hay("snaps", s):
            raw = DATA / f"_snaps_{s}.csv"
            try:
                if not _download(f"{BASE}/snap_counts/snap_counts_{s}.csv", raw):
                    continue
                mp = mp or load_players_map(True)
                d = pd.read_csv(raw, usecols=["game_id", "game_type", "pfr_player_id", "offense_snaps", "offense_pct"])
                d = d[d.game_type == "REG"].copy()
                d["player_id"] = d.pfr_player_id.map(mp)
                d = d.dropna(subset=["player_id"])[["player_id", "game_id", "offense_snaps", "offense_pct"]]
                db.reemplazar("snaps", d, s, fuente="nflverse snap_counts")
                print(f"  snaps {s} listo")
            except Exception as e:
                if not db.hay("snaps", s):
                    print(f"  [aviso] no pude bajar snaps {s} ({e})")
            finally:
                raw.unlink(missing_ok=True)
    have = [s for s in seasons if db.hay("snaps", s)]
    if not have:
        return pd.DataFrame(columns=["season", "player_id", "game_id", "offense_snaps", "offense_pct"])
    return db.leer("snaps", have)
