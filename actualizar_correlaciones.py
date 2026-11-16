"""Recalcula correlaciones.json con los partidos jugados hasta hoy (tarda 3-6 minutos). Abrelo en IDLE y pulsa F5."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json

import correlaciones as C
import data as D
import mercado_eval as ME
import props as P
from jugadores_data import FIRST_PLAYER_SEASON, load_player_weeks

games = D.load_schedules(False)
cur = int(games[games.result.notna()].season.max())
pw = load_player_weeks(range(FIRST_PLAYER_SEASON, cur + 1), refresh_seasons=())
X, _, _ = P.construir_X(games, pw)
print("Predicciones fuera de muestra 2021 en adelante ...")
oos = ME.predicciones_oos(X, todas=True)
t = C.estimar(oos, X)
C.RUTA.write_text(json.dumps(t, indent=0))
print(len(t), "correlaciones guardadas en", C.RUTA)
