"""Diseno de la pagina: pestanas, resumen por partido, vista de un partido a la vez, texto plegable y avisos de frescura.

NO calcula nada: solo acomoda el HTML que ya generan reporte.py, puntos.py, reporte_extra.py, por_equipo.py, elo.py, marcador.py y qb.py.
Todas las calculadoras (linea editable de totales / equipos / combinadas, props, touchdowns, combinada de jugadores, cuotas) siguen siendo las
mismas: escuchan eventos a nivel de documento, asi que funcionan igual aunque su bloque este en otra pestana o dentro de un desplegable.

Estructura
  Esta semana           resumen de valor, una fila por partido (con avisos), mariscales, graficas
  Partidos              selector de partido; cada partido con 4 sub-pestanas: Apuestas / Puntos y combinadas / Props y TD / Matchup
  Equipos y jugadores   equipo por equipo, Elo, touchdowns, Kalshi, props destacados
  Calidad               marcador, confianza en los porcentajes, historial y glosario

Si algo falla al armar este diseno, reporte.py usa el diseno anterior (una sola pagina larga).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

import clima as CL

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
POS_PROPS = ("QB", "RB", "WR", "TE")
UTC_CDMX = timedelta(hours=-6)          # Ciudad de Mexico no cambia de horario


def _esc(x) -> str:
    return html.escape(str(x))


# ------------------------------------------------------------------------------------------ datos de cada partido
def _kickoff(games: pd.DataFrame, gid: str):
    try:
        f = games[games.game_id == gid].iloc[0]
        return CL.kickoff_utc(f.gameday, f.gametime)
    except Exception:
        return None


def _cuando(ko) -> str:
    if ko is None:
        return ""
    l = (ko + UTC_CDMX)
    return f"{DIAS[l.weekday()]} {l.day} {MESES[l.month - 1]} · {l:%H:%M} CDMX"


def _corto(ko) -> str:
    if ko is None:
        return ""
    l = (ko + UTC_CDMX)
    return f"{DIAS[l.weekday()]} {l.day}"


def _badges(gid: str, x, g: dict | None, c: dict) -> list[tuple[str, str, str]]:
    """Lista de (clase, texto, ayuda). clase: v = valor, w = aviso, n = neutral."""
    out = []
    me = c["me"]
    if x is not None:
        lados = []
        for k, t in (("sp", "Spread"), ("to", "Total"), ("ml", "Moneyline")):
            if k == "ml" and not x.tiene_ml:
                continue
            if x[f"{k}_edge"] >= me:
                lados.append(f"{t}: {x[f'{k}_lado']} ({x[f'{k}_edge'] * 100:+.1f} pts)")
        if lados:
            out.append(("v", "✔ posible valor", "; ".join(lados)))
    a = (c.get("qb") or {}).get(gid)
    if a:
        est = [a[l]["estado"] for l in ("home", "away")]
        if "cambio" in est:
            out.append(("w", "🏈 QB distinto", " ".join(a["avisos"])))
        elif "duda" in est:
            out.append(("w", "🏈 QB en duda", " ".join(a["avisos"])))
        elif "regresa" in est:
            out.append(("n", "🏈 regresa QB", " ".join(a["avisos"])))
    mj = (c.get("mov_juego") or {}).get(gid)
    if mj:
        out.append(("n", "🔁 fichajes", mj))
    v = (c.get("clima") or {}).get(gid)
    if v and v.get("estado") == "ok" and v.get("interior") is not True:
        w, t, pp = v.get("viento_mph"), v.get("temp_f"), v.get("prob_precip")
        if w is not None and w >= CL.VIENTO_FUERTE:
            out.append(("w", f"💨 {w:.0f} mph", "viento fuerte pronosticado"))
        if t is not None and t <= CL.FRIO:
            out.append(("w", f"🥶 {(t - 32) * 5 / 9:.0f} °C", "frío"))
        if pp is not None and pp >= 50:
            out.append(("w", f"💧 {pp:.0f} %", "probabilidad de lluvia o nieve"))
    ex = c.get("excl")
    if ex is not None and len(ex) and g:
        e = ex[ex.team.isin([g["home"], g["away"]]) & ex.position.isin(POS_PROPS)]
        if len(e):
            nom = "; ".join(f"{r.name} ({r.position}, {'baja' if r.estado == 'Out' else 'dudoso'})" for r in e.itertuples())
            out.append(("n", f"🩹 {len(e)}", "Jugadores con proyección fuera o dudosos: " + nom))
    return out


def _badges_html(bs, iconos: bool = False) -> str:
    if not bs:
        return ""
    if iconos:
        return "".join(f'<i class="bdi {c}" title="{_esc(a)}">{_esc(t.split(" ")[0])}</i>' for c, t, a in bs)
    return "".join(f'<span class="bd bd-{c}" title="{_esc(a)}">{_esc(t)}</span>' for c, t, a in bs)


def juegos(c: dict) -> list[dict]:
    """Un diccionario por partido (semana en curso y siguiente), ordenado por kickoff."""
    PT, res, games, nm = c.get("PT"), c["res"], c["games"], c["nm"]
    info: dict = {}
    if PT:
        for g in PT["juegos"]:
            info[g["id"]] = {"id": g["id"], "away": g["away"], "home": g["home"], "pt": g}
    rx = {}
    for _, x in res.iterrows():
        rx[x.game_id] = x
        info.setdefault(x.game_id, {"id": x.game_id, "away": x.away_team, "home": x.home_team, "pt": None})
    out = []
    for gid, d in info.items():
        d["x"] = rx.get(gid)
        d["ko"] = _kickoff(games, gid)
        d["bd"] = _badges(gid, d["x"], d, c)
        out.append(d)
    out.sort(key=lambda d: (d["ko"] is None, d["ko"] if d["ko"] is not None else 0, d["id"]))
    return out


# ------------------------------------------------------------------------------------------ piezas de HTML
def _fila(d: dict, nm) -> str:
    x, g = d["x"], d["pt"]
    h, a = d["home"], d["away"]
    nums = []
    if x is not None:
        pl = x.p_gana_local * 100
        fav, pf = (h, pl) if pl >= 50 else (a, 100 - pl)
        mk = x.p_gana_local_mercado * 100
        mk_txt = f' <small>(mercado {(mk if pl >= 50 else 100 - mk):.0f}%)</small>' if pd.notna(mk) else ""
        nums.append(f'<span>Modelo: <b>{_esc(fav)} {pf:.0f}%</b>{mk_txt}</span>')
        nums.append(f'<span>Línea: <b>{_esc(h)} {x.linea_local:+g}</b> · total <b>{x.total_line:g}</b></span>')
    elif g is not None:
        m = g["m"]
        nums.append(f'<span>Modelo: <b>{_esc(h if m >= 0 else a)}</b> por {abs(m):.1f}</span>')
        if g["mercado"]:
            nums.append(f'<span>Línea: <b>{_esc(h)} {-g["spread"]:+g}</b> · total <b>{g["lt"]:g}</b></span>')
        else:
            nums.append("<span>Sin línea todavía</span>")
    if g is not None:
        nums.append(f'<span class="gr-sc">Marcador esperado: {_esc(a)} {g["a"]:.0f} – {g["h"]:.0f} {_esc(h)}</span>')
    ko = d["ko"].isoformat() if d["ko"] is not None else ""
    return (f'<article class="grow" data-g="{_esc(d["id"])}" data-ko="{ko}" data-match="{_esc(a)} @ {_esc(h)}">'
            f'<div class="gr-top"><span class="gr-when">{_esc(_cuando(d["ko"]))}</span><span class="gr-bd">{_badges_html(d["bd"])}</span></div>'
            f'<div class="gr-main"><b>{_esc(nm(a))} @ {_esc(nm(h))}</b></div>'
            f'<div class="gr-nums">{"".join(nums)}</div>'
            f'<button type="button" class="gr-go" data-go="{_esc(d["id"])}">Ver partido →</button></article>')


def resumen_partidos(js_: list[dict], nm) -> str:
    if not js_:
        return ""
    filas = "".join(_fila(d, nm) for d in js_)
    return ('<h2 id="partidos-sem">Los partidos de un vistazo</h2>'
            '<p class="leyenda">✔ posible valor · 🏈 mariscal distinto o en duda · 💨 viento fuerte · 🥶 frío · 💧 lluvia o nieve probable · '
            '🩹 jugadores con proyección fuera o dudosos. Toca un partido para ver todo su detalle y editar tus líneas.</p>'
            f'<div class="grows">{filas}</div>')


def _selector(js_: list[dict]) -> str:
    chips = []
    for d in js_:
        chips.append(f'<button type="button" class="gchip" data-g="{_esc(d["id"])}"><b>{_esc(d["away"])} @ {_esc(d["home"])}</b>'
                     f'<small>{_esc(_corto(d["ko"]))}</small><span class="gc-i">{_badges_html(d["bd"], True)}</span></button>')
    return ('<div class="gsel" id="gsel"><div class="gsel-in">' + "".join(chips) +
            '</div><button type="button" class="gall" id="gall">Mostrar todos</button></div>')


def _panel(d: dict, nm, card_apuestas: str, extra: dict, card_puntos: str) -> str:
    """Panel de un partido con sub-pestanas. extra: matchup / td / casas / props (html)."""
    gid = d["id"]
    sub = []
    if card_apuestas or extra.get("casas"):
        sub.append(("ap", "Apuestas", card_apuestas + extra.get("casas", "")))
    if card_puntos:
        sub.append(("pt", "Puntos y combinadas", card_puntos))
    if extra.get("td") or extra.get("props"):
        sub.append(("pr", "Props y TD", extra.get("td", "") + extra.get("props", "")))
    if extra.get("matchup"):
        sub.append(("mu", "Matchup", extra["matchup"]))
    if not sub:
        sub = [("ap", "Apuestas", '<div class="box">Todavía no hay datos de este partido.</div>')]
    botones = "".join(f'<button type="button" class="sbtn" data-s="{k}">{t}</button>' for k, t, _ in sub)
    cuerpos = "".join(f'<div class="sp" data-s="{k}">{h}</div>' for k, _, h in sub)
    nota = ""
    if not card_apuestas:
        nota = ('<p class="leyenda">Este partido es de la semana siguiente: por ahora solo tiene el over/under de puntos y las combinadas. '
                'Las apuestas contra el mercado, los props y los matchups aparecen cuando entra a la semana en curso.</p>')
    return (f'<section class="gpanel" data-g="{_esc(gid)}">'
            f'<div class="gp-head"><h3>{_esc(nm(d["away"]))} @ {_esc(nm(d["home"]))}</h3><span class="gp-when">{_esc(_cuando(d["ko"]))}</span>'
            f'<div class="gp-bd">{_badges_html(d["bd"])}</div></div>{nota}'
            f'<div class="sseg">{botones}</div>{cuerpos}</section>')


def _sin_numeros(h: str) -> str:
    """Quita la numeracion «4. », «5. » de los titulos (ya no van en orden al estar en pestanas)."""
    return re.sub(r"(<h2[^>]*>)\s*\d+\.\s+", r"\1", h)


def _subnav(items) -> str:
    return '<nav class="subnav">' + "".join(f'<a href="#{i}">{_esc(t)}</a>' for i, t, ok in items if ok) + "</nav>"


# ------------------------------------------------------------------------------------------ ensamblado
def armar(c: dict) -> str:
    """HTML del <main>. c: ver reporte.construir (claves: cur, wk, n, sub, generado_iso, resumen, importante, graficas, ayuda, cred, hist_html,
    sec_*, ex_parts, cards_ap, PT, pt_partes, res, games, qb, clima, excl, me, nm)."""
    nm = c["nm"]
    js_ = juegos(c)
    pp = c.get("pt_partes") or {}
    cards_pt = pp.get("cards", {})
    paneles = "".join(_panel(d, nm, c["cards_ap"].get(d["id"], ""), c["ex_parts"].get(d["id"], {}), cards_pt.get(d["id"], "")) for d in js_)
    intro_pt = re.sub(r"^<h2[^>]*>.*?</h2>", "", pp.get("intro", ""), count=1, flags=re.S)
    como = (f'<details class="exp" id="puntos"><summary>Cómo funcionan el over/under, el clima y las combinadas</summary>{intro_pt}</details>' if intro_pt else "")
    n_al = sum(1 for d in js_ if any(b[0] == "w" for b in d["bd"]))

    it1 = [("sem-resumen", "Resumen", True), ("sem-vistazo", "Partidos de un vistazo", True), ("qb", "Mariscales", bool(c.get("sec_qb"))),
           ("movimientos", "Movimientos", bool(c.get("sec_mov"))), ("graficas", "Gráficas", True)]
    sub1 = _subnav(it1)
    t1 = (f'{sub1}<span id="sem-resumen"></span>{c["resumen"]}{c["importante"]}<span id="sem-vistazo"></span>{resumen_partidos(js_, nm)}'
          f'{c.get("sec_qb", "")}{c.get("sec_mov", "")}'
          f'<details class="sec" id="graficas"><span id="equipos"></span><summary>Gráficas de la semana: margen esperado, probabilidad de ganar y ventajas</summary>{c["graficas"]}</details>')
    t2 = ('<h2 id="partidos">Partido por partido</h2>'
          '<p class="leyenda">Elige un partido y mira, en sub-pestañas: las apuestas contra el mercado, '
          'el over/under de puntos con tus propias líneas y las combinadas, los props y touchdowns de jugadores y el matchup.</p>'
          f'{como}{_selector(js_)}<div class="gpanels" id="pgrid">{paneles}</div>{pp.get("datos", "")}')
    it3 = [("explorador", "LINEA AC", bool(c.get("sec_jug"))), ("porequipo", "Equipo por equipo", bool(c.get("sec_eq"))), ("elo", "Elo", bool(c.get("sec_elo"))),
           ("td", "Touchdowns", bool(c.get("sec_td"))), ("casas", "Kalshi", bool(c.get("sec_casas"))), ("props", "Props destacados", bool(c.get("sec_top")))]
    sub3 = _subnav(it3)
    t3 = sub3 + c.get("sec_jug", "") + c.get("sec_eq", "") + c.get("sec_elo", "") + c.get("sec_td", "") + c.get("sec_casas", "") + c.get("sec_top", "")
    if not (c.get("sec_eq") or c.get("sec_elo") or c.get("sec_jug") or c.get("sec_td") or c.get("sec_casas") or c.get("sec_top")):
        t3 = '<div class="box">Esta pestaña se llena cuando el reporte incluye jugadores y props (corre el programa completo).</div>'
    it4 = [("record", "Récord de elecciones", bool(c.get("sec_mc"))), ("marcador", "Marcador", bool(c.get("sec_mc"))), ("confianza", "Confianza", bool(c.get("cred"))), ("fiab-props", "Props y TD", bool(c.get("sec_cal"))),
           ("historial", "Historial", True), ("ayuda", "Cómo leer", True)]
    sub4 = _subnav(it4)
    t4 = (sub4 + c.get("sec_mc", "") + (f'<div id="confianza">{c["cred"]}</div>' if c.get("cred") else "") + c.get("sec_cal", "") +
          f'<h2 id="historial">Cómo le fue en semanas anteriores</h2>{c["hist_html"]}'
          f'<h2 id="ayuda">Cómo leer este reporte</h2>{c["ayuda"]}')
    t5 = (c["sec_proy"] if c.get("sec_proy") else '<div class="box">Esta pestaña se llena cuando el reporte incluye jugadores (corre el programa completo).</div>')
    tabs = [("tab-semana", f"Esta semana", t1), ("tab-partidos", f"Partidos ({len(js_)})", t2), ("tab-jugadores", "Equipos y jugadores", t3), ("tab-proyecciones", "PROYECCIONES", t5), ("tab-calidad", "Calidad", t4)]
    it2 = [("partidos", "Partido por partido", True), ("puntos", "Over/under, clima y combinadas (cómo funciona)", bool(intro_pt))]
    grupos = [(tabs[0][1], it1), (tabs[1][1], it2), (tabs[2][1], it3), (tabs[3][1], [("proyecciones", "Cruce ofensiva vs defensa", bool(c.get("sec_proy"))), ("proy-of", "Ofensivas: cuánto produce cada una", bool(c.get("sec_proy"))), ("proy-de", "Defensas: cuánto permite cada una", bool(c.get("sec_proy")))]), (tabs[4][1], it4)]
    todo = "".join(f'<div class="am-g"><div class="am-t">{_esc(t)}</div>' + "".join(f'<a href="#{i}">{_esc(x)}</a>' for i, x, ok in its if ok) + "</div>" for t, its in grupos)
    barra = ('<button type="button" class="menubtn" id="menubtn" aria-haspopup="true" aria-expanded="false" aria-controls="allmenu">☰ Todo</button>'
             + "".join(f'<button type="button" class="tabbtn" data-t="{i}">{_esc(t)}</button>' for i, t, _ in tabs))
    cuerpo = "".join(f'<div class="tab" id="{i}">{_sin_numeros(h)}</div>' for i, _, h in tabs)
    return f"""<main>
<script>document.documentElement.classList.add('js')</script>
<header class="top"><h1 id="resumen">NFL · Temporada {c["cur"]}, semana {c["wk"]}</h1>
<p class="sub">{c["sub"]} <span id="fresh" class="fresh" data-gen="{c["generado_iso"]}"></span></p></header>
<nav class="tabs" id="tabs" role="tablist">{barra}</nav>
<div id="allmenu" class="allmenu" hidden>{todo}</div>
{cuerpo}
<p class="foot">Datos: nflverse (play-by-play y líneas), ESPN, Ourlads, rbsdm, Kalshi y Open-Meteo. Los porcentajes salen de un modelo estadístico simple y no son garantía de nada.</p>
<button type="button" id="arriba" class="arriba" title="Volver arriba" aria-label="Volver arriba">↑</button>
</main>"""


CSS = """
.top h1{margin-bottom:.1em}.fresh{display:inline-block;border-radius:999px;padding:1px 10px;font-size:.8rem;background:var(--no);color:var(--ink2);white-space:nowrap}
.fresh.viejo{background:#fde7c8;color:#7a3d00;font-weight:600}
.tabs{position:sticky;top:0;z-index:40;display:flex;gap:8px;overflow-x:auto;background:var(--bg);padding:8px 2px;margin:10px 0 14px;border-bottom:1px solid var(--line);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabbtn{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:8px 15px;font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
.tabbtn.on{background:var(--blue);border-color:var(--blue);color:#fff}
.menubtn{flex:0 0 auto;border:1px solid var(--blue);background:transparent;color:var(--blue);border-radius:999px;padding:8px 14px;font:inherit;font-weight:700;cursor:pointer;white-space:nowrap}
.menubtn[aria-expanded=true]{background:var(--blue);color:#fff}
.allmenu{position:fixed;left:8px;right:8px;top:calc(var(--tabh,56px) + 4px);z-index:60;max-height:calc(100vh - var(--tabh,56px) - 20px);overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 28px rgba(0,0,0,.35);padding:10px 12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px 16px;max-width:900px;margin:0 auto}
.allmenu[hidden]{display:none}
.am-t{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);margin:2px 0 4px}
.am-g a{display:block;padding:7px 10px;border-radius:8px;color:var(--ink);text-decoration:none;font-size:.92rem}.am-g a:hover,.am-g a:focus{background:var(--bg)}
html.js .tab{display:none}html.js .tab.on{display:block}
.subnav{display:flex;gap:8px;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;position:sticky;top:var(--tabh,56px);z-index:35;background:var(--bg);padding:6px 0;margin:0 0 8px;border-bottom:1px solid var(--line)}.subnav::-webkit-scrollbar{display:none}.subnav a{flex:0 0 auto;white-space:nowrap}.tab [id]{scroll-margin-top:calc(var(--tabh,56px) + 54px)}.subnav a{font-size:.85rem;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:4px 11px;color:var(--ink);text-decoration:none}
.leyenda{color:var(--ink2);font-size:.85rem;margin:.2em 0 .8em}
.grows{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.grow{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:5px}
.gr-top{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center}.gr-when{font-size:.8rem;color:var(--ink2)}.gr-main{font-size:1rem}
.gr-nums{display:flex;flex-direction:column;gap:2px;font-size:.88rem}.gr-nums small{color:var(--ink2)}.gr-sc{color:var(--ink2);font-size:.8rem}
.gr-go{align-self:flex-start;margin-top:4px;border:1px solid var(--blue);background:transparent;color:var(--blue);border-radius:8px;padding:6px 12px;font:inherit;font-weight:600;cursor:pointer}
.gr-bd,.gp-bd{display:flex;gap:5px;flex-wrap:wrap}
.bd{border-radius:999px;padding:2px 9px;font-size:.76rem;white-space:nowrap;background:var(--no);color:var(--ink2)}
.bd-v{background:var(--yes);color:var(--yesink);font-weight:600}.bd-w{background:#fde7c8;color:#7a3d00;font-weight:600}
@media (prefers-color-scheme:dark){.bd-w{background:#4a3315;color:#ffd9a0}.fresh.viejo{background:#4a3315;color:#ffd9a0}}
.gsel{position:sticky;top:var(--tabh,56px);z-index:30;background:var(--bg);display:flex;gap:8px;align-items:center;padding:6px 0 8px;border-bottom:1px solid var(--line);margin:10px 0}
.gsel-in{display:flex;gap:6px;overflow-x:auto;flex:1;scrollbar-width:thin;padding-bottom:2px}
.gchip{flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-start;gap:1px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;padding:5px 10px;font:inherit;font-size:.82rem;cursor:pointer;min-width:84px}
.gchip small{color:var(--ink2);font-size:.7rem}.gchip.on{border-color:var(--blue);box-shadow:inset 0 0 0 1px var(--blue);background:rgba(42,120,214,.10)}
.gc-i{display:flex;gap:2px;min-height:1em}.bdi{font-style:normal;font-size:.75rem}
.gall{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 10px;font:inherit;font-size:.8rem;cursor:pointer}.gall.on{background:var(--blue);color:#fff;border-color:var(--blue)}
html.js .gpanel{display:none}html.js .gpanel.on,html.js .gpanels.todos .gpanel{display:block}
.gpanel{margin:8px 0 22px}html.js .gpanels.todos .gpanel{border-top:3px solid var(--line);padding-top:10px}
.gp-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;margin-bottom:6px}.gp-head h3{font-size:1.2rem}.gp-when{color:var(--ink2);font-size:.88rem}
.sseg{display:flex;gap:6px;overflow-x:auto;margin:8px 0;scrollbar-width:none}.sseg::-webkit-scrollbar{display:none}
.sbtn{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:7px 12px;font:inherit;font-size:.88rem;cursor:pointer;white-space:nowrap}
.sbtn.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
html.js .sp{display:none}html.js .sp.on{display:block}
.gpanel .card>header,.gpanel .pjuego>h3{display:none}.gpanel .pjuego,.gpanel .card{margin-top:0}
details.exp,details.sec{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}
details.exp>summary,details.sec>summary{cursor:pointer;font-weight:600;color:var(--ink2);font-size:.9rem}details.sec>summary{color:var(--ink);font-size:1rem}
details.exp[open]>summary,details.sec[open]>summary{margin-bottom:8px}
.arriba{position:fixed;right:14px;bottom:16px;z-index:45;width:40px;height:40px;border-radius:50%;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:1.1rem;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s;box-shadow:0 2px 8px rgba(0,0,0,.2)}
.arriba.on{opacity:.9;pointer-events:auto}
.scroll.ov table th:first-child,.scroll.ov table td:first-child{position:sticky;left:0;background:var(--card);z-index:1;box-shadow:2px 0 3px -2px rgba(0,0,0,.25)}
@media (max-width:700px){
 main{padding:14px 10px 64px}h1{font-size:1.4rem}.grows{grid-template-columns:1fr}.tabbtn{padding:9px 14px}
 button,.pbtn,.sbtn,.gr-go,.gall{min-height:38px}input[type=number],input[type=text],input.lin,input.cuo,input.cuu,input.cutd,input.elin{font-size:16px;min-height:34px}
 .gchip{min-width:76px}
}
@media (pointer:coarse){.pmas,.pmenos,.preset,.creset{min-height:36px;min-width:36px}}
"""


JS = """
<script>
(function(){
var $=function(s,r){return (r||document).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
var curG=null;
function altoTabs(){var t=$('#tabs');if(t)document.documentElement.style.setProperty('--tabh',t.offsetHeight+'px');}
function fixTables(){altoTabs();$$('.tab.on .scroll').forEach(function(s){if(s.offsetParent===null)return;s.classList.toggle('ov',s.scrollWidth>s.clientWidth+4);});}
function showTab(id,quiet){var t=document.getElementById(id);if(!t||!t.classList.contains('tab'))return false;
 $$('.tab').forEach(function(x){x.classList.toggle('on',x===t);});$$('.tabbtn').forEach(function(b){b.classList.toggle('on',b.dataset.t===id);});
 if(!quiet){try{history.replaceState(null,'','#tab='+id.replace('tab-',''));}catch(e){}}fixTables();return true;}
function showSub(p,s){if(!p)return;var ok=$$('.sp',p).some(function(x){return x.dataset.s===s;});if(!ok)s=($('.sp',p)||{dataset:{}}).dataset.s;
 $$('.sp',p).forEach(function(x){x.classList.toggle('on',x.dataset.s===s);});$$('.sbtn',p).forEach(function(b){b.classList.toggle('on',b.dataset.s===s);});p.dataset.sub=s;fixTables();}
function showGame(g,quiet){var p=$('.gpanel[data-g="'+g+'"]');if(!p)return false;curG=g;
 $$('.gpanel').forEach(function(x){x.classList.toggle('on',x===p);});$$('.gchip').forEach(function(b){b.classList.toggle('on',b.dataset.g===g);});
 showSub(p,p.dataset.sub||'ap');var c=$('.gchip.on');if(c&&c.scrollIntoView){try{c.scrollIntoView({block:'nearest',inline:'center'});}catch(e){}}
 if(!quiet){try{history.replaceState(null,'','#game='+g);}catch(e){}}return true;}
function openAncestors(el){var d=el.closest('details');while(d){d.open=true;d=d.parentElement?d.parentElement.closest('details'):null;}}
function go(id){var el=document.getElementById(id);if(!el)return false;var tab=el.closest('.tab');if(tab)showTab(tab.id,true);
 var gp=el.closest('.gpanel');if(gp){showGame(gp.dataset.g,true);var sp=el.closest('.sp');if(sp)showSub(gp,sp.dataset.s);}
 openAncestors(el);setTimeout(function(){try{el.scrollIntoView({behavior:'smooth',block:'start'});}catch(e){el.scrollIntoView();}},40);return true;}
function openGame(g){showTab('tab-partidos',true);showGame(g,false);var s=$('#gsel');window.scrollTo(0,s?Math.max(0,s.getBoundingClientRect().top+window.pageYOffset-(($('#tabs')||{offsetHeight:56}).offsetHeight)-4):0);}
document.addEventListener('click',function(e){var t=e.target;
 var tb=t.closest('.tabbtn');if(tb){showTab(tb.dataset.t);window.scrollTo(0,0);return;}
 var gc=t.closest('.gchip');if(gc){showGame(gc.dataset.g);return;}
 var gg=t.closest('[data-go]');if(gg){openGame(gg.dataset.go);return;}
 var sb=t.closest('.sbtn');if(sb){showSub(sb.closest('.gpanel'),sb.dataset.s);return;}
 var ga=t.closest('#gall');if(ga){var on=$('#pgrid').classList.toggle('todos');ga.classList.toggle('on',on);ga.textContent=on?'Mostrar uno':'Mostrar todos';return;}
 var mb=t.closest('#menubtn'),am=$('#allmenu');
 if(mb&&am){var ab=am.hidden;am.hidden=!ab;mb.setAttribute('aria-expanded',ab?'true':'false');altoTabs();return;}
 if(am&&!am.hidden&&!t.closest('#allmenu')){am.hidden=true;var m2=$('#menubtn');if(m2)m2.setAttribute('aria-expanded','false');}
 else if(am&&!am.hidden&&t.closest('#allmenu a')){am.hidden=true;var m3=$('#menubtn');if(m3)m3.setAttribute('aria-expanded','false');}
 if(t.closest('#arriba')){window.scrollTo({top:0,behavior:'smooth'});return;}
 var a=t.closest('a[href^="#"]');if(a&&a.getAttribute('href').length>1){var id=a.getAttribute('href').slice(1);if(document.getElementById(id)){e.preventDefault();go(id);}}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var am=$('#allmenu');if(am&&!am.hidden){am.hidden=true;var m=$('#menubtn');if(m){m.setAttribute('aria-expanded','false');m.focus();}}}});
function fromHash(){var h=decodeURIComponent((location.hash||'').slice(1));if(!h)return false;
 if(h.indexOf('game=')===0){if(showGame(h.slice(5),true)){showTab('tab-partidos',true);return true;}return false;}
 if(h.indexOf('tab=')===0)return showTab('tab-'+h.slice(4),true);
 return go(h);}
/* texto explicativo largo -> plegable */
function plegar(){$$('.tab').forEach(function(root){var run=[];var kids=Array.prototype.slice.call(root.children);
 function cerrar(){if(!run.length)return;var d=document.createElement('details');d.className='exp';var s=document.createElement('summary');s.textContent='Cómo se lee';d.appendChild(s);
  run[0].parentNode.insertBefore(d,run[0]);run.forEach(function(p){d.appendChild(p);});run=[];}
 kids.forEach(function(k){if(k.tagName==='P'&&k.classList.contains('explain')&&!k.classList.contains('keep')&&k.textContent.length>150){run.push(k);}else{cerrar();}});cerrar();});}
function envolverTablas(){$$('.tab table').forEach(function(t){if(t.closest('.scroll,.chart,#parlay'))return;var w=document.createElement('div');w.className='scroll';t.parentNode.insertBefore(w,t);w.appendChild(t);});
 $$('img').forEach(function(i){i.setAttribute('loading','lazy');i.setAttribute('decoding','async');});}
/* frescura */
function fresco(){var f=$('#fresh');if(!f)return;var gen=Date.parse(f.dataset.gen);if(isNaN(gen))return;var now=Date.now(),h=(now-gen)/36e5;
 function dur(x){if(x<1)return Math.max(1,Math.round(x*60))+' min';if(x<48)return (x<10?x.toFixed(1).replace('.0',''):Math.round(x))+' h';return Math.round(x/24)+' días';}
 var next=null;$$('.grow[data-ko]').forEach(function(r){var k=Date.parse(r.dataset.ko);if(!isNaN(k)&&k>now&&(next===null||k<next.k))next={k:k,m:r.dataset.match};});
 var t='actualizado hace '+dur(Math.max(h,0));if(next)t+=' · próximo partido: '+next.m+' en '+dur((next.k-now)/36e5);else t+=' · sin partidos próximos';
 f.textContent=t;f.classList.toggle('viejo',!!next&&(next.k-now)/36e5<24&&h>6);}
function init(){plegar();envolverTablas();
 var tabs=$$('.tab');if(!tabs.length)return;
 if(!fromHash()){showTab('tab-semana',true);}
 /* partido por defecto: el primero que todavia no empieza */
 if(!$('.gpanel.on')){var now=Date.now(),pick=null;$$('.grow[data-ko]').forEach(function(r){var k=Date.parse(r.dataset.ko);if(pick===null&&(isNaN(k)||k>now-3*36e5))pick=r.dataset.g;});
  var first=$('.gchip');if(!pick&&first)pick=first.dataset.g;if(pick)showGame(pick,true);}
 fresco();setInterval(fresco,60000);
 var up=$('#arriba');window.addEventListener('scroll',function(){if(up)up.classList.toggle('on',window.pageYOffset>700);},{passive:true});
 window.addEventListener('resize',fixTables);window.addEventListener('hashchange',fromHash);fixTables();}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>
"""
