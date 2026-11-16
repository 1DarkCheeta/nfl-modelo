"""
 BASE DE DATOS NFL  -  abre este archivo en IDLE y pulsa F5.

 Hace dos cosas:
   1. (Opcional) Actualiza la base de datos data/nfl.db con lo ultimo de nflverse.
   2. Muestra que contiene y ejecuta la consulta SQL que escribas abajo (y la guarda en outputs/consulta.csv).

 Tambien puedes abrir data/nfl.db con "DB Browser for SQLite" (gratis) o con cualquier programa de SQL.
"""
ACTUALIZAR = True      # True = descarga lo nuevo antes de consultar; False = solo consultar

# Escribe aqui tu consulta (SQL). Ejemplos al final del archivo y en el README.
CONSULTA = """
SELECT name AS jugador, team AS equipo, position AS pos, partidos,
       targets_por_partido, recepciones, pct_atrapadas, yardas_recepcion_por_partido
FROM v_jugador_temporada
WHERE season = (SELECT MAX(season) FROM games WHERE result IS NOT NULL)
  AND position IN ('WR', 'TE') AND partidos >= 4
ORDER BY targets_por_partido DESC
LIMIT 15
"""

import sys
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))


def actualizar():
    from data import FIRST_SEASON, load_schedules, load_team_games
    from jugadores_data import FIRST_PLAYER_SEASON, load_depth, load_injuries, load_player_weeks
    from matchups_data import load_matchup_games

    print("Actualizando la base de datos (la primera vez tarda 1-2 minutos)...")
    g = load_schedules(refresh=True)
    cur = int(g.loc[g.result.notna(), "season"].max())
    load_team_games(range(FIRST_SEASON, cur + 1), refresh_seasons=(cur,))
    load_player_weeks(range(FIRST_PLAYER_SEASON, cur + 1), refresh_seasons=(cur,))
    load_injuries(cur, True)
    load_depth(cur, True)
    load_matchup_games([cur - 1, cur], refresh_seasons=(cur,))


def main():
    import pandas as pd
    import db

    if ACTUALIZAR:
        try:
            actualizar()
        except Exception as e:
            print(f"\nNo pude actualizar ({e}). Uso lo que ya esta guardado.")
    pd.set_option("display.width", 220, "display.max_columns", 40, "display.max_rows", 200)
    print("\nContenido de la base:\n")
    print(db.resumen().to_string(index=False))
    print("\nConsulta:\n" + CONSULTA.strip() + "\n")
    t = db.consulta(CONSULTA)
    print(t.to_string(index=False) if len(t) else "(sin resultados)")
    out = AQUI / "outputs" / "consulta.csv"
    out.parent.mkdir(exist_ok=True)
    t.to_csv(out, index=False)
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n*** Ocurrio un error. Copia el texto de abajo si necesitas ayuda ***\n")
        traceback.print_exc()

# ---------------------------------------------------------------------------------------------
# EJEMPLOS (copia uno dentro de CONSULTA):
#
# Defensas que mas yardas por aire permiten esta temporada:
#   SELECT defensa, partidos, yardas_aire_por_partido, yardas_tierra_por_partido
#   FROM v_defensa_permite WHERE season = 2026 ORDER BY yardas_aire_por_partido DESC
#
# Movimiento de la linea de un partido (cada vez que cambio entre ejecuciones):
#   SELECT capturado, away_team, home_team, spread_line, total_line, home_moneyline
#   FROM lineas_historial WHERE week = 9 ORDER BY game_id, capturado
#
# Que tan bien acertaron las proyecciones de props (se llena sola cuando se juegan los partidos):
#   SELECT * FROM v_props_precision
#
# Modelo vs mercado en partidos ya jugados:
#   SELECT * FROM v_equipos_resultados ORDER BY week
# ---------------------------------------------------------------------------------------------
