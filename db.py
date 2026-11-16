"""Base de datos SQLite del proyecto (data/nfl.db).

Un solo archivo, sin servidor: Python ya trae SQLite. Cada ejecucion descarga lo nuevo de nflverse y lo
guarda aqui; el modelo lee SIEMPRE de esta base. Tablas:

  Datos descargados (se actualizan solos)
    games              calendario, resultados y lineas de mercado
    team_games         EPA por jugada (pase/carrera) de cada equipo en cada partido
    matchup_games      dropbacks, blitz y presion por equipo y partido
    player_weeks       estadisticas por jugador y semana (QB/RB/WR/TE)
    injuries           reportes de lesiones
    depth              depth chart mas reciente por equipo
    descargas          registro de que se descargo y cuando

  Historial que se va llenando con cada ejecucion (lo que el modelo dijo ese dia)
    lineas_historial       movimiento de la linea/cuotas de cada partido
    predicciones_modelo    probabilidades y margenes del modelo
    props_proyecciones     proyeccion de cada jugador (para medir despues que tan bien acerto)
    lineas_casas           lineas/precios de props tomados solos de Kalshi (y de DraftKings via The Odds API si pones tu llave)
    props_cobertura        por jugador-partido de la temporada pasada y la actual: linea, resultado y si la cubrio (local/visita)

  Vistas listas para consultar: v_jugador_temporada, v_defensa_permite, v_props_resultados,
  v_props_precision, v_cobertura_jugador, v_equipos_resultados.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd

RUTA = Path(__file__).parent / "data" / "nfl.db"
RUTA.parent.mkdir(exist_ok=True)

_MAP_REAL = {  # mercado de props -> columna real en player_weeks
    "pass_yds": "pass_yds", "pass_cmp": "cmp", "pass_td": "pass_td", "pass_int": "pass_int",
    "rush_yds": "rush_yds", "rush_att": "car", "rec_yds": "rec_yds", "rec": "rec", "tgt": "tgt", "td": "rush_td + w.rec_td"}
_CASE_REAL = "CASE p.market " + " ".join(f"WHEN '{m}' THEN w.{c}" for m, c in _MAP_REAL.items()) + " END"

VISTAS = {
    "v_jugador_temporada": """
        SELECT season, player_id, name, position, team,
               COUNT(DISTINCT week) AS partidos,
               SUM(att) AS pases, SUM(cmp) AS completos, SUM(pass_yds) AS yardas_pase,
               ROUND(SUM(pass_yds) * 1.0 / COUNT(DISTINCT week), 1) AS yardas_pase_por_partido,
               SUM(car) AS acarreos, SUM(rush_yds) AS yardas_tierra,
               ROUND(SUM(car) * 1.0 / COUNT(DISTINCT week), 1) AS acarreos_por_partido,
               SUM(tgt) AS targets, SUM(rec) AS recepciones, SUM(rec_yds) AS yardas_recepcion,
               ROUND(SUM(tgt) * 1.0 / COUNT(DISTINCT week), 1) AS targets_por_partido,
               ROUND(SUM(rec) * 100.0 / NULLIF(SUM(tgt), 0), 1) AS pct_atrapadas,
               ROUND(SUM(rec_yds) * 1.0 / NULLIF(SUM(rec), 0), 1) AS yardas_por_recepcion,
               ROUND(SUM(rec_yds) * 1.0 / COUNT(DISTINCT week), 1) AS yardas_recepcion_por_partido
        FROM player_weeks WHERE season_type = 'REG'
        GROUP BY season, player_id, name, position, team""",
    "v_defensa_permite": """
        SELECT season, defensa, COUNT(DISTINCT game_id) AS partidos,
               ROUND(SUM(pass_yds) * 1.0 / COUNT(DISTINCT game_id), 1) AS yardas_aire_por_partido,
               ROUND(SUM(rush_yds) * 1.0 / COUNT(DISTINCT game_id), 1) AS yardas_tierra_por_partido
        FROM (SELECT g.season, g.game_id,
                     CASE WHEN w.team = g.home_team THEN g.away_team ELSE g.home_team END AS defensa,
                     w.pass_yds, w.rush_yds
              FROM player_weeks w JOIN games g ON g.season = w.season AND g.week = w.week
                   AND (w.team = g.home_team OR w.team = g.away_team)
              WHERE w.season_type = 'REG')
        GROUP BY season, defensa""",
    "v_props_resultados": f"""
        SELECT p.capturado, p.season, p.week, p.team, p.opp, p.name, p.position, p.market,
               p.base AS promedio_reciente, p.mu AS proyeccion, p.line_n AS linea_normal, {_CASE_REAL} AS real
        FROM props_proyecciones p
        JOIN player_weeks w ON w.player_id = p.player_id AND w.season = p.season AND w.week = p.week""",
    "v_props_precision": """
        SELECT market AS mercado, COUNT(*) AS n,
               ROUND(AVG(ABS(proyeccion - real)), 2) AS error_modelo,
               ROUND(AVG(ABS(promedio_reciente - real)), 2) AS error_promedio_reciente
        FROM v_props_resultados GROUP BY market""",
    "v_cobertura_jugador": """
        SELECT season, player_id, name, position, market AS mercado, COUNT(cubrio) AS partidos, SUM(cubrio) AS cubrio,
               ROUND(100.0 * SUM(cubrio) / COUNT(cubrio), 1) AS pct_cubrio,
               SUM(CASE WHEN is_home = 1 THEN 1 ELSE 0 END) AS partidos_local,
               SUM(CASE WHEN is_home = 1 THEN cubrio ELSE 0 END) AS cubrio_local,
               ROUND(100.0 * SUM(CASE WHEN is_home = 1 THEN cubrio END) / NULLIF(SUM(CASE WHEN is_home = 1 THEN 1 ELSE 0 END), 0), 1) AS pct_local,
               SUM(CASE WHEN is_home = 0 THEN 1 ELSE 0 END) AS partidos_visita,
               SUM(CASE WHEN is_home = 0 THEN cubrio ELSE 0 END) AS cubrio_visita,
               ROUND(100.0 * SUM(CASE WHEN is_home = 0 THEN cubrio END) / NULLIF(SUM(CASE WHEN is_home = 0 THEN 1 ELSE 0 END), 0), 1) AS pct_visita
        FROM props_cobertura WHERE cubrio IS NOT NULL
        GROUP BY season, player_id, name, position, market""",
    "v_equipos_resultados": """
        SELECT p.game_id, p.capturado, g.season, g.week, g.away_team AS visita, g.home_team AS local,
               g.spread_line AS margen_mercado, ROUND(p.pred_mB, 1) AS margen_modelo_B, g.result AS margen_real,
               ROUND(ABS(g.spread_line - g.result), 1) AS error_mercado,
               ROUND(ABS(p.pred_mB - g.result), 1) AS error_modelo_B
        FROM predicciones_modelo p JOIN games g ON g.game_id = p.game_id
        WHERE g.result IS NOT NULL""",
}


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(RUTA, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS descargas (
        tabla TEXT, temporada INTEGER, filas INTEGER, fuente TEXT, descargado TEXT,
        PRIMARY KEY (tabla, temporada))""")
    for v, sql in VISTAS.items():           # se recrean siempre: asi se actualizan al cambiar de version
        con.execute(f"DROP VIEW IF EXISTS {v}")
        con.execute(f"CREATE VIEW {v} AS {sql}")
    return con


def _existe(con, tabla: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone() is not None


def _tipos(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite devuelve columnas vacias como objeto: las pasa a numericas cuando corresponde."""
    for c in df.columns[df.dtypes == object]:
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass
    return df


def _sql_tipo(serie: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(serie):
        return "INTEGER"
    return "REAL" if pd.api.types.is_float_dtype(serie) else "TEXT"


def tiene_columna(tabla: str, columna: str) -> bool:
    con = _con()
    try:
        return _existe(con, tabla) and any(r[1] == columna for r in con.execute(f"PRAGMA table_info({tabla})"))
    finally:
        con.close()


def hay(tabla: str, temporada: int | None = None) -> bool:
    con = _con()
    try:
        if not _existe(con, tabla):
            return False
        if temporada is None:
            return con.execute(f"SELECT 1 FROM {tabla} LIMIT 1").fetchone() is not None
        return con.execute(f"SELECT 1 FROM {tabla} WHERE season = ? LIMIT 1", (int(temporada),)).fetchone() is not None
    finally:
        con.close()


def reemplazar(tabla: str, df: pd.DataFrame, temporada: int | None = None, fuente: str = "nflverse",
               cuando: str | None = None) -> None:
    """Guarda `df`. Con `temporada` solo reemplaza esa temporada; sin ella reemplaza la tabla completa."""
    con = _con()
    try:
        if temporada is None:
            df.to_sql(tabla, con, if_exists="replace", index=False)
        else:
            df = df.copy()
            df["season"] = int(temporada)
            if _existe(con, tabla):
                con.execute(f"DELETE FROM {tabla} WHERE season = ?", (int(temporada),))
                tiene = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}
                for c in df.columns:
                    if c not in tiene:
                        con.execute(f'ALTER TABLE {tabla} ADD COLUMN "{c}" {_sql_tipo(df[c])}')
            df.to_sql(tabla, con, if_exists="append", index=False)
        for col in ("season", "game_id", "player_id"):
            if col in df.columns:
                con.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabla}_{col} ON {tabla}({col})")
        con.execute("INSERT OR REPLACE INTO descargas VALUES (?,?,?,?,?)",
                    (tabla, -1 if temporada is None else int(temporada), len(df), fuente, cuando or _ahora()))
        con.commit()
    finally:
        con.close()


def agregar_foto(tabla: str, df: pd.DataFrame) -> None:
    """Agrega una «foto» (p. ej. lineas de casas): por fuente solo se conserva la ultima del dia, y las de dias anteriores se mantienen."""
    con = _con()
    try:
        if _existe(con, tabla):
            for f in df.fuente.unique():
                con.execute(f"DELETE FROM {tabla} WHERE fuente = ? AND substr(capturado,1,10) = ?", (f, _ahora()[:10]))
        df.to_sql(tabla, con, if_exists="append", index=False)
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabla}_cap ON {tabla}(capturado)")
        con.commit()
    finally:
        con.close()


def marcar_descarga(tabla: str, filas: int, fuente: str) -> None:
    con = _con()
    try:
        con.execute("INSERT OR REPLACE INTO descargas VALUES (?,?,?,?,?)", (tabla, -1, int(filas), fuente, _ahora()))
        con.commit()
    finally:
        con.close()


def leer(tabla: str, temporadas=None, ordenar: str = "season, rowid") -> pd.DataFrame:
    con = _con()
    try:
        sql, par = f"SELECT * FROM {tabla}", []
        if temporadas is not None:
            temporadas = [int(t) for t in temporadas]
            sql += f" WHERE season IN ({','.join('?' * len(temporadas))})"
            par = temporadas
        if ordenar:
            sql += f" ORDER BY {ordenar}"
        return _tipos(pd.read_sql(sql, con, params=par))
    finally:
        con.close()


def horas_desde(tabla: str, temporada: int | None = None) -> float:
    """Horas desde la ultima descarga de esa tabla (inf si nunca)."""
    con = _con()
    try:
        r = con.execute("SELECT descargado FROM descargas WHERE tabla = ? AND temporada = ?",
                        (tabla, -1 if temporada is None else int(temporada))).fetchone()
    finally:
        con.close()
    if not r:
        return float("inf")
    t = dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600


def importar_csv_antiguo(tabla: str, ruta: Path, transformar=None, temporada: int | None = None) -> bool:
    """Si existe un CSV de una version anterior del proyecto, lo pasa a la base (evita volver a descargar)."""
    if not Path(ruta).exists():
        return False
    df = pd.read_csv(ruta, low_memory=False)
    if transformar:
        df = transformar(df)
    cuando = dt.datetime.fromtimestamp(Path(ruta).stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    reemplazar(tabla, df, temporada, fuente=f"csv antiguo {Path(ruta).name}", cuando=cuando)
    return True


# ---------------------------------------------------------------- historial de cada ejecucion
def guardar_historial(res: pd.DataFrame, props: pd.DataFrame | None, cur: int, semana: int) -> dict:
    """Guarda lineas, predicciones y proyecciones de props de esta ejecucion. Devuelve cuantas filas nuevas."""
    ahora, hoy = _ahora(), _ahora()[:10]
    n = {}
    con = _con()
    try:
        # 1) lineas: solo cuando cambian respecto de la ultima captura (asi se ve el movimiento sin duplicar)
        cols = ["game_id", "season", "week", "gameday", "away_team", "home_team", "spread_line", "total_line",
                "home_moneyline", "away_moneyline"]
        nuevo = res[cols].copy()
        nuevo["gameday"] = nuevo.gameday.astype(str).str[:10]
        nuevo.insert(0, "capturado", ahora)
        if _existe(con, "lineas_historial"):
            ult = pd.read_sql("""SELECT l.* FROM lineas_historial l JOIN
                                 (SELECT game_id, MAX(capturado) m FROM lineas_historial GROUP BY game_id) x
                                 ON l.game_id = x.game_id AND l.capturado = x.m""", con)
            k = ["spread_line", "total_line", "home_moneyline", "away_moneyline"]
            m = nuevo.merge(ult[["game_id"] + k], on="game_id", how="left", suffixes=("", "_u"), indicator=True)
            igual = (m._merge == "both").values
            for c in k:
                igual = igual & ((m[c] == m[c + "_u"]) | (m[c].isna() & m[c + "_u"].isna())).values
            nuevo = nuevo[~igual]
        if len(nuevo):
            nuevo.to_sql("lineas_historial", con, if_exists="append", index=False)
        n["lineas"] = len(nuevo)

        # 2) predicciones del modelo: una foto por partido y por dia (la ultima del dia)
        pc = ["game_id", "season", "week", "pred_mA", "pred_mB", "pred_tB", "p_gana_local", "p_cubre_local", "p_over",
              "sp_lado", "sp_edge", "to_lado", "to_edge", "ml_lado", "ml_edge"]
        pr = res[[c for c in pc if c in res.columns]].copy()
        pr.insert(0, "capturado", ahora)
        if _existe(con, "predicciones_modelo"):
            con.execute(f"DELETE FROM predicciones_modelo WHERE substr(capturado,1,10) = ? AND game_id IN "
                        f"({','.join('?' * len(pr))})", [hoy, *pr.game_id])
        pr.to_sql("predicciones_modelo", con, if_exists="append", index=False)
        n["predicciones"] = len(pr)

        # 3) proyecciones de props: una foto por jugador/mercado y por dia
        if props is not None and len(props):
            q = pd.DataFrame({"capturado": ahora, "season": cur, "week": semana, "game_id": props.game_id,
                              "team": props.team, "opp": props.opp, "player_id": props.player_id, "name": props["name"],
                              "position": props.position, "market": props.market, "base": props.base.round(3),
                              "mu": props.mu.round(3), "p25": props.p25, "p50": props.p50, "p75": props.p75,
                              "line_n": props.line_n, "ajuste": props.ajuste.round(4), "estado": props.estado,
                              "p_td": props.p_td.round(4) if "p_td" in props else None})
            if _existe(con, "props_proyecciones"):
                con.execute("DELETE FROM props_proyecciones WHERE season = ? AND week = ? AND substr(capturado,1,10) = ?",
                            (cur, semana, hoy))
            if _existe(con, "props_proyecciones"):
                tiene = {r[1] for r in con.execute("PRAGMA table_info(props_proyecciones)")}
                for c in q.columns:
                    if c not in tiene:
                        con.execute(f'ALTER TABLE props_proyecciones ADD COLUMN "{c}" {_sql_tipo(q[c])}')
            q.to_sql("props_proyecciones", con, if_exists="append", index=False)
            n["props"] = len(q)
        con.execute("CREATE INDEX IF NOT EXISTS idx_props_proy ON props_proyecciones(season, week, player_id)") \
            if _existe(con, "props_proyecciones") else None
        con.execute("CREATE INDEX IF NOT EXISTS idx_pred_game ON predicciones_modelo(game_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_lineas_game ON lineas_historial(game_id)")
        con.commit()
    finally:
        con.close()
    return n


def resumen() -> pd.DataFrame:
    """Una fila por tabla: filas, temporadas y ultima actualizacion."""
    con = _con()
    try:
        filas = []
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            ss = con.execute(f"SELECT MIN(season), MAX(season) FROM {t}").fetchone() if "season" in cols else (None, None)
            u = con.execute("SELECT MAX(descargado) FROM descargas WHERE tabla = ?", (t,)).fetchone()[0]
            if t == "descargas":
                continue
            if u is None:
                u = (con.execute(f"SELECT MAX(capturado) FROM {t}").fetchone()[0] if "capturado" in cols else None)
            filas.append({"tabla": t, "filas": n, "desde": ss[0], "hasta": ss[1], "ultima_actualizacion_UTC": u})
        return pd.DataFrame(filas)
    finally:
        con.close()


def consulta(sql: str) -> pd.DataFrame:
    con = _con()
    try:
        return pd.read_sql(sql, con)
    finally:
        con.close()
