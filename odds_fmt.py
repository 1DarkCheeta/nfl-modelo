"""Momios en formato DECIMAL para todo lo que ve o escribe el usuario.

Los datos de las casas siguen guardados en americano (-110, +150) en la base de datos y los calculos
internos (probabilidad implicita, devig, ROI) NO cambian; solo se traduce al mostrar y al leer lo que se escribe.
  decimal 1.91  = americano -110 :  apuestas 1 y recibes 1.91 en total (ganancia 0.91)
"""
import math


def a_dec(a) -> float:
    """Americano -> decimal (nan si no es valido)."""
    try:
        a = float(a)
    except (TypeError, ValueError):
        return float("nan")
    if math.isnan(a) or a == 0 or -100 < a < 100:
        return float("nan")
    return 1 + a / 100 if a > 0 else 1 + 100 / (-a)


def fd(a) -> str:
    """Americano -> texto decimal con 2 decimales ('1.91'); '—' si no hay dato."""
    d = a_dec(a)
    return "—" if math.isnan(d) else f"{d:.2f}"


def dec_justo(p: float) -> float:
    """Cuota decimal justa (sin comision) de una probabilidad p."""
    return 1.0 / min(max(float(p), 0.01), 0.99)


def fdj(p: float) -> str:
    return f"{dec_justo(p):.2f}"
