"""Baja el historial de precios de Kalshi (puede tardar; se puede interrumpir y volver a correr: reanuda).
Abrelo en IDLE y pulsa F5. Cambia MINUTOS para limitar cuanto trabaja cada vez."""
MINUTOS = 60
SOLO_MERCADOS = False

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalshi_historial as KH

print("Lista de mercados liquidados de Kalshi ...")
print("  total:", KH.bajar_mercados())
if not SOLO_MERCADOS:
    print("Velas por hora (precio antes del partido) ...")
    print(KH.bajar_velas(max_minutos=MINUTOS))
print("Listo. Datos en data/kalshi_hist.db")
