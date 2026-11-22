"""Prepara la pagina web: copia el ultimo reporte a docs/ (lo que se publica en internet).

No borra ni cambia nada de tus carpetas reportes/ o outputs/. Solo agrega:
  docs/index.html            el reporte mas reciente (la direccion principal de la pagina)
  docs/archivo/*.html        copia con fecha de cada corrida (asi un reporte nuevo NO pisa al anterior)
  docs/archivo.html          lista de todos los reportes anteriores
  docs/f/*.js                fragmentos (cada partido, Jugadores, Proyecciones, Calidad, Guía, Gráficas) que la página baja SOLO al abrirlos;
                             el nombre lleva un hash del contenido (si cambia el contenido, cambia el nombre y nadie ve una versión vieja en caché)
Lo llama semana_nfl.py solo al final; tambien puedes correrlo a mano:  python publicar_web.py
"""
from __future__ import annotations

import hashlib
import json
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
            out.append(f"<tr><td>{fuente}</td><td>{nombre}</td><td colspan='2' class='mal'>Sin datos en esta corrida</td></tr>")
            continue
        d, n = ult[tabla]
        try:
            horas = (ahora - datetime.fromisoformat(str(d))).total_seconds() / 3600
        except Exception:
            horas = 0
        color = "ok" if horas <= 30 else "mal"
        edad = "hace unos minutos" if horas < 1 else (f"hace {horas:.0f} h" if horas < 48 else f"hace {horas / 24:.0f} días")
        out.append(f"<tr><td>{fuente}</td><td>{nombre}</td><td>{int(n or 0):,} filas</td><td class='{color}'>{_f_hora(d)} · {edad}</td></tr>")
    return ('<details class="estado box" open><summary><b>Estado de los datos de esta página</b></summary>'
            '<p style="margin:.5em 0">Esta página es una foto del momento en que corrió el modelo: no se actualiza sola al abrirla, '
            'solo cuando corre otra vez. Esto es lo último que descargó cada fuente (hora del servidor que lo corrió, UTC en la nube).</p>'
            '<div class="scroll"><table><thead><tr><th align="left">Fuente</th><th align="left">Qué es</th>'
            '<th align="left">Filas</th><th align="left">Última descarga</th></tr></thead><tbody>' + "".join(out) + "</tbody></table></div></details>")


def _f_hora(d) -> str:
    """«2026-11-18 17:47:10» -> «18/11 17:47 (hora del servidor)»; si no se puede leer, el texto original."""
    try:
        return datetime.fromisoformat(str(d)).strftime("%d/%m %H:%M") + " (hora del servidor)"
    except Exception:
        return str(d)


_FRAG = re.compile(r'<template id="frag-([^"]+)">(.*?)</template>', re.S)


def dividir(texto: str) -> tuple[str, dict[str, str]]:
    """Separa el reporte en un arranque liviano + fragmentos {nombre: html}. El reporte local de reportes/ NO se divide (funciona al abrirlo con doble clic)."""
    frags = {m.group(1): m.group(2) for m in _FRAG.finditer(texto)}
    corto = _FRAG.sub(lambda m: f'<template id="frag-{m.group(1)}" data-src="{{{m.group(1)}}}"></template>', texto)
    return corto, frags


def _guardar_fragmentos(frags: dict[str, str]) -> dict[str, str]:
    """Escribe docs/f/<nombre>.<hash>.js (el hash del contenido evita versiones viejas en caché) y devuelve {nombre: ruta relativa}."""
    carpeta = DOCS / "f"
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = {}
    for nombre, cuerpo in frags.items():
        h = hashlib.sha1(cuerpo.encode("utf-8")).hexdigest()[:10]
        rel = f"f/{nombre}.{h}.js"
        destino = DOCS / rel
        if not destino.exists():
            # .js (no .html): un <script src> SI se carga al abrir docs/index.html con doble clic (file://); un fetch() no.
            destino.write_text("(window.__F=window.__F||{})[" + json.dumps(nombre) + "]=" + json.dumps(cuerpo, ensure_ascii=False) + ";\n", encoding="utf-8")
        rutas[nombre] = rel
    return rutas


def _limpiar_fragmentos() -> int:
    """Borra de docs/f/ los fragmentos que ya no usa ninguna página publicada (index.html ni docs/archivo/*.html)."""
    usados = set()
    for pg in [DOCS / "index.html", *(DOCS / "archivo").glob("*.html")]:
        usados.update(re.findall(r'data-src="(f/[^"]+)"', pg.read_text(encoding="utf-8")))
    n = 0
    for f in [*(DOCS / "f").glob("*.js"), *(DOCS / "f").glob("*.html")]:
        if f"f/{f.name}" not in usados:
            f.unlink()
            n += 1
    return n


def _con_rutas(corto: str, rutas: dict[str, str], base: str) -> str:
    texto = corto
    for nombre, rel in rutas.items():
        texto = texto.replace(f'data-src="{{{nombre}}}"', f'data-src="{rel}"')
    return texto.replace('<meta name="frag-base" content="">', f'<meta name="frag-base" content="{base}">')


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
    texto = ruta.read_text(encoding="utf-8")
    corto, frags = dividir(texto)
    rutas = _guardar_fragmentos(frags)
    # enlace discreto al archivo de reportes anteriores, justo antes del cierre de la pagina
    enlace = ('<p class="foot" style="text-align:center"><a href="archivo.html">'
              'Ver reportes anteriores</a> · generado el ' + datetime.now().strftime("%d/%m/%Y %H:%M") + ' (hora del servidor)</p>')
    enlace = estado_datos() + enlace
    corto = corto.replace("</body>", enlace + "</body>") if "</body>" in corto else corto + enlace
    (DOCS / "index.html").write_text(_con_rutas(corto, rutas, ""), encoding="utf-8")
    copia.write_text(_con_rutas(corto, rutas, "../").replace('href="archivo.html"', 'href="../archivo.html"'), encoding="utf-8")

    filas = []
    for p in sorted((DOCS / "archivo").glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        filas.append(f'<li><a href="archivo/{html.escape(p.name)}">{html.escape(_titulo(p))}</a> '
                     f'<small>{datetime.fromtimestamp(p.stat().st_mtime):%d/%m/%Y %H:%M}</small></li>')
    from ui_css import TOKENS
    (DOCS / "archivo.html").write_text(
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Reportes anteriores</title><style>' + TOKENS + 'body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 var(--font);max-width:640px;margin:2em auto;padding:0 1em}'
        'a{color:var(--accent)}li{margin:.6em 0}small{color:var(--text-2)}</style></head><body><h1>Reportes anteriores</h1>'
        '<p><a href="index.html">← Reporte más reciente</a></p><ul>' + "".join(filas) + "</ul></body></html>", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    borrados = _limpiar_fragmentos()
    print(f"Pagina web : {DOCS / 'index.html'}  (copia con fecha en docs/archivo/; {len(rutas)} fragmentos en docs/f/, {borrados} viejos borrados)")
    return DOCS / "index.html"


if __name__ == "__main__":
    publicar()
