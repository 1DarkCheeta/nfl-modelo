"""Genera el reporte semanal en HTML (un solo archivo, con graficos incrustados)."""
from __future__ import annotations

import base64
import html
import io
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin ventanas: funciona dentro de IDLE
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from predict import HIST, veredicto

ROOT = Path(__file__).parent
REPORTES = ROOT / "reportes"
REPORTES.mkdir(exist_ok=True)

# Colores (paleta categorica validada: azul / naranja; gris para el mercado)
from ui_css import COL                      # los colores de las graficas salen de los mismos tokens que la pagina
SURF, INK, INK2, GRID = COL["surface"], COL["text"], COL["text-2"], COL["border-subtle"]
C_B, C_A, C_MUTED = COL["info"], COL["aviso"], "#5F7799"

TEAMS = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
         "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
         "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
         "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
         "LAC": "Los Angeles Chargers", "LA": "Los Angeles Rams", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
         "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
         "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
         "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def nm(t: str) -> str:
    return TEAMS.get(t, t)


def fecha(d) -> str:
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}"


# ------------------------------------------------------------------ graficos
def _b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _style(ax, grid="x"):
    ax.set_facecolor("none")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=15)
    ax.grid(axis=grid, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def _labels(res):
    return [f"{a} @ {h}" for a, h in zip(res.away_team, res.home_team)]


def fig_margenes(res) -> str:
    n = len(res)
    fig, ax = plt.subplots(figsize=(6.0, 0.46 * n + 2.4), facecolor="none")
    _style(ax)
    y = np.arange(n)
    vals = np.vstack([res.margen_mercado, res.pred_mA, res.pred_mB])
    ax.hlines(y, vals.min(0), vals.max(0), color=C_MUTED, lw=2, zorder=1)
    ax.axvline(0, color=INK2, lw=1)
    ax.scatter(res.margen_mercado, y, marker="D", s=55, color=INK2, zorder=3, label="Mercado (línea)")
    ax.scatter(res.pred_mA, y, marker="o", s=75, facecolors=SURF, edgecolors=C_A, linewidths=2, zorder=3, label="Modelo A (solo ratings)")
    ax.scatter(res.pred_mB, y, marker="o", s=55, color=C_B, edgecolors=SURF, linewidths=1, zorder=4, label="Modelo B (decisión)")
    ax.set_yticks(y, _labels(res))
    ax.invert_yaxis()
    ax.set_xlabel("← gana la visita   ·   puntos esperados   ·   gana el local →", color=INK2, fontsize=15)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=1, frameon=False, fontsize=15, labelcolor=INK2)
    return _b64(fig)


def fig_probabilidad(res) -> str:
    n = len(res)
    fig, ax = plt.subplots(figsize=(6.0, 0.46 * n + 2.4), facecolor="none")
    _style(ax)
    y = np.arange(n)
    mk, mb = res.p_gana_local_mercado * 100, res.p_gana_local * 100
    ok = mk.notna()
    ax.hlines(y[ok], np.minimum(mk, mb)[ok], np.maximum(mk, mb)[ok], color=C_MUTED, lw=2, zorder=1)
    ax.axvline(50, color=INK2, lw=1)
    ax.scatter(mk, y, marker="D", s=55, color=INK2, zorder=3, label="Mercado (cuotas sin comisión)")
    ax.scatter(mb, y, marker="o", s=55, color=C_B, edgecolors=SURF, linewidths=1, zorder=4, label="Modelo B")
    ax.set_yticks(y, _labels(res))
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("← visita   ·   probabilidad de que gane el LOCAL (%)   ·   local →", color=INK2, fontsize=15)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=1, frameon=False, fontsize=15, labelcolor=INK2)
    return _b64(fig)


def fig_ventajas(res, min_edge) -> str:
    n = len(res)
    thr = min_edge * 100
    paneles = [("Spread", "sp"), ("Total (más de / menos de)", "to"), ("Ganador (moneyline)", "ml")]
    fig, axes = plt.subplots(3, 1, figsize=(6.0, 3 * (0.4 * n + 1.3)), sharey=True, facecolor="none")
    y = np.arange(n)
    todo = np.concatenate([(res[f"{k}_edge"] * 100).dropna().values for _, k in paneles])
    lo, hi = min(-8, todo.min() - 1), max(thr + 4, todo.max() + 1)
    for ax, (titulo, k) in zip(axes, paneles):
        _style(ax)
        v = (res[f"{k}_edge"] * 100).fillna(0).values
        col = [C_B if x >= thr else C_MUTED for x in v]
        ax.barh(y, v, color=col, height=0.55)
        ax.axvline(0, color=INK2, lw=1)
        ax.axvline(thr, color=C_A, ls="--", lw=1.5)
        for i, x in enumerate(v):
            if x >= thr:
                ax.text(x + 0.3, i, lt(res[f"{k}_lado"].iloc[i]), va="center", fontsize=15, color=INK)
        ax.set_xlim(lo, hi + 4)
        ax.xaxis.set_major_locator(plt.MultipleLocator(5))
        ax.set_title(titulo, fontsize=17, color=INK, loc="left")
        ax.set_xlabel("ventaja (pts de probabilidad)", color=INK2, fontsize=15)
    axes[0].set_yticks(y, _labels(res))
    axes[0].invert_yaxis()
    axes[2].text(thr, -0.9, " umbral de valor", color=C_A, fontsize=15, va="bottom")
    fig.tight_layout()
    return _b64(fig)


def fig_calibracion(oos, cur) -> str | None:
    s = oos[(oos.season >= 2015) & (oos.season < cur) & oos.y_win.notna() & oos.pwin_B_cal.notna()]
    if len(s) < 200:
        return None
    s = s.assign(bin=pd.cut(s.pwin_B_cal, [0, .2, .35, .5, .65, .8, 1.0], include_lowest=True))
    g = s.groupby("bin", observed=True).agg(n=("y_win", "size"), pred=("pwin_B_cal", "mean"), real=("y_win", "mean"))
    fig, ax = plt.subplots(figsize=(6.0, 6.0), facecolor="none")
    _style(ax, "both")
    ax.plot([0, 100], [0, 100], color=C_MUTED, lw=2, label="Calibración perfecta")
    ax.scatter(g.pred * 100, g.real * 100, s=g.n / 3 + 30, color=C_B, edgecolors=SURF, linewidths=1.5, zorder=3,
               label="Modelo B (tamaño = nº de partidos)")
    ax.set_xlim(0, 100), ax.set_ylim(0, 100)
    ax.set_xlabel("Probabilidad que daba el modelo (%)", color=INK2, fontsize=15)
    ax.set_ylabel("Frecuencia real con que ganó (%)", color=INK2, fontsize=15)
    ax.legend(loc="upper left", frameon=False, fontsize=15, labelcolor=INK2)
    return _b64(fig)


def rmse_tabla(oos, cur):
    m = oos[(oos.season >= 2015) & (oos.season < cur) & oos.result.notna()].dropna(subset=["spread_line", "pred_mA", "pred_mB"])
    if len(m) < 200:
        return None
    r = lambda p: float(np.sqrt(((m.result - p) ** 2).mean()))
    return {"Mercado (línea)": r(m.spread_line), "Modelo A": r(m.pred_mA), "Modelo B": r(m.pred_mB)}, len(m)


def fig_rmse(vals) -> str:
    fig, ax = plt.subplots(figsize=(6.0, 2.8), facecolor="none")
    _style(ax)
    names, v = list(vals), list(vals.values())
    cols = [INK2, C_A, C_B]
    ax.hlines(range(3), min(v) - 0.15, v, color=C_MUTED, lw=2)
    ax.scatter(v, range(3), s=80, color=cols, zorder=3, marker="o")
    for i, x in enumerate(v):
        ax.text(x + 0.04, i, f"{x:.2f}", fontsize=15, color=INK, va="center")
    ax.set_yticks(range(3), names)
    ax.invert_yaxis()
    ax.set_xlim(min(v) - 0.15, max(v) + 0.3)
    ax.set_xlabel("Error típico del margen (puntos; menos = mejor)", color=INK2, fontsize=15)
    return _b64(fig)


# ------------------------------------------------------------------ historial
def _profit(win: bool, lose: bool, odds: float) -> float:
    if win:
        return 100 / abs(odds) if odds < 0 else odds / 100
    return -1.0 if lose else 0.0


def historial(games: pd.DataFrame) -> pd.DataFrame:
    rr = games.set_index("game_id")[["result", "total"]]
    rows = []
    for f in sorted(HIST.glob("prob_*.csv")):
        h = pd.read_csv(f).merge(rr, left_on="game_id", right_index=True, how="left")
        d = h[h.result.notna()]
        if d.empty:
            continue
        nz = d[d.result != 0]
        acc_m = ((nz.p_gana_local >= .5) == (nz.result > 0)).mean() * 100
        mk = nz.dropna(subset=["p_gana_local_mercado"])
        acc_k = ((mk.p_gana_local_mercado >= .5) == (mk.result > 0)).mean() * 100 if len(mk) else np.nan
        bets, units = 0, 0.0
        for _, r in d.iterrows():
            me = r.get("min_edge", 0.02)
            if r.sp_edge >= me:
                home = bool(r.sp_es_a)
                w, l = (r.result > r.spread_line, r.result < r.spread_line) if home else (r.result < r.spread_line, r.result > r.spread_line)
                bets += 1; units += _profit(w, l, r.sp_cuota)
            if r.to_edge >= me:
                over = bool(r.to_es_a)
                w, l = (r.total > r.total_line, r.total < r.total_line) if over else (r.total < r.total_line, r.total > r.total_line)
                bets += 1; units += _profit(w, l, r.to_cuota)
            if r.tiene_ml and r.ml_edge >= me and r.result != 0:
                home = bool(r.ml_es_a)
                w = (r.result > 0) if home else (r.result < 0)
                bets += 1; units += _profit(w, not w, r.ml_cuota)
        rows.append({"Temporada": int(h.season.iloc[0]), "Semana": int(h.week.iloc[0]), "Partidos": len(d),
                     "Acierto ganador modelo %": round(acc_m), "Acierto ganador mercado %": round(acc_k) if acc_k == acc_k else None,
                     "Apuestas con valor": bets, "Resultado (unidades)": round(units, 2)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ HTML
def _signo(x, d=1):
    return f"{x:+.{d}f}"


def _quien(margen: float, home: str, away: str) -> str:
    if abs(margen) < 0.05:
        return "empate técnico"
    return f"{nm(home if margen > 0 else away)} por {abs(margen):.1f}"


def lt(s):
    """Etiqueta visible del lado de un total: la lógica interna sigue usando OVER/UNDER."""
    return str(s).replace("OVER", "Más de").replace("UNDER", "Menos de")


def _badge(edge, lado, min_edge, tiene=True) -> str:
    v = veredicto(edge, lado, min_edge, tiene)
    lado = lt(lado)
    if v.startswith("POSIBLE"):
        return f'<span class="badge yes">✔ Posible valor: {html.escape(lado)} (ventaja {edge * 100:+.1f} pts)</span>'
    if v.startswith("Sin cuota"):
        return '<span class="badge no">Sin cuota publicada todavía</span>'
    if abs(edge) * 100 < 0.05:                      # la diferencia se redondea a 0.0: no es «paga 0.0 pts menos», es que coincide
        return '<span class="badge no">Sin ventaja: el modelo coincide con la línea</span>'
    if edge < 0:
        return (f'<span class="badge no">Sin ventaja · incluso el mejor lado ({html.escape(lado)}) paga '
                f'{abs(edge) * 100:.1f} pts menos de lo que necesita para convenir</span>')
    return (f'<span class="badge no">Sin ventaja clara · {html.escape(lado)} tiene {edge * 100:+.1f} pts a favor, '
            f'pero es menos que el umbral de {min_edge * 100:.0f} pts (diferencia demasiado pequeña para fiarse)</span>')


def _card(r, min_edge, extra: str = "") -> str:
    h, a = r.home_team, r.away_team
    pl = r.p_gana_local * 100
    fav, pf = (h, pl) if pl >= 50 else (a, 100 - pl)
    mk = r.p_gana_local_mercado * 100
    mk_txt = f"el mercado, {(mk if pl >= 50 else 100 - mk):.0f}%" if not np.isnan(mk) else "sin cuota de mercado"
    marca = f'<i class="tick" style="left:{mk:.1f}%"></i>' if not np.isnan(mk) else ""
    disc = abs(r.pred_mA - r.margen_mercado)
    aviso = (f'<p class="warn">⚠ El modelo A discrepa {disc:.1f} puntos del mercado. Casi siempre es porque el mercado sabe algo '
             f'que el modelo no (lesión, mariscal, clima): revisa las noticias antes de fiarte de A.</p>') if disc >= 4 else ""
    cubre_p = r.sp_p * 100
    return f"""
<article class="card">
  <header><h3>{nm(a)} <span>@</span> {nm(h)}</h3><span class="fecha">{fecha(r.gameday)}</span></header>
  <div class="cols">
    <section>
      <h4>¿Quién gana?</h4>
      <p>El modelo da <b>{pf:.0f}%</b> a <b>{nm(fav)}</b> ({mk_txt}).</p>
      <div class="bar" title="Azul = probabilidad del modelo para el local. La marca = mercado."><b style="width:{pl:.1f}%"></b>{marca}</div>
      <div class="barlab"><span>{a}</span><span>{h} (local)</span></div>
      {_badge(r.ml_edge, r.ml_lado, min_edge, r.tiene_ml)}
    </section>
    <section>
      <h4>Spread (con ventaja de puntos)</h4>
      <p>Línea: <b>{h} {r.linea_local:+g}</b>. El mercado espera: {_quien(r.margen_mercado, h, a)}.</p>
      <p class="mini">Modelo A: {_quien(r.pred_mA, h, a)} · Modelo B: {_quien(r.pred_mB, h, a)}</p>
      <p>Mejor lado: <b>{html.escape(r.sp_lado)}</b>, el modelo le da {cubre_p:.0f}% de cubrir; la cuota ({fd(r.sp_cuota)}) exige {r.sp_imp * 100:.0f}%.</p>
      {_badge(r.sp_edge, r.sp_lado, min_edge)}
    </section>
    <section>
      <h4>Total de puntos (más de / menos de)</h4>
      <p>Línea: <b>{r.total_line:g}</b>. El modelo B espera <b>{r.pred_tB:.1f}</b> puntos.</p>
      <p>Mejor lado: <b>{html.escape(lt(r.to_lado))}</b>, el modelo le da {r.to_p * 100:.0f}%; la cuota ({fd(r.to_cuota)}) exige {r.to_imp * 100:.0f}%.</p>
      {_badge(r.to_edge, r.to_lado, min_edge)}
    </section>
  </div>
  {aviso}
  {extra}
</article>"""


from odds_fmt import fd
from ui_css import CSS_TODO as CSS      # un solo sistema de diseno (tokens + componentes); ver ui_css.py y ui/tokens.css

GLOSARIO = """
<dl>
<dt>Línea o spread</dt><dd>Ventaja de puntos que se le da al favorito. «LA -12.5» significa que los Rams deben ganar por más de 12.5 para que la apuesta gane; «ARI +12.5» gana si Arizona pierde por menos de 12.5 o gana.</dd>
<dt>Margen esperado</dt><dd>Por cuántos puntos se espera que gane cada equipo. Positivo = gana el local; negativo = gana la visita. El «margen del mercado» es simplemente la línea con el signo cambiado.</dd>
<dt>Probabilidad de ganar / de cubrir / de «Más de»</dt><dd>Qué tan seguido el modelo cree que ocurrirá cada cosa (100% = seguro). «Cubrir» es superar el spread; «Más de» es que ambos equipos sumen más puntos que la línea del total.</dd>
<dt>Cuota y probabilidad que exige</dt><dd>Una cuota decimal de 1.91 significa que por cada 1 que apuestas recibes 1.91 si ganas (tu ganancia es 0.91). Para no perder dinero a largo plazo hay que acertar 52.4% de las veces: esa es la «probabilidad que exige» la cuota. Incluye la comisión de la casa, por eso en un duelo parejo ninguno de los dos lados llega a 50%.</dd>
<dt>Ventaja (edge)</dt><dd>Probabilidad del modelo menos la probabilidad que exige la cuota, en puntos porcentuales. Si es <b>negativa</b>, la cuota paga menos de lo que vale según el modelo: <b>no conviene</b>. Solo se marca «posible valor» cuando supera el umbral (por defecto +2 pts).</dd>
<dt>«Sin ventaja»</dt><dd>Es el resultado normal en la gran mayoría de los partidos: las casas ya ponen buenos precios y su comisión se come cualquier diferencia pequeña. Que una semana no haya ningún valor no es un error del programa.</dd>
<dt>Moneyline</dt><dd>Apostar solo a quién gana, sin puntos de ventaja.</dd>
</dl>"""

MODELOS = """
<div class="grid2">
<div class="box"><h4>Mercado (referencia)</h4><p>Es la línea y las cuotas de las casas de apuestas. Ya incorporan lesiones, noticias y dinero de profesionales. Es la vara contra la que se mide todo lo demás.</p></div>
<div class="box"><h4>Modelo A · «opinión independiente»</h4><p>Solo mira cómo vienen jugando ambos equipos esta temporada y la anterior (ataque y defensa por pase y por carrera, y puntos), corregido por la dificultad de los rivales. <b>No ve la línea, ni lesiones, ni mariscales.</b> Sirve para detectar partidos donde difiere del mercado, pero en el historial se equivoca más que el mercado.</p></div>
<div class="box"><h4>Modelo B · «el de decisión»</h4><p>Parte de la línea del mercado y la ajusta un poco con los ratings de A y el descanso. Es el que da los porcentajes de este reporte porque en el historial fue el más confiable: sus probabilidades coinciden con la frecuencia real (ver gráfica de calibración).</p></div>
<div class="box"><h4>Umbral de valor</h4><p>Un lado se marca «posible valor» solo si su ventaja es de <b>{umbral:.0f} puntos o más</b>. Con las cuotas con comisión, la mayoría de los partidos queda por debajo.</p></div>
</div>"""


MK_EV = {"sp": "spread", "to": "total", "ml": "ganador"}


def hist_valor(oos, me) -> tuple[dict, dict]:
    """Historial real (fuera de muestra) de las apuestas «posible valor» por mercado: usa evaluacion.evaluar, sin recalcular nada nuevo.
    Devuelve ({sp|to|ml: metricas de «valor»}, evaluacion completa por mercado para las tarjetas KPI de Calidad)."""
    try:
        import marcador as MC
        ref = MC.referencia_backtest(oos, umbral=me)
        ev = ref["eval"]
        return {k: ev[mk]["valor"] for k, mk in MK_EV.items() if mk in ev}, ev
    except Exception as ex:
        print(f"  [aviso] no pude leer el historial de apuestas con valor ({ex})")
        return {}, {}


def veredicto_hist(hv) -> tuple[str, str, str]:
    """(clase, texto del chip, linea de historial). Regla: ambar si el ROI historico es < 0 o su IC 95 % incluye 0; verde solo si el IC queda sobre 0."""
    if not hv or not hv.get("n"):
        return "aviso", "⚠ Ventaja pequeña – sin historial suficiente", ""
    lin = (f"Histórico de este tipo: {hv['acierto'] * 100:.1f} % de acierto ({hv['n']} apuestas) · "
           f"ROI {hv['roi'] * 100:+.1f} % (IC 95 %: {hv['lo'] * 100:+.1f} a {hv['hi'] * 100:+.1f} %)")
    if hv["roi"] < 0:
        return "aviso", "⚠ Ventaja pequeña – históricamente no rentable", lin
    if hv["lo"] <= 0:
        return "aviso", "⚠ Posible valor – histórico no concluyente", lin
    return "valor", "✔ Posible valor – históricamente rentable", lin


def construir(r: dict, ruta: Path | None = None, extras: dict | None = None) -> Path:
    res, oos, cur, wk, me, games = r["res"], r["oos"], r["cur"], r["week"], r["min_edge"], r["games"]
    n = len(res)
    HV, EV_ALL = hist_valor(oos, me)
    flagged = []
    for _, x in res.iterrows():
        for key, tit in (("sp", "Spread"), ("to", "Total"), ("ml", "Moneyline")):
            if key == "ml" and not x.tiene_ml:
                continue
            if x[f"{key}_edge"] >= me:
                flagged.append(f"<li><span class=\"badge {'yes' if veredicto_hist(HV.get(key))[0] == 'valor' else 'warn'}\">{veredicto_hist(HV.get(key))[1]}</span> <b>{html.escape(lt(x[f'{key}_lado']))}</b> ({tit}, {nm(x.away_team)} @ {nm(x.home_team)}): "
                               f"el modelo da {x[f'{key}_p'] * 100:.0f}% y la cuota {fd(x[f'{key}_cuota'])} exige {x[f'{key}_imp'] * 100:.0f}% "
                               f"→ ventaja {x[f'{key}_edge'] * 100:+.1f} pts</li>")
    if flagged:
        _ks = []
        for _, x in res.iterrows():
            for key in ("sp", "to", "ml"):
                if (key != "ml" or x.tiene_ml) and x[f"{key}_edge"] >= me and key not in _ks:
                    _ks.append(key)
        _tit = {"sp": "Spread", "to": "Total", "ml": "Moneyline"}
        _hist = "".join(f"<li><b>{_tit[k]}:</b> {veredicto_hist(HV.get(k))[2] or 'sin historial suficiente'}</li>" for k in _ks)
        resumen = (f'<div class="box big"><h2 style="margin-top:0">Resumen: {len(flagged)} posible(s) valor(es) esta semana (ventaja pequeña)</h2>'
                   f'<ul>{"".join(flagged)}</ul><p class="explain"><b>Veredicto único:</b> son diferencias pequeñas respecto al mercado, no predicciones seguras. '
                   'La etiqueta de cada una sale del historial real de ese tipo de apuesta (pruebas fuera de muestra); ámbar = el resultado histórico es negativo o no concluyente. '
                   f'Revisa lesiones y mariscal titular antes de decidir.</p><ul class="explain">{_hist}</ul></div>')
    else:
        resumen = ('<div class="box big"><h2 style="margin-top:0">Resumen: ningún partido supera el umbral de valor</h2>'
                   '<p>Esta semana el modelo no ve ninguna diferencia lo bastante grande frente a las cuotas. '
                   'Es lo más habitual: el mercado de la NFL es muy eficiente. «Sin ventaja» significa que no conviene apostar según este modelo.</p></div>')

    figs = {"mar": fig_margenes(res), "prob": fig_probabilidad(res), "edge": fig_ventajas(res, me)}
    cal = fig_calibracion(oos, cur)
    rm = rmse_tabla(oos, cur)
    cred = ""
    if cal and rm:
        vals, nrm = rm
        cred = f"""
<h2>¿Qué tanto confiar en estos porcentajes?</h2>
<p class="explain">Probé el modelo B en {nrm} partidos de 2015 a {cur - 1}, prediciendo cada temporada solo con datos de años anteriores (sin trampa).</p>
<div class="grid2">
 <div><h4>Calibración</h4><p class="explain">Si el modelo dice «70%», ¿gana de verdad ~70% de las veces? Cuanto más cerca de la línea gris, más honestos son sus porcentajes.</p><div class="chart"><img alt="Calibración" src="data:image/png;base64,{cal}"></div></div>
 <div><h4>Error al predecir el margen</h4><p class="explain">Error típico en puntos. El mercado ({vals['Mercado (línea)']:.1f}) todavía es mejor que mis ratings solos (A: {vals['Modelo A']:.1f}); B ({vals['Modelo B']:.1f}) queda casi igual que el mercado: <b>no lo supera</b>.</p><div class="chart"><img alt="Error" src="data:image/png;base64,{fig_rmse(vals)}"></div></div>
</div>"""

    hist = historial(games)
    if hist.empty:
        hist_html = '<p class="explain">Todavía no hay semanas anteriores guardadas con partidos jugados. Cada vez que ejecutes el programa se guarda la semana, y la siguiente vez aparecerá aquí cómo le fue.</p>'
    else:
        tot = hist[["Partidos", "Apuestas con valor", "Resultado (unidades)"]].sum()
        hist_html = '<div class="scroll">' + hist.to_html(index=False, border=0, na_rep="n/d") + '</div>' + (
            f'<p class="explain">Total: {int(tot.Partidos)} partidos, {int(tot["Apuestas con valor"])} apuestas marcadas, '
            f'resultado {tot["Resultado (unidades)"]:+.2f} unidades (1 unidad = una apuesta fija). Con tan pocas apuestas esto es ruido, no una tendencia.</p>')

    ex_html, sec_top, sec_cal, nav_extra, sec_td, sec_casas, sec_eq, sec_elo = {}, "", "", "", "", "", "", ""
    ex_parts, excl = {}, None
    sec_pt, nav_pt, pt_data, pt_partes = "", "", None, {}
    sec_qb, nav_qb, qb_an = "", "", {}
    try:                                   # mariscales: quien abre frente al titular habitual (alertas)
        import qb as QB
        qb_an = QB.analizar(r, extras) if extras else {}
        r["qb"] = qb_an
        if qb_an:
            sec_qb = QB.html_qb(qb_an, QB.medir(games), nm)
            nav_qb = '<a href="#qb">Mariscales</a>' if sec_qb else ""
    except Exception as ex:
        print(f"  [aviso] no pude armar los mariscales ({ex})")
    sec_mov, mov_juego = "", {}
    try:                                   # traspasos: quien se movio de equipo (y que el modelo los use con el equipo nuevo)
        import movimientos as MV
        if extras and extras.get("mov_det") is not None:
            sec_mov = MV.html_movimientos(extras["mov_det"], extras.get("mov_of"), nm)
            mov_juego = MV.notas_por_juego(extras["mov_det"], res, wk, nm)
    except Exception as ex:
        print(f"  [aviso] no pude armar la seccion de movimientos ({ex})")
    sec_jug = ""
    try:                                   # explorador de jugadores: Hit Rate semana a semana de cualquier QB/RB/WR/TE (los 32 equipos)
        import jugadores as JG
        if extras and extras.get("pw") is not None:
            sec_jug = JG.html_jugadores(JG.construir(r, extras, nm))
    except Exception as ex:
        print(f"  [aviso] no pude armar el explorador de jugadores ({ex})")
    sec_proy = ""
    try:                                   # PROYECCIONES: proyeccion por volumen (metodo Linemaker), aparte del modelo
        import proyecciones as PY
        if extras and extras.get("pw") is not None:
            sec_proy = PY.html_proyecciones(PY.construir(r, extras, nm))
    except Exception as ex:
        print(f"  [aviso] no pude armar la pestana de proyecciones ({ex})")
    try:                                   # over/under de puntos (total y por equipo) con linea editable
        import puntos as PT
        pt_data = PT.construir(r)
        sec_pt = PT.html_puntos(pt_data, nm)
        pt_partes = PT.html_puntos(pt_data, nm, partes=True)
        nav_pt = '<a href="#puntos">Puntos</a>' if sec_pt else ""
    except Exception as ex:
        print(f"  [aviso] no pude armar el over/under de puntos ({ex})")
    sec_mc, nav_mc = "", ""
    try:                                       # marcador: califica las predicciones guardadas contra lo que paso
        import marcador as MC
        import sqlite3
        _con = sqlite3.connect(Path(__file__).resolve().parent / "data" / "nfl.db")
        try:
            sec_mc = MC.html_marcador(MC.calcular(_con, games=r.get("games"), oos=r.get("oos")), nm)
        finally:
            _con.close()
        nav_mc = '<a href="#marcador">Marcador</a>' if sec_mc else ""
    except Exception as ex:
        print(f"  [aviso] no pude armar el marcador ({ex})")
    if extras:
        import reporte_extra as RE
        import por_equipo as PE
        P, perf, excl = extras["P"], extras["perf"], extras["excl"]
        cres, ecur, tasas = extras.get("cres"), extras.get("cur", cur), extras.get("tasas")
        for _, x in res.iterrows():
            ex_parts[x.game_id] = {
                "matchup": RE.matchup_html(extras["mats"][x.game_id], extras.get("rbs")) if x.game_id in extras["mats"] else "",
                "td": RE.td_html(x.game_id, x.home_team, x.away_team, P, cres, ecur, extras.get("tdauto")),
                "casas": RE.casas_juego_html(x.game_id, extras.get("V")),
                "props": RE.props_html(x.game_id, x.home_team, x.away_team, P, perf, excl, cres, ecur, tasas, extras.get("auto"))}
            p_ = ex_parts[x.game_id]
            ex_html[x.game_id] = p_["matchup"] + p_["td"] + p_["casas"] + p_["props"]
        sec_td = ('<h2 id="td">4. ¿Quién tiene más probabilidad de anotar touchdown esta semana?</h2>'
                  '<p class="explain">Los 20 jugadores con más probabilidad de anotar al menos un TD (por tierra o recepción) en toda la jornada. '
                  'Cada partido tiene abajo su lista completa, de más a menos probable, con el historial de local y visita.</p>'
                  + RE.td_semana_html(P, cres, ecur, 20, extras.get("tdauto")))
        sec_eq = PE.html_equipos(extras.get("equipos"), extras.get("todos") or [], excl=extras.get("excl")) if extras.get("equipos") is not None and len(extras.get("equipos")) else ""
        if extras.get("elo"):
            import elo as EL
            sec_elo = EL.html_elo(extras["elo"], res, nm)
        sec_casas = ('<h2 id="casas">5. Líneas de Kalshi vs modelo (automático)</h2>' + RE.casas_semana_html(extras.get("V"), extras.get("lineas")))
        sec_top = ('<h2 id="props">6. Props destacados de la semana</h2>'
                   '<p class="explain">Aquí van los jugadores donde el <b>contexto del partido</b> (defensa rival, puntos esperados, guion) más mueve la proyección '
                   'frente a la línea «normal» de ese jugador, y solo en los mercados y lados donde el modelo acertó en el historial. '
                   '<b>No son apuestas con ventaja confirmada</b>: no conozco la línea de tu casa de apuestas. Escríbela en la columna «Tu línea» '
                   'y la calculadora te dice la probabilidad y si hay ventaja.</p>' + RE.top_html(extras["top"], extras.get("auto")))
        sec_cal = RE.calidad_html(extras["ev"], extras.get("cov"))
        nav_extra = ('<a href="#porequipo">Por equipo</a>' if sec_eq else '') + ('<a href="#elo">Elo</a>' if sec_elo else '') + '<a href="#td">Touchdowns</a><a href="#casas">Kalshi</a><a href="#props">Props</a>'
    cards = "".join(_card(x, me, (QB.nota_juego(qb_an, x.game_id) if qb_an else "") + ex_html.get(x.game_id, "")) for _, x in res.iterrows())
    usa_web = False
    try:                                   # diseno nuevo: pestanas, resumen por partido, un partido a la vez (ver web.py)
        import os
        if os.environ.get("NFL_DISENO_ANTERIOR"):         # para comparar con el diseno de una sola pagina
            raise RuntimeError("diseno anterior pedido por NFL_DISENO_ANTERIOR")
        import web as WEB
        generado = datetime.now()
        graficas = (f'''<h3>Margen esperado de cada partido</h3>
<p class="explain">Cada fila es un partido. El rombo gris es lo que dice el mercado; el círculo azul (B) casi siempre cae pegado a él; el círculo naranja vacío (A) es la opinión independiente. Si A está lejos del rombo, A y el mercado discrepan.</p>
<div class="chart"><img alt="Márgenes" src="data:image/png;base64,{figs['mar']}"></div>
<h3>¿Quién gana? Modelo vs mercado</h3>
<p class="explain">Probabilidad de que gane el equipo local. Si el punto azul y el rombo están muy juntos, el modelo coincide con el mercado.</p>
<div class="chart"><img alt="Probabilidad de ganar" src="data:image/png;base64,{figs['prob']}"></div>
<h3>¿Hay ventaja en alguna apuesta?</h3>
<p class="explain">Cada barra es el mejor lado de ese partido en cada tipo de apuesta. <b>Hacia la izquierda (negativa) = la cuota paga menos de lo que vale: no conviene.</b> Solo las barras azules, que pasan la línea naranja de umbral, se consideran «posible valor». Si todas son grises, esta semana no hay nada.</p>
<div class="chart"><img alt="Ventajas" src="data:image/png;base64,{figs['edge']}"></div>''')
        cards_ap = {x.game_id: _card(x, me, (QB.nota_juego(qb_an, x.game_id) if qb_an else "") + (f'<div class="qbnota"><b>Movimientos:</b> {html.escape(mov_juego[x.game_id])}</div>' if x.game_id in mov_juego else "")) for _, x in res.iterrows()}
        importante = ('<div class="box"><b>Importante:</b> el modelo A no conoce lesiones ni mariscales; el B parte de la línea del mercado, que sí los conoce '
                      '(los avisos de mariscal, clima y bajas están en cada partido). No es asesoría financiera: apuesta solo lo que puedas perder y donde sea legal.</div>')
        ayuda = MODELOS.format(umbral=me * 100) + f'<details class="box"><summary><b>Qué significa cada número (glosario)</b></summary>{GLOSARIO}</details>'
        body_web = WEB.armar({
            "cur": cur, "wk": wk, "me": me, "nm": nm, "hv": HV, "ev_all": EV_ALL,
            "js_frag": {"jugadores": JG.JS if sec_jug else "", "proyecciones": PY.JS if sec_proy else ""}, "res": res, "games": games, "PT": pt_data, "pt_partes": pt_partes, "qb": qb_an,
            "clima": r.get("clima"), "excl": excl, "sub": f"{n} partidos pendientes con línea publicada · generado el {generado:%d/%m/%Y %H:%M}",
            "generado_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "resumen": resumen, "importante": importante,
            "graficas": graficas, "ayuda": ayuda, "cred": cred, "hist_html": hist_html, "sec_qb": sec_qb, "sec_mov": sec_mov, "sec_jug": sec_jug, "sec_proy": sec_proy, "mov_juego": mov_juego, "sec_mc": sec_mc, "sec_cal": sec_cal,
            "sec_eq": sec_eq, "sec_elo": sec_elo, "sec_td": sec_td, "sec_casas": sec_casas, "sec_top": sec_top,
            "ex_parts": ex_parts, "cards_ap": cards_ap})
        usa_web = True
    except Exception as ex:
        import os
        if not os.environ.get("NFL_DISENO_ANTERIOR"):
            import traceback
            traceback.print_exc()
            print(f"  [aviso] no pude armar el diseño nuevo de la página ({ex}); uso el diseño anterior")
    body = f"""<main>
<nav class="nav"><a href="#resumen">Resumen</a><a href="#equipos">Equipos</a>{nav_pt}{nav_qb}{nav_extra}<a href="#partidos">Partidos</a>{nav_mc}<a href="#historial">Historial</a></nav>
<h1 id="resumen">NFL · Temporada {cur}, semana {wk}</h1>
<p class="sub">{n} partidos pendientes con línea publicada · generado el {datetime.now():%d/%m/%Y %H:%M}</p>
{resumen}
<div class="box"><b>Importante:</b> el modelo A no conoce lesiones ni mariscales; el B parte de la línea del mercado, que sí los conoce (la sección «Mariscales» te avisa de los cambios). No es asesoría financiera: apuesta solo lo que puedas perder y donde sea legal.</div>

<h2>Cómo leer este reporte</h2>
{MODELOS.format(umbral=me * 100)}
<details class="box"><summary><b>Qué significa cada número (glosario)</b></summary>{GLOSARIO}</details>

<h2 id="equipos">1. ¿Qué margen espera cada uno?</h2>
<p class="explain">Cada fila es un partido. El rombo gris es lo que dice el mercado; el círculo azul (B) casi siempre cae pegado a él; el círculo naranja vacío (A) es la opinión independiente. Si A está lejos del rombo, A y el mercado discrepan.</p>
<div class="chart"><img alt="Márgenes" src="data:image/png;base64,{figs['mar']}"></div>

<h2>2. ¿Quién gana? Modelo vs mercado</h2>
<p class="explain">Probabilidad de que gane el equipo local. Si el punto azul y el rombo están muy juntos, el modelo coincide con el mercado.</p>
<div class="chart"><img alt="Probabilidad de ganar" src="data:image/png;base64,{figs['prob']}"></div>

<h2>3. ¿Hay ventaja en alguna apuesta?</h2>
<p class="explain">Cada barra es el mejor lado de ese partido en cada tipo de apuesta. <b>Hacia la izquierda (negativa) = la cuota paga menos de lo que vale: no conviene.</b> Solo las barras azules, que pasan la línea naranja de umbral, se consideran «posible valor». Si todas son grises, esta semana no hay nada.</p>
<div class="chart"><img alt="Ventajas" src="data:image/png;base64,{figs['edge']}"></div>

{sec_eq}
{sec_pt}
{sec_qb}
{sec_mov}
{sec_elo}
{sec_jug}
{sec_proy}
{sec_td}
{sec_casas}
{sec_top}
<h2 id="partidos">7. Detalle partido por partido (con matchups y props)</h2>
{cards}
{cred}
{sec_cal}
{sec_mc}
<h2 id="historial">Cómo le fue en semanas anteriores</h2>
{hist_html}
<p class="foot">Datos: nflverse (play-by-play y líneas). Los porcentajes salen de un modelo estadístico simple y no son garantía de nada.</p>
</main>"""
    if extras:
        import reporte_extra as RE
        import elo as EL
        CSS_X, JS_X = RE.CSS + PE.CSS + EL.CSS, RE.JS + PE.JS
    else:
        CSS_X, JS_X = "", ""
    if sec_pt:
        import por_equipo as PE
        CSS_X += ("" if extras else PE.CSS) + PT.CSS
        JS_X += PT.JS
    if sec_mc:
        CSS_X += MC.CSS
    if sec_qb or qb_an:
        CSS_X += QB.CSS
    if sec_mov:
        CSS_X += MV.CSS
    if sec_jug:                                 # con el diseno nuevo, el JS de jugadores y proyecciones viaja dentro de su fragmento
        CSS_X, JS_X = CSS_X + JG.CSS, JS_X + ("" if usa_web else JG.JS)
    if sec_proy:
        CSS_X, JS_X = CSS_X + PY.CSS, JS_X + ("" if usa_web else PY.JS)
    if usa_web:
        body, CSS_X, JS_X = body_web, CSS_X + WEB.CSS, JS_X + WEB.JS
    doc = f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NFL semana {wk}</title><style>{CSS}{CSS_X}</style></head><body>{body}{JS_X}</body></html>'
    ruta = ruta or REPORTES / f"reporte_{cur}_semana{wk:02d}.html"
    ruta.write_text(doc, encoding="utf-8")
    return ruta
