"""Barra horizontal verde/rojo con línea vertical de corte (solo presentación: recibe números ya calculados).

verde = lado positivo (probabilidad del modelo, favorito, acierto); rojo = contraparte (100 - verde);
línea de corte = probabilidad implícita del mercado/cuota o el umbral de referencia.
El significado NUNCA va solo en el color: lleva etiquetas con el número y un texto («por encima / por debajo del corte»).
"""
import html


def _e(x) -> str:
    return html.escape(str(x))


def barra(p: float, corte: float | None = None, pos: str = "Modelo", neg: str = "Lado contrario", corte_txt: str = "Corte del mercado",
          diff: float | None = None, claro: bool = False) -> str:
    """p y corte en % (0-100). diff = ventaja en puntos ya calculada por el modelo (si no se da, p - corte).
    claro=True: sin la línea de texto del corte (para espacios muy chicos)."""
    p = max(0.0, min(100.0, float(p)))
    n = 100.0 - p
    cut_html, linea, aria_c = "", "", ""
    if corte is not None and corte == corte:
        c = max(0.0, min(100.0, float(corte)))
        d = (p - c) if diff is None else float(diff)
        ok = d >= 0
        cut_html = f'<i class="pcut-cut" style="left:{c:.1f}%" aria-hidden="true"></i>'
        veces = "por encima del corte" if ok else "por debajo del corte"
        linea = (f'<div class="pcut-lab"><span class="cut {"ok" if ok else "no"}">{_e(corte_txt)} <b>{c:.0f}%</b> · '
                 f'<b>{d:+.1f} pts</b> {veces}</span></div>') if not claro else ""
        aria_c = f". {corte_txt} {c:.0f}%: {abs(d):.1f} puntos {veces}"
    aria = f"{pos} {p:.0f}%; {neg} {n:.0f}%{aria_c}"
    return (f'<div class="pcut" role="img" aria-label="{_e(aria)}">'
            f'<div class="pcut-lab top"><span class="pos">{_e(pos)} {p:.0f}%</span><span class="neg">{_e(neg)} {n:.0f}%</span></div>'
            f'<div class="pcut-track" aria-hidden="true"><span class="pcut-pos" style="flex:0 0 calc({p:.1f}% - 1px)"></span>'
            f'<span class="pcut-neg"></span>{cut_html}</div>{linea}</div>')
