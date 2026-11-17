"""Mariscales (QB): quien juega de verdad esta semana frente al titular habitual de cada equipo.

Que hace
  * Detecta, para cada partido pendiente con proyeccion de props, si el QB esperado (el que usan los props: Kalshi > Ourlads >
    depth chart, sin los lesionados Out/Doubtful) es distinto al titular habitual del equipo (el que mas partidos abrio de los
    ultimos 8) o si el titular habitual esta lesionado / en duda.
  * Estima cuanto pesa el cambio segun el Elo del QB (25 puntos de Elo ~ 1 punto de spread). Es solo referencia: un QB sin
    historial cuenta como «promedio» (0), que suele ser optimista para un suplente.
  * Mide con datos historicos si el mercado ya descuenta esos cambios (`medir`).

Lo que NO hace (a proposito)
  La medicion (2006-2025) muestra que cuando juega un QB distinto el mercado ya lo descuenta: la linea no se equivoca mas de
  lo normal y el error no crece. Por eso las probabilidades NO se corrigen por el cambio de QB; el modelo B ya parte de la linea,
  que sabe quien juega. El aviso sirve para que revises la noticia antes de apostar y para saber que los props de ese QB
  tienen mas incertidumbre (poco historial).
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd

import elo as EL

VENTANA = 8            # partidos para definir al titular habitual
MIN_TITULAR = 4        # abridos de los ultimos 8 para considerarlo «habitual»
POCOS = 3              # menos de esto = «sin historial» (el Elo del QB es poco fiable)


# ------------------------------------------------------------------------------------------ datos
def _nombre_norm(s) -> str:
    try:
        from fuentes_web import nombre_norm
        return nombre_norm(s)
    except Exception:
        return str(s).lower().strip()


def secuencia(games: pd.DataFrame) -> dict:
    """Por equipo: lista cronologica de (qb_id, qb_name) de los partidos ya jugados."""
    g = games[games.result.notna() & games.home_qb_id.notna() & games.away_qb_id.notna()].sort_values(["gameday", "game_id"])
    seq: dict = {}
    for r in g.itertuples():
        seq.setdefault(r.home_team, []).append((r.home_qb_id, r.home_qb_name))
        seq.setdefault(r.away_team, []).append((r.away_qb_id, r.away_qb_name))
    return seq


def habitual(seq: list) -> dict | None:
    """Titular habitual = quien abrio mas de los ultimos 8 (si empatan, el mas reciente)."""
    if not seq:
        return None
    ult = seq[-VENTANA:]
    cuenta: dict = {}
    for i, (q, n) in enumerate(ult):
        c = cuenta.setdefault(q, [0, i, n])
        c[0] += 1
        c[1] = i
    q = max(cuenta, key=lambda k: (cuenta[k][0], cuenta[k][1]))
    return {"id": q, "name": cuenta[q][2], "abrio": cuenta[q][0], "de": len(ult), "ultimo": seq[-1][0] == q}


def elo_por_qb(games: pd.DataFrame, cur: int) -> tuple[dict, dict]:
    """Elo (aporte del QB) despues del ultimo partido jugado de cada QB, y cuantos partidos lleva en el Elo."""
    h = EL.elo_historial(games, desde=cur - 1, **EL.PARAMS_REC)
    Q, n = {}, {}
    for r in h.itertuples():
        if pd.isna(r.d_h):
            continue
        for q, e, d in ((r.qb_h, r.elo_qb_h, r.dq_h), (r.qb_a, r.elo_qb_a, r.dq_a)):
            if q:
                Q[q] = float(e + d)
                n[q] = n.get(q, 0) + 1
    return Q, n


# ------------------------------------------------------------------------------------------ analisis
def analizar(r: dict, extras: dict | None, log=print) -> dict:
    """{game_id: {"home": {...}, "away": {...}, "avisos": [texto], "alerta": bool}} para los partidos con props."""
    if not extras or extras.get("P") is None or len(extras["P"]) == 0:
        return {}
    games, cur = r["games"], r["cur"]
    P, excl = extras["P"], extras.get("excl")
    seq = secuencia(games)
    Q, nQ = elo_por_qb(games, cur)
    qbs = P[P.position == "QB"]
    fuera = {}
    if excl is not None and len(excl):
        for e in excl[excl.position == "QB"].itertuples():
            fuera[(e.team, _nombre_norm(e.name))] = (e.estado, getattr(e, "lesion", "") or "")
    md = extras.get("mov_det")                       # traspasos: quien se fue y quien llego (ver movimientos.py)
    se_fue, llego = {}, {}
    if md is not None and len(md):
        for m in md[md.position == "QB"].itertuples():
            se_fue[(m.de, m.player_id)] = m.a
            if pd.isna(m.semana):
                llego[(m.a, m.player_id)] = m.de
    out: dict = {}
    pend = games[games.game_id.isin(P.game_id.unique())]
    for g in pend.itertuples():
        lados = {}
        for lado, team in (("home", g.home_team), ("away", g.away_team)):
            hab = habitual(seq.get(team, []))
            fila = qbs[(qbs.game_id == g.game_id) & (qbs.team == team)]
            exp = fila.iloc[0] if len(fila) else None
            d = {"team": team, "habitual": hab, "esperado": None, "estado": "sin_dato", "texto": "", "dpts": 0.0, "sin_hist": False}
            if exp is not None:
                abr = nQ.get(exp.player_id, 0)
                d["esperado"] = {"id": exp.player_id, "name": exp["name"], "estado": exp.estado or "", "p_juega": float(exp.p_juega) if "p_juega" in exp and pd.notna(exp.p_juega) else 1.0,
                                 "n_prior": int(exp.n_prior) if pd.notna(exp.n_prior) else 0, "elo": Q.get(exp.player_id, 0.0)}
                d["sin_hist"] = abr < POCOS
            if hab is None or exp is None:
                lados[lado] = d
                continue
            hab_fuera = fuera.get((team, _nombre_norm(hab["name"])))
            igual = exp.player_id == hab["id"]
            if not igual:
                d["estado"] = "cambio"
                d["dpts"] = (d["esperado"]["elo"] - Q.get(hab["id"], 0.0)) / EL.PTS_POR_PUNTO
                if (team, hab["id"]) in se_fue:
                    why = f"{hab['name']} (traspasado a {se_fue[(team, hab['id'])]})"
                elif hab_fuera:
                    why = f"{hab['name']} ({'baja' if hab_fuera[0] == 'Out' else 'dudoso'}{' · ' + hab_fuera[1] if hab_fuera[1] else ''})"
                else:
                    why = f"{hab['name']} no aparece como lesionado esta semana (puede ser decisión técnica o lesión larga)"
                dn = "sin historial: contado como mariscal promedio, puede ser optimista" if d["sin_hist"] else f"{d['esperado']['n_prior']} partidos previos"
                if (team, exp.player_id) in llego:
                    dn += f"; llegó por traspaso desde {llego[(team, exp.player_id)]} y aún no juega con el equipo"
                d["texto"] = f"{team}: abre {exp['name']} ({dn}) en vez de {why}."
            else:
                if d["esperado"]["estado"] in ("Questionable", "Doubtful"):
                    d["estado"] = "duda"
                    d["texto"] = (f"{team}: el titular {exp['name']} está {d['esperado']['estado']}"
                                  f" (probabilidad de jugar ≈ {d['esperado']['p_juega'] * 100:.0f}%). Revisa la noticia antes del partido.")
                elif not hab["ultimo"]:
                    d["estado"] = "regresa"
                    d["texto"] = f"{team}: regresa {exp['name']}, que no abrió el último partido del equipo."
                else:
                    d["estado"] = "normal"
            lados[lado] = d
        avisos = [x["texto"] for x in lados.values() if x["texto"]]
        out[g.game_id] = {**lados, "avisos": avisos, "alerta": any(x["estado"] in ("cambio", "duda") for x in lados.values()),
                          "margen_pts": lados["home"]["dpts"] - lados["away"]["dpts"], "sem": int(g.week)}
    return out


# ------------------------------------------------------------------------------------------ medicion historica
def medir(games: pd.DataFrame, desde: int = 2006) -> dict | None:
    """Cuando juega un QB distinto al habitual: ¿el mercado se equivoca mas? (todos los partidos jugados con linea)."""
    g = games[(games.season >= desde) & games.result.notna() & games.home_qb_id.notna() & games.away_qb_id.notna()
              & games.spread_line.notna() & games.total_line.notna()].sort_values(["gameday", "game_id"])
    hist: dict = {}
    filas = []
    for r in g.itertuples():
        e_m, e_t = r.result - r.spread_line, r.total - r.total_line
        cam, deb = [], []
        for lado, team, q in (("h", r.home_team, r.home_qb_id), ("a", r.away_team, r.away_qb_id)):
            h = hist.setdefault(team, [])
            ult = h[-VENTANA:]
            if len(ult) >= MIN_TITULAR:
                vc = pd.Series(ult).value_counts()
                if vc.iloc[0] >= MIN_TITULAR:
                    c = q != vc.index[0]
                    cam.append((lado, c, h.count(q) < 2))
        for lado, c, nuevo in cam:
            filas.append({"cambio": c, "nuevo": c and nuevo, "ats": e_m if lado == "h" else -e_m})
        filas_g = {"g": r.game_id, "cambio": any(c for _, c, _ in cam), "ok": len(cam) == 2, "e_m": e_m, "e_t": e_t}
        filas.append({"juego": filas_g})
        hist[r.home_team].append(r.home_qb_id)
        hist[r.away_team].append(r.away_qb_id)
    eq = pd.DataFrame([f for f in filas if "ats" in f])
    jg = pd.DataFrame([f["juego"] for f in filas if "juego" in f])
    jg = jg[jg.ok]
    if eq.empty or jg.empty:
        return None

    def _s(x):
        return float(x.std() / max(len(x), 1) ** 0.5)
    c, n = eq[eq.cambio], eq[~eq.cambio]
    nuevo = eq[eq.nuevo]
    jc, jn = jg[jg.cambio], jg[~jg.cambio]
    return {"n_eq": len(eq), "n_cambio": len(c), "pct_cambio": len(c) / len(eq),
            "ats_cambio": float(c.ats.mean()), "ats_cambio_se": _s(c.ats), "cubre_cambio": float((c.ats > 0).mean()),
            "ats_normal": float(n.ats.mean()), "ats_normal_se": _s(n.ats), "cubre_normal": float((n.ats > 0).mean()),
            "n_nuevo": len(nuevo), "ats_nuevo": float(nuevo.ats.mean()) if len(nuevo) else np.nan, "ats_nuevo_se": _s(nuevo.ats) if len(nuevo) > 1 else np.nan,
            "n_jc": len(jc), "n_jn": len(jn), "sd_m_cambio": float(jc.e_m.std()), "sd_m_normal": float(jn.e_m.std()),
            "tot_cambio": float(jc.e_t.mean()), "tot_cambio_se": _s(jc.e_t), "tot_normal": float(jn.e_t.mean()), "tot_normal_se": _s(jn.e_t),
            "desde": int(desde)}


# ------------------------------------------------------------------------------------------ HTML
def nota_juego(an: dict | None, game_id: str) -> str:
    """Aviso corto para la tarjeta del partido (vacio si no hay nada que avisar)."""
    a = (an or {}).get(game_id)
    if not a or not a["avisos"]:
        return ""
    return ('<div class="qbnota"><b>Mariscales:</b> ' + " ".join(html.escape(t) for t in a["avisos"]) + "</div>")


def _celda(d: dict) -> str:
    e = d["esperado"]
    if e is None:
        return '<td class="l">sin dato</td>'
    cls = {"cambio": "qb-c", "duda": "qb-d", "regresa": "qb-r"}.get(d["estado"], "")
    h = d["habitual"]
    sub = ""
    if d["estado"] == "cambio" and h:
        sub = f'<small>habitual: {html.escape(h["name"])} · peso según Elo {d["dpts"]:+.1f} pts{" (sin historial)" if d["sin_hist"] else ""}</small>'
    elif d["estado"] == "duda":
        sub = f'<small>{html.escape(e["estado"])} · juega ≈{e["p_juega"] * 100:.0f}%</small>'
    elif d["estado"] == "regresa":
        sub = "<small>regresa tras no abrir el último partido</small>"
    return f'<td class="l {cls}"><b>{html.escape(str(e["name"]))}</b>{sub}</td>'


def html_qb(an: dict, med: dict | None, nombre=lambda t: t) -> str:
    if not an:
        return ""
    juegos = sorted(an.items(), key=lambda kv: (not kv[1]["alerta"], kv[1]["sem"], kv[0]))
    n_al = sum(1 for _, a in juegos if a["alerta"])
    filas = []
    for gid, a in juegos:
        h, v = a["home"], a["away"]
        marca = "⚠ " if a["alerta"] else ""
        tit = f'{marca}{html.escape(nombre(v["team"]))} @ {html.escape(nombre(h["team"]))}'
        filas.append(f'<tr class="{"qb-al" if a["alerta"] else ""}"><td class="l">{tit}</td>{_celda(v)}{_celda(h)}</tr>')
    tabla = ('<div class="scroll"><table class="qbt"><thead><tr><th class="l">Partido</th><th class="l">Visita: mariscal que abre</th>'
             '<th class="l">Local: mariscal que abre</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table></div>")
    hist = ""
    if med:
        hist = (f'<div class="box"><h4>¿El mercado ya sabe del cambio? Sí.</h4><p class="explain">Revisé {med["n_eq"]:,} equipos-partido desde {med["desde"]} '
                f'({med["pct_cambio"] * 100:.0f}% con un mariscal distinto al habitual). Con el titular de siempre el equipo cubre el spread el '
                f'<b>{med["cubre_normal"] * 100:.0f}%</b> de las veces; con un mariscal distinto, el <b>{med["cubre_cambio"] * 100:.0f}%</b> '
                f'(diferencia contra la línea: {med["ats_cambio"]:+.1f} ± {med["ats_cambio_se"]:.1f} pts). Para QB con menos de 2 abridos previos con ese equipo '
                f'({med["n_nuevo"]} casos) el resultado fue {med["ats_nuevo"]:+.1f} ± {med["ats_nuevo_se"]:.1f} pts: un descuento algo mayor al que da el mercado, '
                f'pero dentro del ruido. La dispersión del resultado casi no cambia ({med["sd_m_cambio"]:.1f} vs {med["sd_m_normal"]:.1f} pts) y en el total los partidos '
                f'con cambio quedaron {med["tot_cambio"] - med["tot_normal"]:+.1f} pts por debajo de lo normal contra la línea (dato débil: ±{(med["tot_cambio_se"] ** 2 + med["tot_normal_se"] ** 2) ** 0.5:.1f}). '
                f'<b>Conclusión:</b> no corrijo las probabilidades por el cambio de QB; la línea ya lo incluye. Esta tabla sirve para <b>enterarte</b>, no para apostar contra el mercado.</p></div>')
    return f"""<h2 id="qb">Mariscales: ¿juega el titular?</h2>
<p class="explain">Para cada partido de esta semana, el mariscal que usan los props (Kalshi, Ourlads o depth chart, sin los lesionados) frente al titular habitual del equipo (el que abrió más de los últimos {VENTANA} partidos).
<b>{n_al} partido(s) con aviso</b> ⚠ (arriba). «Peso según Elo» es cuántos puntos de spread vale el cambio según el Elo de los mariscales; con QB sin historial es solo una referencia optimista.
Los props de un QB con pocos partidos usan el promedio de debutantes de su ronda del draft y tienen más incertidumbre.</p>
{tabla}
{hist}"""


CSS = """
.qbt{width:100%;border-collapse:collapse;font-size:.88rem}.qbt th,.qbt td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.qbt td.l,.qbt th.l{text-align:left}.qbt small{display:block;color:var(--ink2);font-size:.74rem}
.qbt tr.qb-al td:first-child{font-weight:600}.qbt td.qb-c{background:rgba(217,130,43,.16)}.qbt td.qb-d{background:rgba(214,176,40,.16)}.qbt td.qb-r{background:rgba(74,127,181,.12)}
.qbnota{font-size:.82rem;background:rgba(217,130,43,.14);border-radius:8px;padding:6px 8px;margin:6px 0}
.pqb{background:rgba(217,130,43,.14);border-radius:8px;padding:6px 8px}
"""
