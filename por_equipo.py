"""
Resumen POR EQUIPO (los que juegan esta semana): para cada uno
  - QB: yardas de pase, probabilidad de OVER / UNDER
  - los 3 jugadores con mas probabilidad de anotar touchdown (el primero es el «mas probable»)
  - WR (los 3 con mas targets esperados): yardas de recepcion, OVER / UNDER
  - RB (los 2 con mas acarreos esperados): yardas por tierra, OVER / UNDER

La linea es la de Kalshi cuando hay (el escalon mas cercano al 50 %); si no hay, es la linea «tipica» del jugador
(la mediana de su proyeccion sin el efecto del rival / guion). Si hay precio de Kalshi la probabilidad mostrada es la
MEZCLA (la que mejor calibrada salio en el backtest); si no, es solo el modelo.
Las probabilidades de OVER / UNDER son «si juega»; el chip «juega ~X %» avisa a los dudosos (Questionable).
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd

import lineas_casas as LC

NOMBRES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills", "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
    "DET": "Detroit Lions", "GB": "Green Bay Packers", "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAR": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}
N_WR, N_RB, N_TD = 3, 2, 3


def _fmt(v, m=None) -> str:
    return f"{v:.0f}" if v >= 20 or float(v).is_integer() else f"{v:.1f}"


def _fl(v) -> str:
    """Linea: siempre con su .5 (242.5), para que no parezca un entero."""
    return f"{v:.1f}"


def _linea_y_p(q, V: pd.DataFrame | None, auto: dict) -> dict:
    """Linea, probabilidad de OVER y de donde sale, para una fila de proyeccion `q` (un jugador y un mercado)."""
    a = (auto or {}).get((q.player_id, q.market))
    pj = float(q.p_juega) if pd.notna(getattr(q, "p_juega", np.nan)) else 1.0
    if a is not None and V is not None and len(V):
        v = V[(V.player_id == q.player_id) & (V.mercado == q.market) & (V.linea == a["linea"]) & (V.fuente == a["fuente"])]
        if len(v):
            r = v.iloc[0]
            mid = (r.ask + r.bid) / 2 if not (np.isnan(r.ask) or np.isnan(r.bid)) else np.nan
            lad = V[(V.player_id == q.player_id) & (V.mercado == q.market) & (V.fuente == a["fuente"]) & V.ask.notna() & V.bid.notna()
                    & ((V.ask - V.bid) <= 0.15)].sort_values("linea")
            lad = ",".join(f"{l:g}:{(ak + bd) / 2:.4f}" for l, ak, bd in zip(lad.linea, lad.ask, lad.bid))
            return {"linea": float(a["linea"]), "p_over": float(r.p_mezcla), "p_modelo": float(r.p_modelo), "p_mercado": mid,
                    "fuente": "Kalshi", "pj": pj, "lad": lad}
    # sin precio de Kalshi: «linea tipica» = la que dejaria 50/50 al jugador en un partido normal (mediana de su proyeccion sin
    # el efecto del rival / guion); la probabilidad de OVER dice cuanto mueve el contexto del partido frente a esa linea
    from props import nb_pn
    from scipy.stats import nbinom
    n, pp = nb_pn(max(float(q.mu_n), 1e-3), float(q.phi))
    m = float(nbinom.ppf(0.5, n, pp))
    cand = [m - 0.5, m + 0.5]
    mu_n_eff = max(float(q.mu_n), 1e-3)
    pr = [float(1 - nbinom.cdf(np.floor(c), n, pp)) for c in cand]
    linea = cand[int(np.argmin([abs(x - 0.5) for x in pr]))]
    p = float(LC._p_modelo(LC._con_linea(pd.Series(q._asdict()), linea)))
    return {"linea": float(max(linea, 0.5)), "p_over": p, "p_modelo": p, "p_mercado": np.nan, "fuente": "estimada", "pj": pj, "lad": ""}


def _unicos(P: pd.DataFrame, team: str, market: str, pos: str, key: str, k: int) -> pd.DataFrame:
    d = P[(P.team == team) & (P.market == market) & (P.position == pos)].drop_duplicates("player_id")
    return d.sort_values(key, ascending=False).head(k)


def construir(P: pd.DataFrame, V: pd.DataFrame | None = None, auto: dict | None = None, tdauto: dict | None = None) -> pd.DataFrame:
    """Tabla larga: una fila por equipo / rol / jugador / mercado."""
    filas = []
    teams = sorted(P.team.unique())
    for t in teams:
        opp = P[P.team == t].opp.iloc[0]
        loc = "local" if P[P.team == t].is_home.iloc[0] == 1 else "visita"
        base = {"equipo": t, "rival": opp, "localia": loc}
        # --- QB y yardas de pase
        for rol, d in (("QB", _unicos(P, t, "pass_yds", "QB", "e_att", 1)),
                       ("WR", _unicos(P, t, "rec_yds", "WR", "e_tgt", N_WR)),
                       ("RB", _unicos(P, t, "rush_yds", "RB", "e_car", N_RB))):
            for q in d.itertuples():
                x = _linea_y_p(q, V, auto)
                filas.append({**base, "rol": rol, "jugador": q.name, "player_id": q.player_id, "mercado": q.label, "mkt": q.market,
                              "linea": x["linea"], "fuente_linea": x["fuente"], "proyeccion": q.mu, "promedio_reciente": q.base,
                              "p_over": x["p_over"], "p_under": 1 - x["p_over"], "p_modelo": x["p_modelo"], "p_mercado": x["p_mercado"],
                              "p_juega": x["pj"], "estado": q.estado, "n_prior": q.n_prior, "rol_depth": q.rol,
                              "mu_eff": max(q.base + q.s_cal * (q.mu - q.base), 1e-3), "phi": q.phi, "lad": x["lad"],
                              "w": LC.PESO_MODELO_TIERRA if q.market in ("rush_yds", "rush_att") else LC.PESO_MODELO})
        # --- touchdowns
        td = P[(P.team == t) & (P.market == "td")].drop_duplicates("player_id").copy()
        pm = {}
        if V is not None and len(V):
            vv = V[(V.mercado == "td") & (V.linea == 0.5)].dropna(subset=["p_mezcla"])
            pm = vv.groupby("player_id").agg(p_mezcla=("p_mezcla", "first"), ask=("ask", "first"), bid=("bid", "first")).to_dict("index")
        td["p_final"] = [pm[i]["p_mezcla"] if i in pm else (p * (pj if pd.notna(pj) else 1.0)) for i, p, pj in zip(td.player_id, td.p_td, td.p_juega)]
        for n, q in enumerate(td.sort_values("p_final", ascending=False).head(N_TD).itertuples(), 1):
            mk = pm.get(q.player_id, {})
            mid = (mk["ask"] + mk["bid"]) / 2 if mk and not (np.isnan(mk["ask"]) or np.isnan(mk["bid"])) else np.nan
            filas.append({**base, "rol": f"TD{n}", "jugador": q.name, "player_id": q.player_id, "mercado": "Anotar touchdown", "mkt": "td",
                          "linea": 0.5, "fuente_linea": "Kalshi" if mk else "estimada", "proyeccion": q.mu, "promedio_reciente": q.base,
                          "p_over": q.p_final, "p_under": 1 - q.p_final, "p_modelo": q.p_td * (q.p_juega if pd.notna(q.p_juega) else 1.0),
                          "p_mercado": mid, "p_juega": q.p_juega, "estado": q.estado, "n_prior": q.n_prior, "rol_depth": q.rol,
                          "pos": q.position})
    return pd.DataFrame(filas)


def csv_equipos(T: pd.DataFrame) -> pd.DataFrame:
    if T.empty:
        return T
    return pd.DataFrame({
        "equipo": T.equipo, "rival": T.rival, "localia": T.localia, "rol": T.rol, "jugador": T.jugador, "mercado": T.mercado,
        "linea": T.linea, "fuente_de_la_linea": T.fuente_linea, "proyeccion": T.proyeccion.round(1),
        "prob_over_%": (T.p_over * 100).round(0), "prob_under_%": (T.p_under * 100).round(0),
        "solo_modelo_over_%": (T.p_modelo * 100).round(0), "kalshi_over_%": (T.p_mercado * 100).round(0),
        "prob_de_jugar_%": (T.p_juega * 100).round(0), "estado_lesion": T.estado.replace("", "sin reporte"),
        "partidos_previos": T.n_prior.astype(int)})


# ------------------------------------------------------------------ HTML
def _chips(r) -> str:
    out = ""
    if r.estado == "Questionable" and r.p_juega < 0.995:
        out += f'<span class="est" title="Probabilidad de jugar; OVER/UNDER son «si juega»">juega ~{r.p_juega * 100:.0f}%</span>'
    elif r.estado:
        out += f'<span class="est">{html.escape({"Out": "Baja", "Doubtful": "Dudoso", "Questionable": "Dudoso"}.get(r.estado, r.estado))}</span>'
    if r.n_prior < 2:
        out += '<span class="est" title="Poco o nada de historial: estimación con más incertidumbre">sin historial</span>'
    return out


def _barra(p: float) -> str:
    """Barra de dos colores: la parte llena es OVER (o «anota»); el resto, UNDER."""
    return f'<span class="bar2" title="OVER {p * 100:.0f}% · UNDER {(1 - p) * 100:.0f}%"><i style="width:{p * 100:.0f}%"></i></span>'


def _fila_yds(r) -> str:
    over, lado = r.p_over, "OVER" if r.p_over >= 0.5 else "UNDER"
    pl = max(over, 1 - over)
    fuerte = " fuerte" if pl >= 0.60 else ""
    if r.fuente_linea == "Kalshi":
        fu = (f'<small class="auto">Kalshi</small>' + (f' <small>(mercado {r.p_mercado * 100:.0f}% over · modelo {r.p_modelo * 100:.0f}%)</small>' if pd.notna(r.p_mercado) else ""))
    else:
        fu = '<small title="No hay precio de Kalshi: uso su línea típica (la que lo dejaría 50/50 en un partido normal)">línea típica</small>'
    pj = r.p_juega if (r.p_juega is not None and pd.notna(r.p_juega)) else 1.0
    attrs = (f' data-emu="{r.mu_eff:.4f}" data-ephi="{r.phi:.4f}" data-epj="{pj:.3f}" data-ew="{r.w:g}" data-elad="{r.lad}" '
             f'data-l0="{r.linea:g}" data-src0="{html.escape(fu, quote=True)}"')
    return (f'<tr{attrs}><td><span class="pl">{html.escape(r.jugador)}</span><span class="rol">{r.rol_depth or r.rol}</span>{_chips(r)}</td>'
            f'<td class="num"><input class="elin" type="number" step="0.5" value="{r.linea:g}" title="Cambia la línea para recalcular"> '
            f'<button class="pbtn" data-reset="1" title="Volver a la línea original">↺</button><br><span class="esrc">{fu}</span></td>'
            f'<td class="num"><b>{_fmt(r.proyeccion)}</b></td>'
            f'<td class="num eqo">{over * 100:.0f}%</td><td class="num equ">{(1 - over) * 100:.0f}%</td>'
            f'<td><span class="eqbar">{_barra(over)}</span><span class="lado{fuerte}">{lado} {pl * 100:.0f}%</span><br>'
            f'<small class="ecj">cuota justa: OVER {_cj(over):+d} · UNDER {_cj(1 - over):+d}</small></td></tr>')


def _cj(p: float) -> int:
    p = min(max(p, 0.01), 0.99)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


_TH = ('<tr><th>Jugador</th><th>Línea</th><th>Proyección</th><th>OVER</th><th>UNDER</th><th>Lado más probable</th></tr>')


def _bloque(titulo: str, ayuda: str, filas: list[str]) -> str:
    if not filas:
        return ""
    return (f'<h4>{titulo} <small>{ayuda}</small></h4><div class="scroll"><table class="pt">{_TH}{"".join(filas)}</table></div>')


def _tds(d: pd.DataFrame) -> str:
    if d.empty:
        return ""
    li = []
    for r in d.itertuples():
        k = f' <small class="auto">Kalshi {r.p_mercado * 100:.0f}%</small>' if pd.notna(r.p_mercado) else ""
        li.append(f'<li><span class="pl">{html.escape(r.jugador)}</span><span class="rol">{r.rol_depth or ""}</span>{_chips(r)} '
                  f'<b class="tdp">{r.p_over * 100:.0f}%</b> {_barra(r.p_over)}{k}</li>')
    return ('<h4>Más probable a anotar <small>(1+ TD por tierra o recepción; con Kalshi, mezcla)</small></h4>'
            f'<ol class="tdlist">{"".join(li)}</ol>')


def html_equipos(T: pd.DataFrame, todos: list[str], games_semana: pd.DataFrame | None = None, excl: pd.DataFrame | None = None) -> str:
    """`todos` = los 32 equipos; los que no estan en T descansan (bye)."""
    if T.empty:
        return ""
    juegan = sorted(T.equipo.unique(), key=lambda t: NOMBRES.get(t, t))
    descansan = [t for t in todos if t not in set(T.equipo)]
    idx = " · ".join(f'<a href="#eq-{t}">{t}</a>' for t in juegan)
    cards = []
    for t in juegan:
        d = T[T.equipo == t]
        r0 = d.iloc[0]
        qb = [_fila_yds(r) for r in d[d.rol == "QB"].itertuples()]
        wr = [_fila_yds(r) for r in d[d.rol == "WR"].itertuples()]
        rb = [_fila_yds(r) for r in d[d.rol == "RB"].itertuples()]
        td = _tds(d[d.rol.str.startswith("TD")])
        if not qb:                      # sin QB proyectado (titular baja y el suplente sin pases recientes): avisarlo, no dejarlo en silencio
            baja = []
            if excl is not None and len(excl):
                baja = [f"{r.name} ({ {'Out': 'Out', 'Doubtful': 'Dudoso'}.get(r.estado, r.estado)})" for r in excl[(excl.team == t) & (excl.position == "QB")].itertuples()]
            motivo = (f"el QB titular {', '.join(baja)} no juega y " if baja else "")
            qb = [f'<tr><td colspan="6"><span class="est">sin proyección</span> {html.escape(motivo)}el modelo no tiene datos recientes para proyectar a su suplente '
                  f'(pide un promedio de 15+ pases y haber jugado en los últimos partidos). Revisa quién abre de QB antes de usar a sus receptores.</td></tr>']
        cards.append(
            f'<section class="eqcard" id="eq-{t}"><h3>{html.escape(NOMBRES.get(t, t))} <small>{"vs" if r0.localia == "local" else "@"} {html.escape(r0.rival)} · {r0.localia}</small></h3>'
            + _bloque("Mariscal (QB): yardas de pase", "", qb) + td
            + _bloque("Receptores (WR): yardas de recepción", "los 3 con más targets esperados", wr)
            + _bloque("Corredores (RB): yardas por tierra", "los 2 con más acarreos esperados", rb) + "</section>")
    nombres = ", ".join(html.escape(NOMBRES.get(t, t)) for t in descansan)
    if not descansan:
        bye = ""
    elif len(descansan) <= 4:
        bye = f'<p class="explain"><b>Descansan esta semana</b> (no hay partido, así que no hay proyección): {nombres}.</p>'
    else:
        bye = (f'<p class="explain"><b>Sin partido pendiente</b> ({len(descansan)} equipos: ya jugaron esta jornada o descansan, así que no tienen proyección): '
               f'{nombres}.</p>')
    return (
        '<h2 id="porequipo">Equipo por equipo: QB, anotadores, WR y RB</h2>'
        '<p class="explain">Para cada equipo que juega esta semana: las yardas de pase de su QB, quién tiene más probabilidad de anotar y las yardas de sus receptores y corredores, '
        'con la probabilidad de <b>OVER</b> (pasar la línea) y de <b>UNDER</b> (quedarse debajo). '
        'Cuando hay precio de Kalshi la línea es la de Kalshi y la probabilidad es la <b>mezcla</b> modelo + mercado (la que mejor calibrada salió al probarla con partidos pasados). '
        'Si no hay precio, uso su <b>línea típica</b> (la que lo dejaría 50/50 en un partido normal) y solo el modelo: en ese caso un OVER por encima de 50% significa que el rival y el guion del partido lo favorecen, '
        'no que haya ventaja contra tu casa. <b>Si tu casa tiene otra línea, escríbela en la casilla «Línea» de cualquier jugador y las probabilidades se recalculan al instante</b> (con la mezcla de Kalshi si esa línea cae dentro de sus precios; si no, solo con el modelo). El botón ↺ regresa a la línea original.</p>'
        '<div class="box"><b>Cómo leerlo:</b> un 60% de OVER significa que, en estos números, de cada 10 veces que se repitiera el partido el jugador pasa la línea unas 6. '
        'Las probabilidades de jugadores sin mucho historial o dudosos tienen más incertidumbre. No es asesoría financiera.</div>'
        + bye + f'<p class="eqidx">{idx}</p><div class="eqgrid">{"".join(cards)}</div>')


JS = """
<script>
(function(){
function cdf(k,mu,phi){if(k<0)return 0;var n=1/phi,p=n/(n+mu),pmf=Math.exp(n*Math.log(p)),c=pmf;for(var i=0;i<k;i++){pmf=pmf*(i+n)/(i+1)*(1-p);c+=pmf;}return Math.min(c,1);}
function pc(p){var v=Math.round(p*100);return v<1?'<1%':(v>99?'>99%':v+'%');}
function cj(p){if(p<0.02||p>0.98)return '—';var o=p>=0.5?Math.round(-100*p/(1-p)):Math.round(100*(1-p)/p);return (o>0?'+':'')+o;}
function lad(tr){var t=tr.dataset.elad;if(!t)return [];return t.split(',').map(function(x){var a=x.split(':');return [parseFloat(a[0]),parseFloat(a[1])];}).sort(function(a,b){return a[0]-b[0];});}
function mid(l,L){for(var i=0;i<l.length;i++){if(Math.abs(l[i][0]-L)<1e-9)return l[i][1];}
 for(i=0;i+1<l.length;i++){if(L>l[i][0]&&L<l[i+1][0]){var f=(L-l[i][0])/(l[i+1][0]-l[i][0]);return l[i][1]+f*(l[i+1][1]-l[i][1]);}}return NaN;}
function eq(tr){var L=parseFloat(tr.querySelector('input.elin').value),d=tr.dataset,o=tr.querySelector('.eqo'),u=tr.querySelector('.equ'),
 bar=tr.querySelector('.eqbar i'),lado=tr.querySelector('.lado'),src=tr.querySelector('.esrc'),cjq=tr.querySelector('.ecj');
 if(isNaN(L)){src.textContent='escribe la línea';return;}
 var mu=+d.emu,phi=+d.ephi,pj=+d.epj,w=+d.ew,pm=1-cdf(Math.floor(L),mu,phi),L0=parseFloat(d.l0),m=mid(lad(tr),L),p,txt;
 if(Math.abs(L-L0)<1e-9){src.innerHTML=d.src0;}
 if(!isNaN(m)){p=w*pm*pj+(1-w)*m;if(Math.abs(L-L0)>1e-9)txt='<small class="auto">mezcla con Kalshi</small> <small>(mercado '+Math.round(m*100)+'% over · modelo '+Math.round(pm*pj*100)+'%)</small>';}
 else{p=pm;if(Math.abs(L-L0)>1e-9)txt='<small>solo modelo (si juega)'+(lad(tr).length?'; esa línea queda fuera de los precios de Kalshi':'')+'</small>';}
 if(Math.abs(L-L0)>1e-9)src.innerHTML=txt;
 o.textContent=pc(p);u.textContent=pc(1-p);bar.style.width=(p*100)+'%';
 var pl=Math.max(p,1-p);lado.textContent=(p>=0.5?'OVER ':'UNDER ')+pc(pl);lado.className='lado'+(pl>=0.6?' fuerte':'');
 cjq.textContent='cuota justa: OVER '+cj(p)+' · UNDER '+cj(1-p);}
document.addEventListener('input',function(ev){var t=ev.target;if(t.classList&&t.classList.contains('elin')){eq(t.closest('tr'));}});
document.addEventListener('click',function(ev){var b=ev.target.closest('button[data-reset]');if(!b)return;var tr=b.closest('tr');tr.querySelector('input.elin').value=tr.dataset.l0;eq(tr);});
})();
</script>
"""

CSS = """
input.elin{width:70px;padding:2px 4px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit;text-align:right}
.esrc{font-size:.72rem;color:var(--ink2)}.ecj{color:var(--ink2)}
.eqidx{font-size:.85rem;line-height:1.9}.eqidx a{color:var(--blue);text-decoration:none;margin-right:2px}
.eqgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:14px}@media(max-width:600px){.eqgrid{grid-template-columns:1fr}}
.eqcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;min-width:0}
.eqcard h3{margin:0 0 4px;font-size:1.05rem}.eqcard h3 small{color:var(--ink2);font-weight:400;font-size:.8rem}
.eqcard h4{margin:12px 0 2px;font-size:.88rem}.eqcard h4 small{color:var(--ink2);font-weight:400}
.bar2{display:inline-block;width:70px;height:8px;border-radius:4px;background:#f1c3b8;vertical-align:middle;margin:0 6px;overflow:hidden}
.bar2 i{display:block;height:8px;background:#6fb78a}
.lado{font-size:.8rem;font-weight:600;color:var(--ink2)}.lado.fuerte{color:var(--yesink)}
ol.tdlist{margin:2px 0 0;padding-left:1.3em;font-size:.88rem}ol.tdlist li{padding:2px 0}
"""
