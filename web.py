"""Diseno de la pagina: pestanas, resumen por partido, vista de un partido a la vez, texto plegable y avisos de frescura.

NO calcula nada: solo acomoda el HTML que ya generan reporte.py, puntos.py, reporte_extra.py, por_equipo.py, elo.py, marcador.py y qb.py.
Todas las calculadoras (linea editable de totales / equipos / combinadas, props, touchdowns, combinada de jugadores, cuotas) siguen siendo las
mismas: escuchan eventos a nivel de documento, asi que funcionan igual aunque su bloque este en otra pestana o dentro de un desplegable.

Estructura (4 secciones, navegacion segmentada; tema oscuro (paleta Los Picketones) por defecto y claro con boton)
  Picks / Valor         que apostar hoy, posibles valores, filtros, partidos de la semana (la siguiente aparte), resumen, graficas, tarjeta, metodologia
  Partidos              selector de partido; cada partido con 4 sub-pestanas: Apuestas / Puntos y combinadas / Props y TD / Matchup
  Jugadores y Props     LINEA AC, touchdowns, props destacados, cruce ofensiva vs defensa, ofensiva, defensiva
  Record / Backtest     resumen de calidad, mis apuestas, record, marcador, confianza, historial y la guia («Como leer este reporte»)

Si algo falla al armar este diseno, reporte.py usa el diseno anterior (una sola pagina larga).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

import clima as CL
from odds_fmt import fd
import web_extra as EX
from barras import barra

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
            nom = "; ".join(f"{r.name} ({r.team} · {r.position}, {'baja' if r.estado == 'Out' else 'dudoso'})" for r in e.itertuples())
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


# ------------------------------------------------------------------------------------------ componentes
SUBS = {"ap": "apuestas", "pt": "puntos", "pr": "props", "mu": "matchup"}      # sub-pestana -> nombre en la URL (#partido=MIN-SF&tab=props)
SUB_TXT = {"ap": "Apuestas", "pt": "Puntos y combinadas", "pr": "Props y TD", "mu": "Matchup"}

# Textos de los «?»: mismo significado que «Cómo leer este reporte» y la guia de Calidad (solo mas cortos)
TIPS = {
    "modelo": ("Modelo", "Probabilidad que el modelo B (el de decisión) da a que ocurra esto. Parte de la línea del mercado y la ajusta un poco con ratings y descanso."),
    "implicita": ("Probabilidad que exige la cuota", "Una cuota decimal de 1.91 (la habitual) pide acertar 52.4 % de las veces para no perder dinero a largo plazo. Esa es la «probabilidad implícita»; ya incluye la comisión de la casa."),
    "ventaja": ("Ventaja (en puntos)", "Probabilidad del modelo menos la que exige la cuota, en puntos porcentuales. Si es negativa, la cuota paga menos de lo que vale según el modelo. Solo se marca «posible valor» desde el umbral (por defecto +2 pts)."),
    "cuota": ("Cuota justa", "La cuota sin comisión que corresponde a una probabilidad. Si tu casa paga más que la cuota justa, hay valor según el modelo."),
    "clv": ("CLV", "Si la línea se movió a favor del lado que eligió el modelo entre su predicción y el cierre. Positivo = el mercado terminó dándole la razón."),
    "logloss": ("Log-loss", "Mide qué tan buenas son las probabilidades (menos es mejor; 0.693 = lanzar una moneda). Frente al mercado importa que sea menor."),
    "push": ("Push", "La línea cayó exacta: la apuesta se devuelve y no cuenta ni como ganada ni como perdida."),
    "ic": ("IC 95 %", "Intervalo de confianza: cuánto puede ser solo azar. Si incluye el 0 %, el resultado no se distingue de la suerte."),
    "roi": ("ROI", "Ganancia entre dinero apostado (1 unidad por apuesta). Se muestra con su intervalo de confianza."),
    "tamano": ("Tamaño sugerido", "Cuántas unidades apostar (1 unidad = 1 % de tu banca): un cuarto de lo que sugiere el criterio de Kelly con la probabilidad del modelo y la cuota, con tope de 1 unidad. Es una guía para no apostar de más, no una garantía: el modelo no ha demostrado ventaja estable."),
    "acierto": ("Acierto", "% de veces que pasó lo que el modelo veía más probable. En spread y total, con cuota decimal 1.91, el punto de equilibrio es 52.4 %."),
}


def tip(k: str) -> str:
    return f'<button type="button" class="tip" data-tip="{k}" aria-label="¿Qué significa {_esc(TIPS[k][0])}?">?</button>'


def vchip(cls: str, txt: str, title: str = "") -> str:
    t = f' title="{_esc(title)}"' if title else ""
    return f'<span class="vchip {cls}"{t}>{_esc(txt)}</span>'


def lt(s) -> str:
    return str(s).replace("OVER", "Más de").replace("UNDER", "Menos de")


def _mercados(x) -> list[dict]:
    """Los tres mercados de un partido con lo que ya calcula predict/reporte (nada se recalcula aqui)."""
    if x is None:
        return []
    out = []
    h = x.home_team
    for k, t in (("sp", "Spread"), ("to", "Total de puntos"), ("ml", "Ganador")):
        if k == "ml" and not x.tiene_ml:
            continue
        lado = x[f"{k}_lado"]
        if k == "ml":
            lab = f"{lado.replace(' ML', '')} gana"
        else:                                   # en spread y total el lado ya trae su linea («MIN +3», «OVER 46.5»)
            lab = lt(lado)
        p = float(x[f"{k}_p"])
        # En el ganador (moneyline) el lado con «ventaja» puede ser el NO favorito: la apuesta es «PIT gana» aunque el modelo favorezca a DEN.
        # lab (la apuesta tal cual) no cambia; rot es el rotulo de lectura y pos/neg nombran a los equipos en la barra.
        under = (k == "ml" and p < 0.5)
        pl_ = float(x.p_gana_local)
        fav = h if pl_ >= 0.5 else x.away_team
        pfav = pl_ if pl_ >= 0.5 else 1 - pl_
        if k == "ml":
            eq_ = lado.replace(" ML", "")
            pos, neg = f"Modelo: {eq_}", (x.away_team if eq_ == h else h)
        else:
            pos, neg = "Modelo", "Lado contrario"
        out.append({"k": k, "t": t, "lado": lado, "lab": lab, "p": p, "imp": float(x[f"{k}_imp"]),
                    "cuota": float(x[f"{k}_cuota"]), "edge": float(x[f"{k}_edge"]), "under": under, "fav": fav, "pfav": pfav,
                    "rot": lab + (" — no es el favorito" if under else ""), "rot_c": lab + (" (no favorito)" if under else ""),
                    "pos": pos, "neg": neg})
    return out


def _veredicto_chip(k: str, hv: dict | None) -> tuple[str, str, str]:
    """Misma regla que reporte.veredicto_hist (ámbar si el ROI histórico es <0 o su IC 95 % incluye 0; verde solo si queda sobre 0)."""
    h = (hv or {}).get(k)
    if not h or not h.get("n"):
        return "aviso", "⚠ Ventaja pequeña – sin historial suficiente", ""
    lin = (f"Histórico de este tipo: {h['acierto'] * 100:.1f}% de acierto ({h['n']} apuestas) · ROI {h['roi'] * 100:+.1f}% "
           f"(IC 95 %: {h['lo'] * 100:+.1f} a {h['hi'] * 100:+.1f}%)")
    if h["roi"] < 0:
        return "aviso", "⚠ Ventaja pequeña – históricamente no rentable", lin
    if h["lo"] <= 0:
        return "aviso", "⚠ Posible valor – histórico no concluyente", lin
    return "valor", "✔ Posible valor – históricamente rentable", lin


def _ct(m: dict) -> str:
    return "La cuota (" + fd(m["cuota"]) + ") exige"


def _badges_pie(bs, n: int = 2) -> str:
    """Pie de la tarjeta: como maximo 2 alertas clave (el resto sigue completo en el detalle del partido); el «posible valor» ya va arriba."""
    al = [b for b in bs if b[0] != "v"]
    s = _badges_html(al[:n])
    if len(al) > n:
        resto = "; ".join(f"{b[1]}: {b[2]}" if b[2] else b[1] for b in al[n:])
        s += f'<span class="bd" title="{_esc(resto)}">+{len(al) - n} más</span>'
    return s


def _card_partido(d: dict, nm, c: dict) -> str:
    x, g = d["x"], d["pt"]
    h, a = d["home"], d["away"]
    me, hv = c["me"], c.get("hv")
    nums, barra_h = [], ""
    if x is not None:
        pl = x.p_gana_local * 100
        fav, pf = (h, pl) if pl >= 50 else (a, 100 - pl)
        otro = a if fav == h else h
        mk = x.p_gana_local_mercado * 100
        mkv = (mk if pl >= 50 else 100 - mk) if pd.notna(mk) else None
        barra_h = barra(pf, mkv, fav, otro, "Corte del mercado")
        nums.append(f'<span>Línea: <b>{_esc(h)} {x.linea_local:+g}</b> · total <b>{x.total_line:g}</b></span>')
    elif g is not None:
        m = g["m"]
        nums.append(f'<span>Modelo: <b>{_esc(h if m >= 0 else a)}</b> por {abs(m):.1f}</span>')
        nums.append(f'<span>Línea: <b>{_esc(h)} {-g["spread"]:+g}</b> · total <b>{g["lt"]:g}</b></span>' if g["mercado"] else "<span>Sin línea todavía</span>")
    sc = f'<div class="score">Marcador esperado <b class="num">{_esc(a)} {g["a"]:.0f} – {g["h"]:.0f} {_esc(h)}</b></div>' if g is not None else ""
    mks = [m for m in _mercados(x) if m["edge"] >= me]
    ver = ""
    if mks:
        cl, tx, _ = _veredicto_chip(mks[0]["k"], hv)
        ver = vchip("valor" if cl == "valor" else "aviso", f"✔ Posible valor: {mks[0]['lab']}", "; ".join(f"{m['t']}: {m['lab']} ({m['edge'] * 100:+.1f} pts)" for m in mks))
    elif x is not None:
        ver = vchip("neutral", "— Sin ventaja contra el mercado")
    else:
        ver = vchip("line", "Semana siguiente")
    ko = d["ko"].isoformat() if d["ko"] is not None else ""
    al = [k for k, w in (("qb", "🏈"), ("clima", "💨🥶💧"), ("les", "🩹"), ("mov", "🔁")) if any(
        (b[1].split(" ")[0] in w) for b in d["bd"])]
    return (f'<article class="mcard grow" data-g="{_esc(d["id"])}" data-ko="{ko}" data-match="{_esc(a)} @ {_esc(h)}" data-teams="{_esc(a)} {_esc(h)}" '
            f'data-val="{" ".join(m["k"] for m in mks)}" data-al="{" ".join(al)}">'
            f'<div class="gc-top"><span class="when gr-when">{_esc(_cuando(d["ko"]))}</span>{ver}</div>'
            f'<div class="gc-mid"><div class="teams"><span>{_esc(a)}</span><span class="at">@</span><span>{_esc(h)}</span></div>'
            f'<div class="full gr-main">{_esc(nm(a))} @ {_esc(nm(h))}</div>{sc}'
            f'<div class="gc-nums">{"".join(nums)}</div></div>{barra_h}'
            f'<div class="gc-foot"><span class="gc-alerts gr-bd">{_badges_pie(d["bd"])}</span>'
            f'<button type="button" class="more gr-go" data-go="{_esc(d["id"])}">Ver partido →</button></div></article>')


def _picks(js_: list[dict], c: dict, nm) -> str:
    """Tarjetas de «posible valor» ordenadas de mayor a menor ventaja (carrusel en movil)."""
    me, hv = c["me"], c.get("hv")
    L = []
    for d in js_:
        for m in _mercados(d["x"]):
            if m["edge"] >= me:
                L.append((m["edge"], d, m))
    L.sort(key=lambda t: -t[0])
    if not L:
        return ('<div class="vacio"><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Ningún partido supera el umbral de valor esta semana.</b> '
                'Es lo más habitual: el mercado de la NFL es muy eficiente.</div></div>')
    cards = []
    for e, d, m in L:
        cl, tx, _ = _veredicto_chip(m["k"], hv)
        h, a = d["home"], d["away"]
        cards.append(
            f'<article class="pick" data-go="{_esc(d["id"])}" data-tab="apuestas" data-teams="{_esc(a)} {_esc(h)}" data-mk="{m["k"]}" tabindex="0" role="button" '
            f'aria-label="{_esc(m["t"])} {_esc(m["rot"])}, ventaja {e * 100:+.1f} puntos. Ver partido">'
            f'<div class="gc-top"><span class="when">{_esc(_cuando(d["ko"]))}</span>{vchip("valor" if cl == "valor" else "aviso", tx)}</div>'
            f'<div class="gc-mid"><div class="pk-m">{_esc(m["t"])} · {_esc(a)} @ {_esc(h)}</div><div class="pk-lado">{_esc(m["rot"])}</div>'
            f'<div class="pk-edge {"v" if cl == "valor" else "a"}"><span class="num">{e * 100:+.1f}</span> <span class="pk-u">pts de ventaja</span></div>'
            f'<div class="pk-det">Cuota <b>{fd(m["cuota"])}</b></div></div>'
            f'{barra(m["p"] * 100, m["imp"] * 100, m["pos"], m["neg"], _ct(m), diff=e * 100)}'
            f'<div class="gc-foot"><span class="more">Ver partido →</span></div></article>')
    return f'<div class="carousel" id="picks" role="list" aria-label="Posibles valores ordenados por ventaja">{"".join(cards)}</div>'


def _alertas(js_: list[dict]) -> str:
    n = lambda k: sum(1 for d in js_ if any(b[1].split(" ")[0] in {"qb": "🏈", "clima": "💨🥶💧", "les": "🩹", "mov": "🔁"}[k] for b in d["bd"]))
    ch = []
    for k, t in (("qb", "🏈 Mariscal distinto o en duda"), ("clima", "💨 Clima"), ("les", "🩹 Lesiones"), ("mov", "🔁 Fichajes")):
        if n(k):
            ch.append(f'<button type="button" class="vchip aviso" data-al="{k}" aria-pressed="false">{t} · {n(k)}</button>')
    return f'<div class="chips" id="alertas">{"".join(ch)}</div>' if ch else ""


def _filtros(js_: list[dict], nm) -> str:
    eq = sorted({d["away"] for d in js_} | {d["home"] for d in js_})
    op = "".join(f'<option value="{_esc(t)}">{_esc(nm(t))}</option>' for t in eq)
    return ('<div class="fbar filters" role="search" aria-label="Filtros de partidos">'
            f'<label>Equipo<select id="f-eq"><option value="">Todos</option>{op}</select></label>'
            '<label>Mercado<select id="f-mk"><option value="">Todos</option><option value="sp">Spread</option><option value="to">Total (Más de / Menos de)</option><option value="ml">Ganador</option></select></label>'
            '<button type="button" class="toggle" id="f-val" aria-pressed="false">Solo con valor</button>'
            '<button type="button" class="limpiar" id="f-clear" hidden>Limpiar filtros</button>'
            '<span class="fcount" id="f-n" aria-live="polite"></span></div>')


def _grupo(titulo: str, sub: str, ds: list[dict], nm, c: dict, cls: str = "") -> str:
    filas = "".join(_card_partido(d, nm, c) for d in ds)
    return (f'<div class="sem-sec"><h3>{_esc(titulo)}</h3><p class="leyenda">{sub}</p></div><div class="mlist grows {cls}">{filas}</div>')


def resumen_partidos(js_: list[dict], nm, c: dict) -> str:
    if not js_:
        return ""
    act = [d for d in js_ if d["x"] is not None]          # semana en curso (tiene apuestas contra el mercado)
    sig = [d for d in js_ if d["x"] is None]              # semanas posteriores (solo puntos y combinadas)
    # la lista #mlist solo agrupa la semana activa; la siguiente va en su propio bloque (plegado) para no mezclarlas
    cuerpo = _grupo(f"Semana {c['wk']} · en curso", "✔ posible valor · 🏈 mariscal distinto o en duda · 💨 viento fuerte · 🥶 frío · 💧 lluvia o nieve probable · "
                    "🩹 jugadores con proyección fuera o dudosos. Toca un partido para ver todo su detalle y editar tus líneas.", act, nm, c) if act else ""
    cuerpo = cuerpo.replace('class="mlist grows ', 'id="mlist" class="mlist grows ', 1) if act else ""
    extra = ""
    if sig:
        extra = (f'<details class="exp semsig" id="sem-sig"><summary>Semana siguiente ({len(sig)} partidos) · por ahora solo Más de / Menos de de puntos y combinadas</summary>'
                 f'<div class="mlist grows">{"".join(_card_partido(d, nm, c) for d in sig)}</div></details>')
    return ('<h2 id="partidos-sem">Los partidos de la semana</h2>'
            f'{_filtros(js_, nm)}{cuerpo}'
            '<div class="vacio" id="f-vacio" hidden><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Ningún partido coincide con los filtros.</b> Quita alguno para ver más. '
            '<button type="button" class="chip" data-limpiar="1">Limpiar filtros</button></div></div>' + extra)


def _selector(js_: list[dict], c: dict) -> str:
    chips, vio_sig = [], False
    for d in js_:
        if d["x"] is None and not vio_sig:
            vio_sig = True
            chips.append(f'<span class="gsep" role="separator" aria-label="Semana siguiente">Semana siguiente</span>')
        chips.append(f'<button type="button" class="gchip" data-g="{_esc(d["id"])}"><b>{_esc(d["away"])} @ {_esc(d["home"])}</b>'
                     f'<small>{_esc(_corto(d["ko"]))}</small><span class="gc-i">{_badges_html(d["bd"], True)}</span></button>')
    return ('<div class="gsel" id="gsel"><div class="gsel-in">' + "".join(chips) +
            '</div><button type="button" class="gall" id="gall">Mostrar todos</button></div>')


def _una_frase(d: dict, c: dict) -> str:
    """Resumen de una frase con los mismos numeros que ya muestra el partido."""
    x, g = d["x"], d["pt"]
    h, a = d["home"], d["away"]
    if x is None:
        return "Partido de la semana siguiente: por ahora solo tiene los Más de / Menos de de puntos y las combinadas."
    pl = x.p_gana_local * 100
    fav, pf = (h, pl) if pl >= 50 else (a, 100 - pl)
    s = f"El modelo favorece a {fav} con {pf:.0f}%; línea {h} {x.linea_local:+g}, total {x.total_line:g}"
    if g is not None:
        s += f", marcador esperado {a} {g['a']:.0f} – {g['h']:.0f} {h}"
    mks = [m for m in _mercados(x) if m["edge"] >= c["me"]]
    s += ". " + (("Posible valor: " + "; ".join(f"{m['rot']} ({m['edge'] * 100:+.1f} pts)" for m in mks) + ".") if mks else "Sin ventaja contra el mercado.")
    return s


def _eleccion_ml(x, me: float) -> str:
    """Elección del modelo en el ganador (moneyline), la tenga o no ventaja: el equipo que el modelo ve más probable.
    Solo muestra lo que ya calcula predict (p_gana_local, cuota, ventaja); no cambia ningún cálculo ni el veredicto."""
    try:
        pl = float(x.p_gana_local)
    except (TypeError, ValueError):
        return ""
    if pl != pl:
        return ""
    home = pl >= 0.5
    eq = x.home_team if home else x.away_team
    p = pl if home else 1 - pl
    tiene = bool(x.tiene_ml)
    odds = x.home_moneyline if home else x.away_moneyline
    pm = x.p_gana_local_mercado
    pm = (pm if home else 1 - pm) if (tiene and pm == pm) else None
    cuota = fd(odds) if tiene else "sin cuota"
    if tiene and float(x.ml_edge) >= me:
        lado = str(x.ml_lado).replace(" ML", "")
        nota = (f"Además tiene posible valor ({float(x.ml_edge) * 100:+.1f} pts)." if lado == eq else
                f"El posible valor de este mercado está en {_esc(lado)} (no es la elección del modelo): se explica abajo.")
    elif tiene:
        nota = "Esta elección es solo informativa: no hay ventaja contra la cuota, así que no es una apuesta recomendada."
    else:
        nota = "Esta elección es solo informativa: todavía no hay cuota de ganador publicada."
    mk = (f'<div class="fact"><small>El mercado le da{tip("implicita")}</small><b>{pm * 100:.0f}%</b></div>' if pm is not None else "")
    return (f'<section class="verdict box" aria-label="Elección del modelo en el ganador">{vchip("neutral", "Elección del modelo · Ganador (moneyline)")}'
            f'<h3>Gana {_esc(eq)} <span class="pk-g">(moneyline)</span></h3>'
            f'{barra(p * 100, pm * 100 if pm is not None else None, eq, x.away_team if home else x.home_team, "El mercado le da")}'
            f'<div class="facts mini3"><div class="fact"><small>Modelo{tip("modelo")}</small><b>{p * 100:.0f}%</b></div>{mk}'
            f'<div class="fact"><small>Cuota</small><b>{cuota}</b></div></div>'
            f'<p class="explain">{nota}</p></section>')


def _veredicto_html(d: dict, c: dict) -> str:
    """Un solo veredicto por apuesta con posible valor (y, si no hay, el mejor lado y por que no alcanza)."""
    x = d["x"]
    if x is None:
        return ""
    me, hv = c["me"], c.get("hv")
    ms = _mercados(x)
    val = [m for m in ms if m["edge"] >= me]
    out = [_eleccion_ml(x, me)]
    if val:
        for m in val:
            cl, tx, lin = _veredicto_chip(m["k"], hv)
            out.append(
                f'<section class="verdict box" aria-label="Veredicto {_esc(m["t"])}">{vchip("valor" if cl == "valor" else "aviso", tx)}'
                f'<h3>Posible valor: {_esc(m["rot"])} <span class="pk-g">({_esc(m["t"])})</span></h3>'
                f'{barra(m["p"] * 100, m["imp"] * 100, m["pos"], m["neg"], _ct(m), diff=m["edge"] * 100)}'
                f'<div class="facts mini3"><div class="fact"><small>Modelo{tip("modelo")}</small><b>{m["p"] * 100:.0f}%</b></div>'
                f'<div class="fact"><small>Cuota ({fd(m["cuota"])}) exige{tip("implicita")}</small><b>{m["imp"] * 100:.0f}%</b></div>'
                f'<div class="fact edge"><small>Ventaja{tip("ventaja")}</small><b>{m["edge"] * 100:+.1f} pts</b></div></div>'
                + (f'<p class="explain">Ojo: esto no es el pronóstico del partido. El modelo favorece a {_esc(m["fav"])} ({m["pfav"] * 100:.0f}%); '
                   f'aquí la apuesta es a {_esc(m["lado"].replace(" ML", ""))}, que tiene {m["p"] * 100:.0f}% según el modelo contra {m["imp"] * 100:.0f}% que exige la cuota. '
                   f'El valor está en lo que paga, no en que el modelo lo espere ganador.</p>' if m["under"] else "")
                + (f'<p class="hist">{_esc(lin)}</p>' if lin else "") + f'<p>{EX.boton_registrar(d, m)}</p></section>')
    else:
        m = max(ms, key=lambda t: t["edge"]) if ms else None
        if m:
            out.append(
                f'<section class="verdict box" aria-label="Veredicto">{vchip("neutral", "— Sin ventaja contra el mercado")}'
                f'<h3>Sin ventaja en este partido</h3>{barra(m["p"] * 100, m["imp"] * 100, m["pos"], m["neg"], _ct(m), diff=m["edge"] * 100)}<p class="explain">El mejor lado es {_esc(m["rot"])} ({_esc(m["t"])}): el modelo le da {m["p"] * 100:.0f}% y la cuota '
                f'({fd(m["cuota"])}) exige {m["imp"] * 100:.0f}%, una ventaja de {m["edge"] * 100:+.1f} pts, menos que el umbral de {me * 100:.0f} pts.{tip("ventaja")}</p></section>')
    return "".join(out)


def _panel(d: dict, nm, card_apuestas: str, extra: dict, card_puntos: str, c: dict) -> tuple[str, str]:
    """(shell del partido, fragmento con sus sub-pestanas). El shell trae encabezado y pastillas; el fragmento se carga al abrir el partido."""
    gid = d["id"]
    sub = []
    if card_apuestas or extra.get("casas"):
        sub.append(("ap", _veredicto_html(d, c) + card_apuestas + extra.get("casas", "")))
    if card_puntos:
        sub.append(("pt", '<p class="calc-tit">Mi línea / mi cuota</p>' + card_puntos))
    if extra.get("td") or extra.get("props"):
        sub.append(("pr", extra.get("td", "") + extra.get("props", "")))
    if extra.get("matchup"):
        sub.append(("mu", extra["matchup"]))
    if not sub:
        sub = [("ap", '<div class="box">Todavía no hay datos de este partido.</div>')]
    botones = "".join(f'<button type="button" class="sbtn pill" data-s="{k}" data-n="{SUBS[k]}">{SUB_TXT[k]}</button>' for k, _ in sub)
    cuerpos = "".join(f'<div class="sp" data-s="{k}">{h}</div>' for k, h in sub)
    nota = ""
    if not card_apuestas:
        nota = ('<p class="leyenda">Este partido es de la semana siguiente: por ahora solo tiene los Más de / Menos de de puntos y las combinadas. '
                'Las apuestas contra el mercado, los props y los matchups aparecen cuando entra a la semana en curso.</p>')
    g, h, a = d["pt"], d["home"], d["away"]
    big = (f'<div class="big"><span class="num">{_esc(a)} {g["a"]:.0f} – {g["h"]:.0f} {_esc(h)}</span><span>marcador esperado</span></div>' if g is not None else "")
    slug = f"{a}-{h}"
    head = (f'<section class="gpanel" data-g="{_esc(gid)}" data-slug="{_esc(slug)}" data-frag="g-{_esc(gid)}">'
            f'<div class="gp-head mh"><div class="mc-top"><span class="gp-when when">{_esc(_cuando(d["ko"]))}</span><div class="gp-bd">{_badges_html(d["bd"])}</div></div>'
            f'<h3 class="teams">{_esc(a)} <span class="at">@</span> {_esc(h)}</h3><div class="full">{_esc(nm(a))} @ {_esc(nm(h))}</div>{big}<p class="resumen1">{_esc(_una_frase(d, c))}</p></div>{nota}'
            f'<div class="sseg pillbar" role="tablist">{botones}</div><div class="gp-body"><div class="cargando" role="status">Cargando el partido…</div></div></section>')
    return head, f'<template id="frag-g-{_esc(gid)}">{cuerpos}</template>'


def _sin_numeros(h: str) -> str:
    """Quita la numeracion «4. », «5. » de los titulos (ya no van en orden al estar en pestanas)."""
    return re.sub(r"(<h2[^>]*>)\s*\d+\.\s+", r"\1", h)


def _subnav(items) -> str:
    return '<nav class="subnav" aria-label="Secciones de esta pestaña">' + "".join(f'<a href="#{i}">{_esc(t)}</a>' for i, t, ok in items if ok) + "</nav>"


def _kpis(c: dict) -> str:
    """Tarjetas KPI de Calidad con los numeros de evaluacion.py (acierto, ROI con IC 95 %, log-loss del modelo contra el mercado)."""
    ev = c.get("ev_all") or {}
    if not ev:
        return ""
    tit = {"spread": "Spread", "total": "Total (Más de / Menos de)", "ganador": "Ganador"}
    cards = []
    for mk in ("spread", "total", "ganador"):
        r = ev.get(mk)
        if not r:
            continue
        v = r["valor"]
        if v["n"]:
            cls = "c" if v["roi"] < 0 else ("a" if v["lo"] <= 0 else "v")
            ico = {"c": "✖", "a": "⚠", "v": "✔"}[cls]
            txt = ("negativo" if cls == "c" else ("no concluyente (el IC incluye 0)" if cls == "a" else "positivo"))
            roi = (f'<div class="kv {cls}"><span aria-hidden="true">{ico}</span> {v["roi"] * 100:+.1f}%</div>'
                   f'<div class="ks">ROI de los «posibles valores»{tip("roi")} · {txt}<br>IC 95 %{tip("ic")}: {v["lo"] * 100:+.1f}% a {v["hi"] * 100:+.1f}%</div>'
                   f'<div class="ks">Acierto{tip("acierto")}: <b>{v["acierto"] * 100:.1f}%</b> en {v["n"]} apuestas</div>'
                   + barra(v["acierto"] * 100, 52.4 if mk in ("spread", "total") else None, "Acierto", "Falló", "Punto de equilibrio (cuota 1.91)")
                   + ('' if mk in ("spread", "total") else '<div class="ks">Sin corte único: el punto de equilibrio depende de la cuota de cada apuesta.</div>'))
        else:
            roi = '<div class="ks">Sin apuestas con valor en el historial.</div>'
        dll = r["ll"] - r["ll_mk"]
        roi += (f'<div class="ks">Log-loss{tip("logloss")} del modelo: <b>{r["ll"]:.3f}</b> · del mercado: <b>{r["ll_mk"]:.3f}</b> '
                f'({"mejor" if dll < 0 else "no mejor"} que el mercado)</div>')
        cards.append(f'<article class="kpi box"><h3>{tit[mk]}</h3>{roi}</article>')
    return (f'<h2 id="kpis" class="tabsec">Resumen de calidad (pruebas fuera de muestra)</h2><div class="kpis">{"".join(cards)}</div>'
            '<p class="explain">Cada tarjeta resume cuánto acertó el modelo en temporadas pasadas (sin usar datos del futuro). Los detalles y las tablas completas están más abajo.</p>')


# ------------------------------------------------------------------------------------------ ensamblado
def _metodologia(c: dict) -> str:
    """Notas metodologicas plegadas (mismos textos que ya tiene la pagina: «?» y «Como leer este reporte»); no cambia ningun calculo."""
    ay = c.get("ayuda", "")
    ab = "".join(re.findall(r'<div class="box"><h4>Modelo [AB].*?</div>', ay, flags=re.S))
    return ('<details class="exp" id="metodologia"><summary>Metodología y transparencia: tamaño sugerido (¼ Kelly, tope de 1 u), ROI histórico y Modelo A frente a Modelo B</summary>'
            f'<div class="met"><h4>Tamaño sugerido</h4><p>{_esc(TIPS["tamano"][1])}</p>'
            f'<h4>ROI histórico</h4><p>{_esc(TIPS["roi"][1])} {_esc(TIPS["ic"][1])} Las cifras fuera de muestra están en <a href="#kpis">Récord / Backtest</a>.</p>'
            f'<h4>Modelo A y Modelo B</h4>{ab}</div></details>')


def armar(c: dict) -> str:
    """HTML del <main>. c: ver reporte.construir (claves: cur, wk, n, sub, generado_iso, resumen, importante, graficas, ayuda, cred, hist_html,
    sec_*, ex_parts, cards_ap, PT, pt_partes, res, games, qb, clima, excl, me, nm, hv, ev_all, js_frag)."""
    nm = c["nm"]
    js_ = juegos(c)
    pp = c.get("pt_partes") or {}
    cards_pt = pp.get("cards", {})
    heads, frags = [], []
    for d in js_:
        h_, f_ = _panel(d, nm, c["cards_ap"].get(d["id"], ""), c["ex_parts"].get(d["id"], {}), cards_pt.get(d["id"], ""), c)
        heads.append(h_)
        frags.append(f_)
    intro_pt = re.sub(r"^<h2[^>]*>.*?</h2>", "", pp.get("intro", ""), count=1, flags=re.S)
    como = (f'<details class="exp" id="puntos"><summary>Cómo funcionan los Más de / Menos de, el clima y las combinadas</summary>{intro_pt}</details>' if intro_pt else "")

    def lazy(name, html_, host_cls="fhost"):
        frags.append(f'<template id="frag-{name}">{html_}</template>')
        return f'<div class="{host_cls}" data-frag="{name}"><div class="cargando" role="status">Cargando…</div></div>'

    # ---- Picks / Valor (inicio): que apostar hoy, posibles valores, filtros, partidos de la semana, graficas, tarjeta y metodologia
    it1 = [("hoy", "Qué apostar hoy", True), ("sem-resumen", "Posibles valores", True), ("partidos-sem", "Partidos de la semana", True), ("graficas", "Gráficas", True),
           ("tarjeta", "Tarjeta para compartir", True), ("metodologia", "Metodología", True)]
    graf = (f'<details class="sec" id="graficas" data-frag="graficas"><span id="equipos"></span><summary>Gráficas de la semana: margen esperado, probabilidad de ganar y ventajas</summary>'
            f'<div class="fhost"><div class="cargando" role="status">Cargando…</div></div></details>')
    frags.append(f'<template id="frag-graficas">{c["graficas"]}</template>')
    n_val = sum(1 for d in js_ for m in _mercados(d["x"]) if m["edge"] >= c["me"])
    t1 = (f'{_subnav(it1)}{EX.hoy_html(js_, c, _mercados, _cuando, _veredicto_chip, vchip, tip)}<span id="sem-resumen"></span>'
          f'<h2 class="tabsec" id="picks-tit">Posibles valores de toda la semana ({n_val})</h2>'
          f'<p class="leyenda">Ordenados de mayor a menor ventaja. Toca uno para ver el partido.</p>{_picks(js_, c, nm)}{_alertas(js_)}'
          f'<details class="exp" id="resumen-det"><summary>Detalle del resumen y aviso importante</summary>{c["resumen"]}{c["importante"].replace("la sección «Mariscales» te avisa de los cambios", "las alertas 🏈 de cada partido te avisan de los cambios")}</details>'
          f'<span id="sem-vistazo"></span>{resumen_partidos(js_, nm, c)}{graf}<span id="tarjeta-ancla"></span>{EX.tarjeta_html(js_, c, _mercados, nm)}{_metodologia(c)}')
    # ---- Partidos
    t2 = ('<h2 id="partidos" class="tabsec">Partido por partido</h2>'
          '<details class="exp"><summary>Qué hay en cada partido</summary><p class="leyenda">Elige un partido y mira, en sub-pestañas: las apuestas contra el mercado, '
          'los Más de / Menos de de puntos con tus propias líneas y las combinadas, los props y touchdowns de jugadores y el matchup.</p></details>'
          f'{como}{_selector(js_, c)}<div class="gpanels" id="pgrid">{"".join(heads)}</div>{pp.get("datos", "")}')
    # ---- Jugadores y Props: solo LINEA AC, Touchdowns, Props destacados, Cruce ofensiva vs defensa, Ofensiva y Defensiva (en ese orden)
    proy = re.sub(r'<nav class="subnav">.*?</nav>', "", c.get("sec_proy") or "", count=1, flags=re.S)   # el menu de esta seccion ya esta arriba
    it3 = [("explorador", "LINEA AC", bool(c.get("sec_jug"))), ("td", "Touchdowns", bool(c.get("sec_td"))), ("props", "Props destacados", bool(c.get("sec_top"))),
           ("proyecciones", "Cruce ofensiva vs defensa", bool(proy)), ("proy-of", "Ofensiva", bool(proy)), ("proy-de", "Defensiva", bool(proy))]
    hay_j = any(c.get(k) for k in ("sec_jug", "sec_td", "sec_top", "sec_proy"))
    t3 = _subnav(it3) + c.get("sec_jug", "") + c.get("sec_td", "") + c.get("sec_top", "") + proy
    if not hay_j:
        t3 = '<div class="box">Esta pestaña se llena cuando el reporte incluye jugadores y props (corre el programa completo).</div>'
    t3 += (c.get("js_frag") or {}).get("jugadores", "") + (c.get("js_frag") or {}).get("proyecciones", "")
    # ---- Récord / Backtest (incluye la guia)
    it4 = [("kpis", "Resumen", bool(c.get("ev_all"))), ("mis-apuestas", "Mis apuestas", True), ("record", "Récord de elecciones", bool(c.get("sec_mc"))), ("marcador", "Marcador", bool(c.get("sec_mc"))),
           ("confianza", "Confianza", bool(c.get("cred"))), ("fiab-props", "Props y TD", bool(c.get("sec_cal"))), ("historial", "Historial", True), ("guia", "Guía", True)]
    guia = ('<details class="sec" id="guia"><summary>Guía: cómo leer este reporte y qué significan los «?»</summary>'
            '<h2 id="ayuda" class="tabsec">Cómo leer este reporte</h2>' + c["ayuda"] +
            '<h2 id="guia-tips" class="tabsec">Qué significan los «?»</h2><dl>' + "".join(f"<dt>{_esc(v[0])}</dt><dd>{_esc(v[1])}</dd>" for v in TIPS.values()) + "</dl></details>")
    t4 = (_subnav(it4) + _kpis(c) + EX.mis_apuestas_html(c) + c.get("sec_mc", "") + (f'<div id="confianza">{c["cred"]}</div>' if c.get("cred") else "") + c.get("sec_cal", "") +
          f'<h2 id="historial">Cómo le fue en semanas anteriores</h2>{c["hist_html"]}{guia}')
    n_g = len(js_)
    tabs = [("tab-picks", "Picks / Valor", t1, False), ("tab-partidos", "Partidos", t2, False), ("tab-jugadores", "Jugadores y Props", t3, True),
            ("tab-record", "Récord / Backtest", t4, True)]
    barra_nav = "".join(f'<button type="button" class="navbtn" data-t="{i}">{_esc(tt)}</button>' for i, tt, _, _ in tabs)
    cuerpo = ""
    for i, tt, h, lz in tabs:
        h = _sin_numeros(h)
        if lz:                                  # pestana pesada: se carga al abrirla (en el reporte local, ya viene dentro del mismo archivo)
            frags.append(f'<template id="frag-{i}">{h}</template>')
            cuerpo += f'<div class="tab" id="{i}" data-frag="{i}"><div class="cargando" role="status">Cargando…</div></div>'
        else:
            cuerpo += f'<div class="tab" id="{i}">{h}</div>'
    # mapa id -> fragmento (para que #ancla abra la pestana o partido correcto aunque aun no se haya cargado)
    idmap = {}
    for f in frags:
        m = re.match(r'<template id="frag-([^"]+)">', f)
        for i_ in re.findall(r'\bid="([^"]+)"', f):
            idmap.setdefault(i_, m.group(1))
    for i, tt, h, lz in tabs:
        idmap.setdefault(i, i)
    import json as _json
    idm = _json.dumps(idmap, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tipsj = _json.dumps({k: list(v) for k, v in TIPS.items()}, ensure_ascii=False, separators=(",", ":"))
    sol = '<svg class="i-sol" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
    luna = '<svg class="i-luna" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'
    ayu = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/></svg>'
    return f"""<main id="top">
<script>document.documentElement.classList.add('js')</script>
<a class="skip" href="#contenido">Saltar al contenido</a>
<header class="top"><div class="ttl"><span class="kick">NFL · Temporada {c["cur"]}</span><h1 id="resumen">Semana {c["wk"]}</h1></div>
<div class="hbtns"><button type="button" class="ibtn" id="guiabtn" title="Guía: cómo leer este reporte" aria-label="Guía: cómo leer este reporte">{ayu}</button>
<button type="button" class="ibtn" id="tema" title="Cambiar entre tema claro y oscuro" aria-label="Cambiar entre tema claro y oscuro" aria-pressed="false">{luna}{sol}</button></div>
<p class="sub"><span id="fresh" class="fresh" data-gen="{c["generado_iso"]}"></span><span>{c["sub"]}</span></p>
<div class="stale" id="stale" hidden role="alert"></div>{EX.banner_nueva()}</header>
<nav class="appnav" id="nav" aria-label="Secciones"><div class="seg">{barra_nav}</div></nav>
<div id="contenido">{cuerpo}</div>
<p class="foot">Datos: nflverse (play-by-play y líneas), ESPN, Ourlads, rbsdm, Kalshi y Open-Meteo. Los porcentajes salen de un modelo estadístico simple y no son garantía de nada.</p>
<button type="button" id="arriba" class="arriba" title="Volver arriba" aria-label="Volver arriba">↑</button>
<div id="sheet" class="box" role="dialog" aria-live="polite" hidden><b id="sheet-t"></b><p id="sheet-p"></p><button type="button" id="sheet-x">Entendido</button></div>
{EX.FORM_HTML}
<script type="application/json" id="ma-res">{EX.resultados_json(c["games"], c["cur"])}</script>
<script type="application/json" id="idmap">{idm}</script>
<script type="application/json" id="tips">{tipsj}</script>
<meta name="frag-base" content="">
{"".join(frags)}
</main>"""


CSS = """
.fhost>.cargando{padding:var(--s4) 0}
.mcard:focus-visible,.pick:focus-visible{outline:2px solid var(--border-strong);outline-offset:2px}
.mcard{cursor:pointer}.pick{cursor:pointer}
.pbl,.pcb{padding:var(--s3) var(--s4)!important;margin:var(--s3) 0;border-top:0!important;background:linear-gradient(var(--surface-2),var(--surface-2)) padding-box,var(--metal) border-box!important;border-width:1px!important}
.pbl::before,.pcb::before{content:"Mi línea / mi cuota";display:block;font-size:var(--fs-12);font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin-bottom:var(--s2)}
.pbl input.plineain,.pcb input.cspin,.pcb input.ctoin{min-height:var(--touch);font-size:16px}
input.pcq,input.cq{min-height:var(--touch);font-size:16px}
@media(max-width:700px){
 input.lin,input.cuo,input.cuu,input.cutd,input.elin{min-height:44px;width:92px!important;font-size:16px}input.leg{width:26px;height:26px}
 table.pt,table.pt tbody,table.pt tr,table.pt td{display:block;width:100%}
 table.pt tr.thr{display:none}
 table.pt tr[data-ptd],table.pt tr[data-mu]{border:var(--borde-ancho) solid transparent;border-radius:var(--r);background:linear-gradient(var(--surface),var(--surface)) padding-box,var(--metal) border-box;padding:var(--s3) var(--s4);margin:var(--s3) 0}
 table.pt td{display:flex;justify-content:space-between;align-items:center;gap:var(--s3);border:0;padding:5px 0;text-align:right}
 table.pt td::before{content:attr(data-label);flex:0 0 38%;color:var(--text-2);font-size:var(--fs-12);text-transform:uppercase;letter-spacing:.04em;text-align:left}
 table.pt td>*{max-width:62%}
 table.pt td.mn,table.pt td.hist{display:block;text-align:left}table.pt td.mn::before,table.pt td.hist::before{display:block;margin-bottom:2px}
 table.pt td:first-child{position:static;min-width:0}
 .scroll{max-height:none}
}
"""

JS = """
<script>
(function(){
var $=function(s,r){return (r||document).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
var BASE=(($('meta[name=frag-base]')||{}).content)||'',FRC={},IDM={},TIPS={},LOADED={};
try{IDM=JSON.parse($('#idmap').textContent);TIPS=JSON.parse($('#tips').textContent);}catch(e){}
window.__fr=window.__fr||[];
function altoNav(){var n=$('#nav');if(!n)return;document.documentElement.style.setProperty('--tabh',n.offsetHeight+'px');}
/* ---------- fragmentos (cada partido y cada pestana pesada se baja al abrirla) ---------- */
/* los fragmentos son .js (window.__F[nombre]=html): un <script src> funciona con doble clic (file://) y en GitHub Pages, sin servidor */
function cargaJs(name,url,intento){intento=intento||0;return new Promise(function(ok,mal){var W=window.__F=window.__F||{};if(W[name]!==undefined){ok(W[name]);return;}
 var sc=document.createElement('script');sc.src=url+(intento?'?r='+Date.now():'');sc.async=true;
 sc.onload=function(){sc.remove();if(W[name]!==undefined)ok(W[name]);else mal(new Error('vacio'));};
 sc.onerror=function(){sc.remove();if(intento<1)cargaJs(name,url,intento+1).then(ok,mal);else mal(new Error('red'));};document.head.appendChild(sc);});}
/* si la pagina quedo vieja (se publico una version nueva y los nombres con hash cambiaron) baja el indice nuevo y reintenta con la ruta actual */
function refrescar(name,t){var u=location.href.split('#')[0];return fetch(u,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);return r.text();}).then(function(h){
 var m=h.match(new RegExp('<template id="frag-'+name+'" data-src="([^"]+)"'));if(!m||m[1]===t.getAttribute('data-src'))throw new Error('igual');t.setAttribute('data-src',m[1]);return cargaJs(name,BASE+m[1]);});}
function traer(name){if(FRC[name])return FRC[name];var t=document.getElementById('frag-'+name);
 if(!t){FRC[name]=Promise.resolve(null);return FRC[name];}
 var src=t.getAttribute('data-src');
 FRC[name]=!src?Promise.resolve(t.innerHTML):src.slice(-3)==='.js'?cargaJs(name,BASE+src).catch(function(){return refrescar(name,t);}):fetch(BASE+src).then(function(r){if(!r.ok)throw new Error(r.status);return r.text();});
 FRC[name].catch(function(){delete FRC[name];});return FRC[name];}
function correr(host){$$('script',host).forEach(function(o){var n=document.createElement('script');if(o.type)n.type=o.type;if(o.id)n.id=o.id;n.text=o.textContent;o.parentNode.replaceChild(n,o);});}
function montar(name,host,after){if(!host)return Promise.resolve();if(LOADED[name]){return Promise.resolve();}
 return traer(name).then(function(h){if(h===null||LOADED[name])return;LOADED[name]=1;host.innerHTML=h;host.removeAttribute('data-cargando');
  correr(host);post(host);window.__fr.forEach(function(f){try{f(host);}catch(e){}});if(after)after(host);
 },function(){host.innerHTML='<div class="vacio"><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>No pude cargar esta parte.</b> Revisa tu conexión (o que la carpeta <code>f</code> esté junto a esta página) y <button type="button" class="chip" data-retry="'+name+'">reintentar</button> o <button type="button" class="chip" data-recargar="1">recargar la página</button> (puede que se haya publicado una versión nueva)</div></div>';});}
document.addEventListener('click',function(e){if(e.target.closest('[data-recargar]')){location.reload();return;}var r=e.target.closest('[data-retry]');if(r){var h=r.closest('[data-frag],.gp-body');if(h)cargarHost(h);}},true);
function hostDe(el){/* donde se monta el fragmento de un elemento con data-frag */
 if(el.classList.contains('gpanel'))return $('.gp-body',el);if(el.classList.contains('tab'))return el;return $('.fhost',el)||el;}
function cargarHost(el){var n=el.dataset.frag||(el.closest('[data-frag]')||{dataset:{}}).dataset.frag;var f=el.closest?el.closest('[data-frag]')||el:el;
 return montar(f.dataset.frag,hostDe(f),function(host){if(f.classList.contains('gpanel'))alistar(f);});}
window.__cargarTodo=function(){return Promise.all($$('[data-frag]').map(function(e){return cargarHost(e);}));};
/* ---------- pestanas ---------- */
var ALIAS={semana:'picks',calidad:'record',proyecciones:'jugadores',guia:'record','tab-semana':'tab-picks','tab-calidad':'tab-record','tab-proyecciones':'tab-jugadores','tab-guia':'tab-record'};
function showTab(id,quiet){id=ALIAS[id]||id;var t=document.getElementById(id);if(!t||!t.classList.contains('tab'))return Promise.resolve(false);
 $$('.tab').forEach(function(x){x.classList.toggle('on',x===t);});$$('.navbtn').forEach(function(b){if(b.dataset.t===id)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
 if(!quiet){try{history.replaceState(null,'','#tab='+id.replace('tab-',''));}catch(e){}}
 var p=t.dataset.frag?cargarHost(t):Promise.resolve();fixTables();return p.then(function(){fixTables();return true;});}
function alistar(p){if(!p.dataset.sub){var f=$('.sbtn',p);if(f)showSub(p,f.dataset.s,true);}}
function showSub(p,s,quiet){if(!p)return;var sps=$$('.sp',p);if(!sps.length){p.dataset.sub=s;$$('.sbtn',p).forEach(function(b){b.classList.toggle('on',b.dataset.s===s);b.setAttribute('aria-selected',b.dataset.s===s?'true':'false');});return;}
 var ok=sps.some(function(x){return x.dataset.s===s;});if(!ok)s=sps[0].dataset.s;
 sps.forEach(function(x){x.classList.toggle('on',x.dataset.s===s);});$$('.sbtn',p).forEach(function(b){b.classList.toggle('on',b.dataset.s===s);b.setAttribute('aria-selected',b.dataset.s===s?'true':'false');});p.dataset.sub=s;
 if(!quiet)urlGame(p);fixTables();}
function nombreSub(p){var b=$('.sbtn.on',p);return b?b.dataset.n:'';}
function urlGame(p){try{history.replaceState(null,'','#partido='+p.dataset.slug+'&tab='+nombreSub(p));}catch(e){}}
function showGame(g,quiet,sub){var p=$('.gpanel[data-g="'+g+'"]');if(!p)return Promise.resolve(false);
 $$('.gpanel').forEach(function(x){x.classList.toggle('on',x===p);});$$('.gchip').forEach(function(b){b.classList.toggle('on',b.dataset.g===g);});
 var c=$('.gchip.on');if(c&&c.scrollIntoView){try{c.scrollIntoView({block:'nearest',inline:'center'});}catch(e){}}
 return cargarHost(p).then(function(){var want=sub||p.dataset.sub||'ap';showSub(p,want,true);if(!quiet)urlGame(p);return true;});}
function subKey(n){var m={apuestas:'ap',puntos:'pt',props:'pr',matchup:'mu'};return m[n]||n;}
function openAncestors(el){var d=el.closest('details');while(d){d.open=true;d=d.parentElement?d.parentElement.closest('details'):null;}}
function aEl(el){openAncestors(el);setTimeout(function(){try{el.scrollIntoView({behavior:'smooth',block:'start'});}catch(e){el.scrollIntoView();}},40);}
function go(id){/* ancla: abre la pestana / partido / desplegable que la contiene (cargandolos si hace falta) */
 var el=document.getElementById(id);
 if(el){var tab=el.closest('.tab');var pr=tab?showTab(tab.id,true):Promise.resolve();var gp=el.closest('.gpanel');
  return pr.then(function(){if(gp){return showGame(gp.dataset.g,true).then(function(){var sp=el.closest('.sp');if(sp)showSub(gp,sp.dataset.s,true);aEl(el);return true;});}
   var fh=el.closest('details[data-frag]');if(fh&&fh.id!==id)openAncestors(el);aEl(el);return true;});}
 var fr=IDM[id];if(!fr)return Promise.resolve(false);
 var host=fr.indexOf('g-')===0?$('.gpanel[data-g="'+fr.slice(2)+'"]'):document.getElementById(fr)||$('[data-frag="'+fr+'"]');if(!host)return Promise.resolve(false);
 var tab=host.closest('.tab');var pr=tab?showTab(tab.id,true):Promise.resolve();
 return pr.then(function(){if(host.classList.contains('gpanel')){return showGame(host.dataset.g,true);}return cargarHost(host);}).then(function(){var e2=document.getElementById(id);if(e2){var gp2=e2.closest('.gpanel');if(gp2){var sp2=e2.closest('.sp');if(sp2)showSub(gp2,sp2.dataset.s,true);}aEl(e2);return true;}return false;});}
function irSel(){var s=$('#gsel');if(!s)return;var off=($('#nav')?$('#nav').offsetHeight:0)+4;window.scrollTo(0,Math.max(0,s.getBoundingClientRect().top+window.pageYOffset-off));}
function openGame(g,sub){showTab('tab-partidos',true).then(function(){return showGame(g,false,sub);}).then(function(){var s=$('#gsel');window.scrollTo(0,0);if(s)window.scrollTo(0,Math.max(0,s.getBoundingClientRect().top+window.pageYOffset-($('#nav')?$('#nav').offsetHeight:0)-4));});}
/* ---------- eventos ---------- */
document.addEventListener('click',function(e){var t=e.target;
 var tp=t.closest('.tip');if(tp){e.preventDefault();hoja(tp.dataset.tip);return;}
 if(t.closest('#sheet-x')){$('#sheet').hidden=true;return;}
 var nb=t.closest('.navbtn');if(nb){showTab(nb.dataset.t).then(function(){window.scrollTo(0,0);});return;}
 var gc=t.closest('.gchip');if(gc){showGame(gc.dataset.g);return;}
 var gg=t.closest('[data-go]');if(gg&&!t.closest('a')){openGame(gg.dataset.go,gg.dataset.tab?subKey(gg.dataset.tab):null);return;}
 var mc=t.closest('.mcard');if(mc&&!t.closest('button,a,input,select,.tip')){openGame(mc.dataset.g);return;}
 var sb=t.closest('.sbtn');if(sb){showSub(sb.closest('.gpanel'),sb.dataset.s);return;}
 var ga=t.closest('#gall');if(ga){var on=$('#pgrid').classList.toggle('todos');ga.classList.toggle('on',on);ga.textContent=on?'Mostrar uno':'Mostrar todos';if(on)$$('.gpanel').forEach(cargarHost);return;}
 if(t.closest('#tema')){ponerTema(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark',true);return;}
 if(t.closest('#guiabtn')){go('ayuda');return;}
 if(t.closest('#f-clear,[data-limpiar]')){limpiar();return;}
 var al=t.closest('button[data-al]');if(al){al.setAttribute('aria-pressed',al.getAttribute('aria-pressed')==='true'?'false':'true');filtrar();return;}
 var fv=t.closest('#f-val');if(fv){fv.setAttribute('aria-pressed',fv.getAttribute('aria-pressed')==='true'?'false':'true');filtrar();return;}
 if(!t.closest('#sheet')&&$('#sheet')&&!$('#sheet').hidden)$('#sheet').hidden=true;
 if(t.closest('#arriba')){window.scrollTo({top:0,behavior:'smooth'});return;}
 var a=t.closest('a[href^="#"]');if(a&&a.getAttribute('href').length>1){var id=a.getAttribute('href').slice(1);e.preventDefault();go(id);}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var sh=$('#sheet');if(sh&&!sh.hidden)sh.hidden=true;}
 if((e.key==='Enter'||e.key===' ')&&e.target.classList&&(e.target.classList.contains('pick')||e.target.classList.contains('mcard'))){e.preventDefault();openGame(e.target.dataset.go||e.target.dataset.g,e.target.dataset.tab?subKey(e.target.dataset.tab):null);}});
document.addEventListener('change',function(e){if(e.target.id==='f-eq'||e.target.id==='f-mk')filtrar();});
function hoja(k){var s=$('#sheet'),t=TIPS[k];if(!s||!t)return;$('#sheet-t').textContent=t[0];$('#sheet-p').textContent=t[1];s.hidden=false;var x=$('#sheet-x');if(x)x.focus();}
/* ---------- filtros de la pantalla de inicio ---------- */
function filtrar(){var eq=($('#f-eq')||{}).value||'',mk=($('#f-mk')||{}).value||'',val=($('#f-val')||{getAttribute:function(){return 'false';}}).getAttribute('aria-pressed')==='true';
 var als=$$('button[data-al][aria-pressed=true]').map(function(b){return b.dataset.al;});var n=0,tot=0;
 $$('#mlist .mcard,#sem-sig .mcard').forEach(function(c){tot++;var ok=true;var teams=(c.dataset.teams||'').split(' ');var v=(c.dataset.val||'').split(' ').filter(Boolean);
  if(eq&&teams.indexOf(eq)<0)ok=false;if(val&&(mk?v.indexOf(mk)<0:!v.length))ok=false;
  if(ok&&als.length){var a=(c.dataset.al||'').split(' ');ok=als.every(function(x){return a.indexOf(x)>=0;});}
  c.hidden=!ok;if(ok)n++;});
 $$('#picks .pick').forEach(function(p){var ok=true;if(eq&&(p.dataset.teams||'').split(' ').indexOf(eq)<0)ok=false;if(mk&&p.dataset.mk!==mk)ok=false;p.hidden=!ok;});
 var act=!!(eq||mk||val||als.length);var f=$('#f-n');if(f)f.textContent=act?(n+' de '+tot+' partidos'):(tot+' partidos');var fv=$('#f-vacio');if(fv)fv.hidden=n>0;
 var cl=$('#f-clear');if(cl)cl.hidden=!act;}
function limpiar(){var e=$('#f-eq'),m=$('#f-mk'),v=$('#f-val');if(e)e.value='';if(m)m.value='';if(v)v.setAttribute('aria-pressed','false');$$('button[data-al]').forEach(function(b){b.setAttribute('aria-pressed','false');});filtrar();}
/* ---------- tema claro / oscuro (oscuro por defecto; se recuerda en este navegador) ---------- */
function ponerTema(t,guardar){var r=document.documentElement;if(t==='dark')r.setAttribute('data-theme','dark');else r.removeAttribute('data-theme');
 var b=$('#tema');if(b)b.setAttribute('aria-pressed',t==='dark'?'true':'false');if(guardar){try{localStorage.setItem('nflmodelo.tema',t);}catch(e){}}}
(function(){var t='dark';try{t=localStorage.getItem('nflmodelo.tema')||'dark';}catch(e){}ponerTema(t==='light'?'light':'dark',false);})();
/* ---------- texto explicativo largo -> plegable; tablas con barra interna; tablas vacias ---------- */
function plegar(root){var roots=root.classList&&root.classList.contains('tab')?[root]:[];roots.forEach(function(r){var run=[];var kids=Array.prototype.slice.call(r.children);
 function cerrar(){if(!run.length)return;var d=document.createElement('details');d.className='exp';var s=document.createElement('summary');s.textContent='Cómo se lee';d.appendChild(s);
  run[0].parentNode.insertBefore(d,run[0]);run.forEach(function(p){d.appendChild(p);});run=[];}
 kids.forEach(function(k){if(k.tagName==='P'&&k.classList.contains('explain')&&!k.classList.contains('keep')&&k.textContent.length>150){run.push(k);}else{cerrar();}});cerrar();});}
function envolverTablas(root){$$('table',root).forEach(function(t){if(t.closest('.scroll,.chart,#parlay'))return;var w=document.createElement('div');w.className='scroll';t.parentNode.insertBefore(w,t);w.appendChild(t);});
 $$('img',root).forEach(function(i){i.setAttribute('loading','eager');i.setAttribute('decoding','async');});}
function etiquetar(root){$$('table.pt',root).forEach(function(t){var hd=null;$$('tr',t).forEach(function(r){if(!hd&&r.querySelector('th')&&!r.querySelector('td')){hd=[].map.call(r.children,function(c){return c.textContent.trim();});r.classList.add('thr');}});
 if(hd)$$('tr',t).forEach(function(r){if(r.classList.contains('thr'))return;[].forEach.call(r.children,function(c,i){if(hd[i]&&!c.dataset.label)c.dataset.label=hd[i];});});});}
function vacios(root){$$('table',root).forEach(function(t){var d=[].filter.call(t.querySelectorAll('tr'),function(r){return r.querySelector('td');});
 if(d.length)return;var v=document.createElement('div');v.className='vacio';
 v.innerHTML='<span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Sin datos por ahora.</b> '+(t.getAttribute('data-vacio')||'Esta tabla no tiene filas con los datos de hoy.')+'</div>';
 var w=t.closest('.scroll')||t;w.parentNode.replaceChild(v,w);});}
function post(root){plegar(root);envolverTablas(root);etiquetar(root);vacios(root);fixTables();}
function fixTables(){altoNav();$$('.tab.on .scroll').forEach(function(s){if(s.offsetParent===null)return;s.classList.toggle('ov',s.scrollWidth>s.clientWidth+4);});}
/* ---------- frescura: «Actualizado: … CDMX» y aviso si hay datos viejos en dia de partido ---------- */
function fresco(){var f=$('#fresh');if(!f)return;var gen=Date.parse(f.dataset.gen);if(isNaN(gen))return;var now=Date.now(),h=(now-gen)/36e5;
 function dur(x){if(x<1)return Math.max(1,Math.round(x*60))+' min';if(x<48)return (x<10?x.toFixed(1).replace('.0',''):Math.round(x))+' h';return Math.round(x/24)+' días';}
 var cd=new Date(gen-6*36e5),p=function(n){return (n<10?'0':'')+n;};var M=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
 var fecha=cd.getUTCDate()+' '+M[cd.getUTCMonth()]+' '+p(cd.getUTCHours())+':'+p(cd.getUTCMinutes())+' CDMX';
 var next=null,hoy=false;$$('.mcard[data-ko]').forEach(function(r){var k=Date.parse(r.dataset.ko);if(isNaN(k))return;if(k>now&&(next===null||k<next.k))next={k:k,m:r.dataset.match};if(Math.abs(k-now)<24*36e5)hoy=true;});
 var t='Actualizado: '+fecha+' (hace '+dur(Math.max(h,0))+')';if(next)t+=' · próximo partido: '+next.m+' en '+dur((next.k-now)/36e5);else t+=' · sin partidos próximos';
 f.textContent=t;var viejo=h>24&&hoy;f.classList.toggle('viejo',viejo);var s=$('#stale');if(s){s.hidden=!viejo;if(viejo)s.textContent='⚠ Estos datos tienen más de 24 horas y hoy hay partidos: pueden haber cambiado líneas, lesiones o mariscales.';}}
/* ---------- arranque / URL ---------- */
function fromHash(){var h=decodeURIComponent((location.hash||'').slice(1));if(!h)return Promise.resolve(false);
 var q={};h.split('&').forEach(function(kv){var i=kv.indexOf('=');if(i>0)q[kv.slice(0,i)]=kv.slice(i+1);else q._=kv;});
 if(q.partido){var p=$('.gpanel[data-slug="'+q.partido.toUpperCase()+'"]');if(p)return showTab('tab-partidos',true).then(function(){return showGame(p.dataset.g,true,q.tab?subKey(q.tab):null);}).then(function(r){irSel();return r;});return Promise.resolve(false);}
 if(q.game){return showTab('tab-partidos',true).then(function(){return showGame(q.game,true,q.tab?subKey(q.tab):null);});}
 if(q.tab&&!q.partido)return showTab('tab-'+q.tab,true);
 if(q._)return go(q._);return Promise.resolve(false);}
function init(){post(document.body);altoNav();
 if(!$$('.tab').length)return;
 fromHash().then(function(ok){if(!ok&&!$('.tab.on'))showTab('tab-picks',true);
  if(!$('.gpanel.on')){var now=Date.now(),pick=null;$$('.mcard[data-ko]').forEach(function(r){var k=Date.parse(r.dataset.ko);if(pick===null&&(isNaN(k)||k>now-3*36e5))pick=r.dataset.g;});
   var first=$('.gchip');if(!pick&&first)pick=first.dataset.g;if(pick){var p=$('.gpanel[data-g="'+pick+'"]');$$('.gpanel').forEach(function(x){x.classList.toggle('on',x===p);});$$('.gchip').forEach(function(b){b.classList.toggle('on',b.dataset.g===pick);});
    if($('#tab-partidos').classList.contains('on'))cargarHost(p);}}});
 filtrar();fresco();setInterval(fresco,60000);
 var up=$('#arriba');window.addEventListener('scroll',function(){if(up)up.classList.toggle('on',window.pageYOffset>700);},{passive:true});
 window.addEventListener('resize',fixTables);window.addEventListener('hashchange',function(){fromHash();});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>
"""

CSS = CSS + EX.CSS_EXTRA
JS = JS + EX.JS_EXTRA
