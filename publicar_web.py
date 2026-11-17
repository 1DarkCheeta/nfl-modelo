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


FUENTES = [  # (tabla en la base de datos, nombre que se muestra, de donde viene)
    ("games", "Calendario, resultados y líneas", "nflverse"),
    ("team_games", "Jugadas (EPA por equipo)", "nflverse"),
    ("player_weeks", "Estadísticas de jugadores", "nflverse"),
    ("injuries", "Lesiones (reporte oficial)", "nflverse"),
    ("lesiones_espn", "Lesiones y notas", "ESPN"),
    ("depth", "Depth chart", "nflverse"),
    ("ourlads_depth", "Depth chart y titulares", "Ourlads"),
    ("rbsdm_team_tiers", "EPA, éxito y tendencias por equipo", "rbsdm"),
    ("snaps", "Jugadas por jugador (snaps)", "nflverse"),
    ("lineas_kalshi", "Líneas de props", "Kalshi"),
    ("clima_pronostico", "Pronóstico del clima por estadio", "Open-Meteo"),
]


def estado_datos() -> str:
    """Tabla con la ultima descarga de cada fuente (leida de la base de datos), para ver de un vistazo si algo no se actualizo."""
    import sqlite3
    try:
        con = sqlite3.connect(AQUI / "data" / "nfl.db")
        filas = con.execute("SELECT tabla, MAX(descargado), SUM(filas) FROM (SELECT tabla, descargado, filas FROM descargas "
                            "WHERE descargado = (SELECT MAX(d2.descargado) FROM descargas d2 WHERE d2.tabla = descargas.tabla)) GROUP BY tabla").fetchall()
        con.close()
    except Exception:
        return ""
    ult = {t: (d, n) for t, d, n in filas}
    ahora = datetime.now()
    out = []
    for tabla, nombre, fuente in FUENTES:
        if tabla not in ult:
            out.append(f"<tr><td>{fuente}</td><td>{nombre}</td><td colspan='2' style='color:#b3261e'>Sin datos en esta corrida</td></tr>")
            continue
        d, n = ult[tabla]
        try:
            horas = (ahora - datetime.fromisoformat(str(d))).total_seconds() / 3600
        except Exception:
            horas = 0
        color = "#0a7d3c" if horas <= 30 else "#b3261e"
        edad = "hace unos minutos" if horas < 1 else (f"hace {horas:.0f} h" if horas < 48 else f"hace {horas / 24:.0f} días")
        out.append(f"<tr><td>{fuente}</td><td>{nombre}</td><td>{int(n or 0):,} filas</td><td style='color:{color}'>{d} · {edad}</td></tr>")
    return ('<details style="max-width:900px;margin:1.5em auto;font:14px system-ui" open><summary><b>Estado de los datos de esta página</b></summary>'
            '<p style="margin:.5em 0">Esta página es una foto del momento en que corrió el modelo: no se actualiza sola al abrirla, '
            'solo cuando corre otra vez. Esto es lo último que descargó cada fuente (hora del servidor que lo corrió, UTC en la nube).</p>'
            '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%"><thead><tr><th align="left">Fuente</th><th align="left">Qué es</th>'
            '<th align="left">Filas</th><th align="left">Última descarga</th></tr></thead><tbody>' + "".join(out) + "</tbody></table></div></details>")


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
              'Ver reportes anteriores</a> · generado el ' + datetime.now().strftime("%d/%m/%Y %H:%M") + ' (hora del servidor)</p>')
    enlace = estado_datos() + enlace
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
