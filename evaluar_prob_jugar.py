"""Repite la validacion de la probabilidad de jugar de los Questionable (necesita internet la primera vez). Abrelo en IDLE y pulsa F5."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_jugar as PJ

print("Error Brier fuera de muestra (menor = mejor):")
print(PJ.evaluar().round(4).to_string(index=False))
