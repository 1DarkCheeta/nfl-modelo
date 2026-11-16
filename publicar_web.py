"""Prepara la pagina web: copia el ultimo reporte a docs/ (lo que se publica en internet).

No borra ni cambia nada de tus carpetas reportes/ o outputs/. Solo agrega:
  docs/index.html            el reporte mas reciente (la direccion principal de la pagina)
  docs/archivo/*.html        copia con fecha de cada corrida (asi un reporte nuevo NO pisa al anterior)
  docs/archivo.html          lista de todos los reportes anteriores
Lo llama semana_nfl.py solo al final; tambien puedes correrlo a mano:  python publicar_web.py
"""
from __future__ import annotations

import html
import re
import shutil
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DOCS = AQUI / "docs"


def _titulo(ruta: Path) -> str:
    m = re.search(r"reporte_(\d{4})_semana(\d+)", ruta.name)
    return f"Temporada {m.group(1)} · semana {int(m.group(2))}" if m else ruta.stem


def publicar(ruta: Path | None = None) -> Path:
    if ruta is None:                                   # el reporte mas reciente de la carpeta reportes/
        cand = sorted((AQUI / "reportes").glob("reporte_*.html"), key=lambda p: p.stat().st_mtime)
        if not cand:
            raise FileNotFoundError("No hay reportes en la carpeta reportes/. Corre primero semana_nfl.py.")
        ruta = cand[-1]
    ruta = Path(ruta)
    (DOCS / "archivo").mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    copia = DOCS / "archivo" / f"{ruta.stem}_{sello}.html"
    shutil.copyfile(ruta, copia)
    texto = ruta.read_text(encoding="utf-8")
    # enlace discreto al archivo de reportes anteriores, justo antes del cierre de la pagina
    enlace = ('<p style="text-align:center;font:14px system-ui;margin:2em 0"><a href="archivo.html">'
              'Ver reportes anteriores</a> · generado el ' + datetime.now().strftime("%d/%m/%Y %H:%M") + ' (UTC en la nube)</p>')
    texto = texto.replace("</body>", enlace + "</body>") if "</body>" in texto else texto + enlace
    (DOCS / "index.html").write_text(texto, encoding="utf-8")

    filas = []
    for p in sorted((DOCS / "archivo").glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        filas.append(f'<li><a href="archivo/{html.escape(p.name)}">{html.escape(_titulo(p))}</a> '
                     f'<small>{datetime.fromtimestamp(p.stat().st_mtime):%d/%m/%Y %H:%M}</small></li>')
    (DOCS / "archivo.html").write_text(
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Reportes anteriores</title><style>body{font:16px/1.6 system-ui;max-width:640px;margin:2em auto;padding:0 1em}'
        'li{margin:.5em 0}small{color:#777}</style></head><body><h1>Reportes anteriores</h1>'
        '<p><a href="index.html">← Reporte más reciente</a></p><ul>' + "".join(filas) + "</ul></body></html>", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print(f"Pagina web : {DOCS / 'index.html'}  (copia con fecha en docs/archivo/)")
    return DOCS / "index.html"


if __name__ == "__main__":
    publicar()
