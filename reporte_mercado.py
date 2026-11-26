"""Reporte «¿Le gana el modelo al mercado?» (HTML autocontenido)."""
from __future__ import annotations

import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from reporte import C_A, C_B, C_MUTED, GRID, INK, INK2, SURF, _b64, _style, img_dual

NOMBRES = {"pass_yds": "Yardas por pase", "pass_cmp": "Pases completos", "pass_td": "TD de pase", "pass_int": "Intercepciones",
           "rush_yds": "Yardas por tierra", "rush_att": "Acarreos", "rec_yds": "Yardas de recepción", "rec": "Recepciones",
           "td": "Anotar touchdown"}

CSS = """
:root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e6e5e1;--card:#fff;--blue:#2a78d6;--org:#eb6834;--good:#1f7a43;--bad:#b3341a}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--ink:#f2f1ee;--ink2:#b3b2ac;--line:#33322f;--card:#1f1f1d;--blue:#6aa8f5;--org:#f08a5d;--good:#5fd08a;--bad:#ff8f77}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.2rem;margin:1.6em 0 .4em}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}
.explain{color:var(--ink2);font-size:.92rem;margin:.2em 0 .6em}.big{font-size:1.05rem}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}th{font-size:.74rem;color:var(--ink2);text-transform:uppercase;letter-spacing:.03em}
.good{color:var(--good);font-weight:600}.bad{color:var(--bad);font-weight:600}.mut{color:var(--ink2)}
img{max-width:100%;height:auto}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:800px){.grid2{grid-template-columns:1fr}}
"""


def _pct(x, d=1):
    return "—" if x is None or x != x else f"{x * 100:.{d}f}%"


def fig_brier(res) -> str:
    pm = res["por_mercado"]
    ks = sorted(pm, key=lambda k: pm[k]["brier_modelo"] - pm[k]["brier_mercado"])
    y = np.arange(len(ks))
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(ks) + 1.2))
    dif = [pm[k]["brier_modelo"] - pm[k]["brier_mercado"] for k in ks]
    ax.barh(y, dif, color=[C_B if v < 0 else C_A for v in dif], height=0.6)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels([NOMBRES.get(k, k) for k in ks])
    ax.set_xlabel("← el modelo es mejor        error del modelo − error del mercado        el mercado es mejor →", color=INK2, fontsize=8.5)
    _style(ax, "x")
    return _b64(fig)


def fig_calibracion(res) -> str:
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    ax.plot([0, 1], [0, 1], color=C_MUTED, lw=1.2, ls="--")
    for nombre, col, c in (("Mercado (Kalshi)", "calibracion_mercado", C_A), ("Modelo", "calibracion_modelo", C_B)):
        t = pd.DataFrame(res[col])
        ax.plot(t.pred, t.real, marker="o", color=c, lw=1.8, label=nombre, ms=5)
    ax.set_xlabel("probabilidad que dio", color=INK2)
    ax.set_ylabel("lo que pasó de verdad", color=INK2)
    ax.legend(frameon=False, fontsize=9)
    _style(ax, "both")
    return _b64(fig)


def construir(res: dict, ruta: Path, fuente: str = "") -> Path:
    g, pm = res["global"], res["por_mercado"]
    db = res.get("dif_brier")
    # veredicto automatico y honesto
    if db and db["hi90"] < 0:
        ver = ("<span class='good'>En esta muestra el modelo le gana al mercado</span> de forma consistente (el intervalo completo queda a su favor).")
    elif db and db["lo90"] > 0:
        ver = ("<span class='bad'>El mercado le gana al modelo</span> de forma consistente: no hay evidencia de que el modelo sepa algo que el precio no sepa.")
    else:
        ver = ("<b>No se puede distinguir al modelo del mercado</b> con esta muestra: la diferencia es menor que el ruido.")
    pesos = res["pesos_logit"]
    filas = ""
    for k, v in sorted(pm.items(), key=lambda kv: kv[1]["brier_modelo"] - kv[1]["brier_mercado"]):
        d = v["brier_modelo"] - v["brier_mercado"]
        ic = v.get("dif_brier")
        sig = ""
        if ic:
            sig = "sí" if (ic["hi90"] < 0 or ic["lo90"] > 0) else "no"
        filas += (f"<tr><td>{NOMBRES.get(k, k)}</td><td>{v['n']}</td><td>{v['brier_mercado']:.3f}</td><td>{v['brier_modelo']:.3f}</td>"
                  f"<td>{v['brier_mezcla50']:.3f}</td><td class='{'good' if d < 0 else 'bad'}'>{d:+.3f}</td><td>{sig}</td></tr>")
    ap = ""
    for u in (3, 5, 8, 12):
        for etq, k in (("todas las diferencias", f"todas_{u}"), ("sin las >10 pts (como el reporte)", f"filtro10_{u}")):
            a = res["apuestas"].get(k)
            if a:
                ap += (f"<tr><td>≥ {u} pts · {etq}</td><td>{a['n']}</td><td class='{'good' if a['roi'] > 0 else 'bad'}'>{_pct(a['roi'])}</td>"
                       f"<td>{_pct(a['lo90'])} a {_pct(a['hi90'])}</td></tr>")
    clv = "".join(f"<li>Apuestas con ventaja ≥ {int(c['umbral'] * 100)} pts, tomadas con el precio de 24 h antes: el precio se movió "
                  f"<b>{c['clv_medio'] * 100:+.1f} puntos</b> respecto a lo que pagaste (n = {c['n']}).</li>" for c in res.get("clv", []))
    sem = "".join(f"<tr><td>Temporada {w['season']} · semana {w['week']}</td><td>{w['n']}</td><td>{w['brier_mercado']:.3f}</td>"
                  f"<td>{w['brier_modelo']:.3f}</td></tr>" for w in res.get("por_semana", []))
    dtxt = (f"Diferencia de error (modelo − mercado): <b>{db['dif']:+.4f}</b>, intervalo al 90 %: {db['lo90']:+.4f} a {db['hi90']:+.4f}, "
            f"sobre {db['partidos']} partidos." if db else "")
    mezcla = res.get("dif_brier_mezcla25")
    mtxt = (f"Una mezcla con 25 % de modelo y 75 % de mercado cambia el error en {mezcla['dif']:+.4f} (intervalo {mezcla['lo90']:+.4f} a {mezcla['hi90']:+.4f})."
            if mezcla else "")
    m15 = res.get("dif_brier_mezcla20")
    if m15:
        mtxt += (f"<br>La que usa el reporte semanal (20 % modelo, 80 % mercado): {m15['dif']:+.4f} (intervalo {m15['lo90']:+.4f} a {m15['hi90']:+.4f}). "
                 "Si el intervalo incluye el cero, la mejora no se distingue del azar; en ningún caso es grande.")
    pp = "".join(f"<tr><td>{f['tramo']}</td><td>{f['n']}</td><td>{_pct(f['precio'])}</td><td>{_pct(f['real'])}</td>"
                 f"<td class='{'good' if f['roi_si'] > 0 else 'bad'}'>{_pct(f['roi_si'])}</td><td class='{'good' if f['roi_no'] > 0 else 'bad'}'>{_pct(f['roi_no'])}</td></tr>"
                 for f in res.get("por_precio", []))
    body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Modelo vs mercado</title><style>{CSS}</style></head><body><main>
<h1>¿Le gana el modelo al mercado?</h1>
<p class="explain">Para cada jugador y partido pasado se compara la probabilidad del modelo (calculada solo con datos anteriores al partido) con el precio de Kalshi justo antes del inicio, y con lo que pasó de verdad. {html.escape(fuente)}</p>
<div class="card big"><b>Veredicto.</b> {ver}<br><span class="explain">{dtxt}<br>{mtxt}</span></div>
<div class="card"><b>Muestra:</b> {res['n']:,} precios de {res['juegos']} partidos ({res['semanas']} semanas). Solo jugadores que sí jugaron, con diferencia entre compra y venta de 10 centavos o menos.</div>

<h2>1. Error por tipo de apuesta</h2>
<p class="explain">Brier = error medio de las probabilidades (0 = perfecto; 0.25 = tirar una moneda). Menor es mejor. «Significativa» dice si la diferencia es mayor que el ruido (intervalo al 90 %, remuestreando partidos).</p>
<div class="card"><div class="grid2"><div>{img_dual("Error por mercado", fig_brier, res)}</div>
<div><table><tr><th>Mercado</th><th>n</th><th>Mercado</th><th>Modelo</th><th>Mezcla 50/50</th><th>Dif.</th><th>Signif.</th></tr>{filas}</table></div></div></div>

<h2>2. ¿Qué tan honestas son las probabilidades?</h2>
<p class="explain">Si dicen «70 %», ¿pasa ~70 % de las veces? Cuanto más cerca de la línea punteada, mejor.</p>
<div class="card">{img_dual("Calibración", fig_calibracion, res)}</div>

<h2>3. ¿Cuánto pesa cada uno?</h2>
<div class="card"><p>Una regresión del resultado sobre ambos da un peso de <b>{pesos['mercado']:.2f}</b> al mercado y <b>{pesos['modelo']:.2f}</b> al modelo (en escala logit). Un peso del modelo cercano a cero significa que, una vez conocido el precio, el modelo casi no agrega información.</p></div>

<h2>4. Apuestas simuladas</h2>
<p class="explain">Un contrato por cada escalón donde el modelo ve ventaja neta (después de comisión) al precio de cierre. ROI = ganancia / dinero puesto. El intervalo al 90 % remuestrea partidos; si incluye el cero, no se distingue de la suerte.</p>
<div class="card"><table><tr><th>Regla</th><th>Apuestas</th><th>ROI</th><th>Intervalo 90 %</th></tr>{ap}</table></div>
<div class="card"><b>Movimiento del precio (CLV).</b><ul>{clv}</ul><span class="explain">Si el modelo supiera algo, el precio debería moverse hacia él antes del partido (valor positivo).</span></div>

<h2>5. ¿Está sesgado el precio?</h2>
<p class="explain">Si siempre compraras «Más de» (o siempre «Menos de») en cada tramo de precio, ¿cuánto ganarías o perderías después de comisión y diferencia entre compra y venta? Muestra si los favoritos o los improbables están mal pagados. No depende del modelo.</p>
<div class="card"><table><tr><th>Precio de «Más de»</th><th>n</th><th>Precio medio</th><th>Pasó</th><th>ROI comprar «Más de»</th><th>ROI comprar «Menos de»</th></tr>{pp}</table></div>

<h2>6. Semana por semana</h2>
<div class="card"><table><tr><th>Semana</th><th>n</th><th>Error mercado</th><th>Error modelo</th></tr>{sem}</table></div>

<h2>Límites</h2>
<div class="card"><ul class="explain"><li>Los precios son de Kalshi, que tiene poca liquidez; no son lo mismo que DraftKings.</li>
<li>Se compara un escalón por jugador (el de más volumen), que suele estar cerca de 50-50.</li>
<li>Los escalones del mismo partido están correlacionados: por eso los intervalos remuestrean partidos y no apuestas.</li>
<li>Se descartan jugadores que no jugaron; al cierre el mercado ya sabe quiénes son inactivos, así que el sesgo es pequeño.</li>
<li>No es asesoría financiera.</li></ul></div>
</main></body></html>"""
    ruta.write_text(body, encoding="utf8")
    return ruta
