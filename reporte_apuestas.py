"""Reporte «Mis apuestas» (HTML autocontenido): resultados reales, ROI con incertidumbre, acierto, calibracion y CLV."""
from __future__ import annotations

import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import apuestas as A
from reporte import C_A, C_B, C_MUTED, INK2, _b64, _style
from reporte_mercado import CSS, NOMBRES

TIPOS = {"prop": "Jugador", "ml": "Ganador", "spread": "Handicap", "total": "Total"}


def _pct(x, d=1, signo=False):
    return "—" if x is None or x != x else (f"{x * 100:+.{d}f}%" if signo else f"{x * 100:.{d}f}%")


def _money(x):
    return "—" if x is None or x != x else f"{x:+,.2f}"


def fig_curva(d: pd.DataFrame) -> str:
    x = A.numericas(d)
    x = x[x.resultado.isin(["gano", "perdio"])].copy()
    x["_o"] = pd.to_numeric(x.id, errors="coerce")
    x = x.sort_values("_o")
    acum = x.ganancia.fillna(0).cumsum().to_numpy()
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    ax.axhline(0, color=INK2, lw=1)
    ax.plot(np.arange(1, len(acum) + 1), acum, color=C_B if acum[-1] >= 0 else C_A, lw=2)
    ax.set_xlabel("apuestas liquidadas (en orden)", color=INK2)
    ax.set_ylabel("ganancia acumulada", color=INK2)
    _style(ax, "y")
    return _b64(fig)


def construir(d: pd.DataFrame, ruta: Path) -> Path:
    r = A.resumen(d)
    liq = r.get("liquidadas", 0)
    if liq == 0:
        ver = ("Todavía no hay apuestas liquidadas. Cuando registres apuestas y terminen los partidos, aquí verás tu ganancia real, "
               "tu acierto frente a lo esperado y si le ganas al precio de cierre (CLV).")
        kpis = ""
        curva = ""
    else:
        roi, lo, hi = r["roi"], r["roi_lo90"], r["roi_hi90"]
        if hi < 0:
            ver = f"Hasta ahora pierdes dinero y la diferencia ya no parece azar (ROI {_pct(roi, 1, True)}, intervalo {_pct(lo, 1, True)} a {_pct(hi, 1, True)})."
        elif lo > 0:
            ver = f"Hasta ahora ganas y la diferencia no parece azar (ROI {_pct(roi, 1, True)}, intervalo {_pct(lo, 1, True)} a {_pct(hi, 1, True)}). Confírmalo con más apuestas."
        else:
            ver = (f"Con {liq} apuestas liquidadas todavía no se distingue de la suerte: ROI {_pct(roi, 1, True)}, pero el intervalo al 90 % va de "
                   f"{_pct(lo, 1, True)} a {_pct(hi, 1, True)}. Es normal: hacen falta cientos de apuestas.")
        k = [("Apuestas liquidadas", f"{liq}"), ("Monto apostado", f"{r['monto']:,.2f}"), ("Ganancia", _money(r["ganancia"])), ("ROI", _pct(roi, 1, True)),
             ("Acierto real", _pct(r["acierto"])), ("Acierto que implican los precios", _pct(r["p_impl"]))]
        if "clv_prob_medio" in r:
            k.append(("CLV medio", f"{r['clv_prob_medio']:+.1f} pts de prob. ({_pct(r['clv_prob_pos'], 0)} de las veces positivo)"))
        kpis = '<div class="card"><table>' + "".join(f"<tr><td>{a}</td><td><b>{b}</b></td></tr>" for a, b in k) + "</table></div>"
        curva = f'<h2>Ganancia acumulada</h2><img alt="Ganancia acumulada" src="data:image/png;base64,{fig_curva(d)}">'
    cal = ""
    if r.get("n_prob", 0) >= 5:
        cal = (f'<div class="card"><b>¿Acertó el modelo?</b> En {r["n_prob"]} apuestas con probabilidad del modelo registrada: el modelo decía en promedio '
               f'{_pct(r["prob_modelo_media"])} de ganar, ganaste {_pct(r["acierto_con_prob"])}. Error (Brier): modelo {r["brier_modelo"]:.3f} vs precio {r["brier_precio"]:.3f} '
               f'(menor es mejor).<div class="explain">Con pocas apuestas esto fluctúa mucho; ya con más de 100 empieza a decir algo.</div></div>')

    def tabla(nombre, t, mapa=None):
        if not t or not t.get("n"):
            return ""
        filas = "".join(f"<tr><td>{html.escape(mapa.get(k, str(k)) if mapa else str(k))}</td><td>{int(n)}</td><td>{m:,.2f}</td><td class='{'good' if g > 0 else 'bad'}'>{g:+,.2f}</td>"
                        f"<td class='{'good' if ro > 0 else 'bad'}'>{_pct(ro, 1, True)}</td><td>{_pct(ac)}</td></tr>"
                        for k, n, m, g, ro, ac in zip(t[list(t)[0]], t["n"], t["monto"], t["ganancia"], t["roi"], t["acierto"]))
        return f"<h2>{nombre}</h2><div class='card'><table><tr><th></th><th>Apuestas</th><th>Monto</th><th>Ganancia</th><th>ROI</th><th>Acierto</th></tr>{filas}</table></div>"
    por = ""
    if liq:
        props = A.resumen(d[d.tipo == "prop"]) if (d.tipo == "prop").any() else {}
        por = tabla("Por tipo", r.get("por_tipo"), TIPOS) + tabla("Por mercado (jugadores)", props.get("por_mercado"), NOMBRES)
    x = d.copy()
    x["_o"] = pd.to_numeric(x.id, errors="coerce")
    x = x.sort_values("_o", ascending=False)
    cls = {"gano": "good", "perdio": "bad"}
    filas = []
    for t in x.itertuples():
        quien = html.escape(t.jugador) if t.tipo == "prop" else html.escape(t.equipo)
        mk = NOMBRES.get(t.mercado, t.mercado) if t.tipo == "prop" else TIPOS.get(t.tipo, t.tipo)
        filas.append(f"<tr><td>{t.id}</td><td>{t.temporada}-S{t.semana}</td><td>{quien}<br><small class='mut'>{html.escape(str(t.equipo))}{(' vs ' + html.escape(str(t.rival))) if t.rival else ''}</small></td>"
                     f"<td>{html.escape(mk)}</td><td>{html.escape((str(t.lado) + ' ' + str(t.linea)).strip())}</td><td>{html.escape(str(t.cuota))}</td><td>{html.escape(str(t.monto))}</td>"
                     f"<td class='{cls.get(t.resultado, 'mut')}'>{t.resultado}</td><td>{html.escape(str(t.estadistica))}</td><td>{html.escape(str(t.ganancia))}</td><td>{html.escape(str(t.clv))}</td></tr>")
    necesarias = A.apuestas_para_detectar()
    body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mis apuestas</title><style>{CSS}</style></head><body><main>
<h1>Mis apuestas</h1>
<p class="explain">Tus apuestas reales, liquidadas con los resultados oficiales. Aquí se ve si el método funciona con tu dinero, sin cuentos.</p>
<div class="card big"><b>Veredicto.</b> {ver}<div class="explain">Pendientes: {r['pendientes']} · anuladas/empates: {r['anuladas']}.</div></div>
{kpis}{cal}{curva}{por}
<h2>Todas tus apuestas</h2>
<div class="card" style="overflow-x:auto"><table><tr><th>#</th><th>Semana</th><th>Apuesta</th><th>Mercado</th><th>Lado y línea</th><th>Cuota</th><th>Monto</th><th>Resultado</th><th>Real</th><th>Ganancia</th><th>CLV</th></tr>
{''.join(filas) or '<tr><td colspan="11">Aún no hay apuestas registradas.</td></tr>'}</table></div>
<h2>Cómo leerlo</h2>
<div class="card"><p class="explain"><b>ROI</b> = ganancia ÷ monto apostado. <b>CLV</b> (valor frente al cierre) = si apostaste a un precio mejor que el último antes del partido: es la señal más rápida de que tu método tiene valor, porque el precio de cierre es el más informado.
Si tu CLV promedio es positivo de forma sostenida, vas bien aunque el ROI de pocas semanas salga negativo; si es negativo, el mercado se movió contra ti.<br><br>
<b>Ojo con la suerte:</b> para distinguir un ROI verdadero de +3 % del azar harían falta unas <b>{necesarias:,}</b> apuestas. Con unas decenas, cualquier resultado puede ser suerte. Por eso cuenta más el CLV y la calibración que el ROI de unas semanas.<br><br>
Los empates y partidos donde el jugador no juega se anulan (en Kalshi, si el jugador no juega, el «Sí» pierde). No es asesoría financiera: apuesta solo lo que puedas perder y donde sea legal.</p></div>
</main></body></html>"""
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text(body, encoding="utf-8")
    return ruta
