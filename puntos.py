"""Over / under de PUNTOS: total del partido y puntos de cada equipo, con la linea editable.

Como funciona:
  * El modelo de totales (tB) y el de margen (mB) dan los puntos esperados del partido y la diferencia.
        local = (total + margen) / 2        visita = (total - margen) / 2
    Si el partido aun no tiene linea del mercado se usan los modelos A (sin mercado) y se avisa.
  * La incertidumbre sale de los errores REALES que tuvo el modelo fuera de muestra desde 2008
    (se guardan 400 percentiles por tipo de error). Asi se respeta la forma real de los marcadores
    (no es una campana perfecta) y los puntos se tratan como numeros enteros: con linea entera hay "push".
  * En la pagina escribes cualquier linea y se recalcula en el momento (no hace falta correr nada).

Validado en el backtest 2013-2026 (modelo ajustado solo con temporadas previas): con lineas desplazadas
-14 a +14 puntos respecto al esperado, las probabilidades coinciden con la frecuencia real (error tipico ~1-2 puntos de %).
Contra la linea del mercado el modelo NO tiene ventaja: sus probabilidades ahi quedan cerca de 50 %.
"""
from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd

import clima as _clima

NQ = 400
Q = (np.arange(NQ) + 0.5) / NQ


def _cuantiles(oos: pd.DataFrame) -> dict:
    o = oos[oos.result.notna() & oos.total.notna()].copy()
    o["hp"], o["ap"] = (o.total + o.result) / 2, (o.total - o.result) / 2
    out = {}
    for v in "AB":
        d = o.dropna(subset=[f"pred_t{v}", f"pred_m{v}"])
        t, m = d[f"pred_t{v}"], d[f"pred_m{v}"]
        out[v] = {"t": np.quantile(d.total - t, Q).round(2).tolist(),
                  "h": np.quantile(d.hp - (t + m) / 2, Q).round(2).tolist(),
                  "a": np.quantile(d.ap - (t - m) / 2, Q).round(2).tolist(), "n": int(len(d))}
    return out


def _redondea(x: float) -> float:
    return float(np.round(x * 2) / 2)


def construir(r: dict, semanas: int = 2) -> dict | None:
    """Partidos pendientes de la semana en curso y la siguiente, con puntos esperados y lineas por defecto."""
    df, final, oos, cur = r.get("df"), r.get("final"), r.get("oos"), r.get("cur")
    if df is None or final is None or oos is None:
        return None
    pend = df[df.result.isna() & (df.season == cur)].copy()
    if pend.empty:
        return None
    wk0 = int(pend.week.min())
    pend = pend[pend.week < wk0 + semanas].sort_values(["gameday", "game_id"])
    juegos = []
    for x in pend.itertuples():
        con_linea = pd.notna(x.spread_line) and pd.notna(x.total_line)
        v = "B" if con_linea else "A"
        row = pend.loc[[x.Index]]
        t = float(final[f"t{v}"][0].predict(row[_feats(v, "t")])[0])
        m = float(final[f"m{v}"][0].predict(row[_feats(v, "m")])[0])
        dw = 0.0                                   # cuanto mueve el viento pronosticado al total esperado
        if "wind_eff" in row.columns and float(row.wind_eff.iloc[0]) != 0.0:
            r0 = row.copy()
            r0["wind_eff"] = 0.0
            dw = t - float(final[f"t{v}"][0].predict(r0[_feats(v, "t")])[0])
        mh, ma = (t + m) / 2, (t - m) / 2
        if con_linea:
            lt = float(x.total_line)
            lh, la = _redondea((x.total_line + x.spread_line) / 2), _redondea((x.total_line - x.spread_line) / 2)
        else:
            lt, lh, la = _redondea(t), _redondea(mh), _redondea(ma)
        juegos.append({"id": x.game_id, "sem": int(x.week), "fecha": pd.Timestamp(x.gameday).strftime("%d/%m"), "away": x.away_team,
                       "home": x.home_team, "mod": v, "t": round(t, 1), "h": round(mh, 1), "a": round(ma, 1),
                       "lt": lt, "lh": lh, "la": la, "mercado": bool(con_linea),
                       "clima": (r.get("clima") or {}).get(x.game_id), "dw": round(dw, 1)})
    return {"juegos": juegos, "q": _cuantiles(oos), "cur": cur}


def _feats(v: str, k: str):
    from model import SPECS
    return SPECS[f"{k}{v}"][0]


# ------------------------------------------------------------------------------------------ HTML
def _bloque(clave: str, titulo: str, esperado: float, linea: float, nota: str) -> str:
    return (f'<div class="pbl" data-k="{clave}" data-mu="{esperado}" data-l0="{linea}">'
            f'<div class="pt"><b>{html.escape(titulo)}</b> <span class="pexp">espera <b>{esperado:.1f}</b> pts · rango probable (80 %): <span class="prng"></span></span></div>'
            f'<div class="plin"><label>Línea <input type="number" class="plineain" step="0.5" inputmode="decimal" value="{linea:g}"></label>'
            f'<button type="button" class="pmenos">−1</button><button type="button" class="pmas">+1</button>'
            f'<button type="button" class="preset" title="volver a la línea original">↺</button> <span class="pnota">{html.escape(nota)}</span></div>'
            f'<div class="pres"><div class="pbar"><i></i></div>'
            f'<div class="pnum"><span class="pov"></span><span class="ppu"></span><span class="pun"></span></div>'
            f'<div class="pcj"></div></div><svg class="pdist" viewBox="0 0 300 70" preserveAspectRatio="none"></svg>'
            f'<div class="pax"><span class="pax0"></span><span>puntos</span><span class="pax1"></span></div></div>')


def html_puntos(PT: dict | None, nombre=lambda t: t) -> str:
    if not PT or not PT["juegos"]:
        return ""
    cards = []
    for g in PT["juegos"]:
        if g["mercado"]:
            nota_t, nota_h = "línea del mercado", "implícita: sale del spread y del total"
            aviso = ""
        else:
            nota_t = nota_h = "aún sin línea: punto de partida = lo que espera el modelo"
            aviso = '<p class="pav">Este partido todavía no tiene línea del mercado: usa el modelo A (solo ratings propios, sin mercado), que se equivoca más. Úsalo como referencia.</p>'
        chips, nota_w = _clima.etiquetas(g.get("clima"))
        wx = f'<div class="pwx">{chips}</div>' if chips else ""
        if nota_w:
            wx += f'<p class="pwn">{html.escape(nota_w)}</p>'
        if abs(g.get("dw", 0)) >= 0.3:
            wx += f'<p class="pwn">El modelo ya incluye el viento: mueve el total esperado {g["dw"]:+.1f} pts.</p>'
        cards.append(
            f'<div class="eqcard pjuego" data-k="{g["id"]}"><h3>{html.escape(nombre(g["away"]))} @ {html.escape(nombre(g["home"]))} '
            f'<small>semana {g["sem"]} · {g["fecha"]}</small></h3>{wx}{aviso}'
            + _bloque("t", "Total del partido", g["t"], g["lt"], nota_t)
            + _bloque("h", f"Puntos de {nombre(g['home'])} (local)", g["h"], g["lh"], nota_h)
            + _bloque("a", f"Puntos de {nombre(g['away'])} (visita)", g["a"], g["la"], nota_h) + "</div>")
    q = json.dumps(PT["q"], separators=(",", ":"))
    return f"""<h2 id="puntos">Over / under de puntos (total y por equipo)</h2>
<p class="explain">Para cada partido de esta semana y la siguiente: cuántos puntos espera el modelo y qué tan probable es que se pasen (<b>over</b>) o se queden cortos (<b>under</b>) de una línea.
<b>Escribe cualquier línea</b> (o usa −1 / +1) y las probabilidades se recalculan al instante. El gráfico muestra cómo se reparten los marcadores posibles; la parte coloreada es el over.</p>
<p class="explain"><b>Cómo leerlo:</b> «cuota justa» es la cuota que dejaría el negocio parejo con esa probabilidad; con cuota −110 hace falta acertar 52.4 % para no perder. En el historial (2013-2026) el modelo
<b>no le gana a la línea del mercado</b>: cerca de la línea sus probabilidades rondan 50 %, y eso es lo normal. Donde sí sirve es para lo que el mercado <b>no te muestra</b>: qué tan probable es una línea distinta, o un total por equipo.
Las probabilidades de líneas lejanas (±14 puntos del esperado) coincidieron con la frecuencia real con un error típico de 1-2 puntos porcentuales.</p>
<p class="explain"><b>Clima:</b> debajo del nombre de cada partido está el pronóstico del estadio para la hora del juego (Open-Meteo; se vuelve a bajar en cada corrida, así que es más confiable mientras más cerca esté el partido). El modelo de totales ya usa el viento y el techo. En el historial (2013-2026), con
viento de 15 mph o más el total real quedó en promedio <b>1.5 pts por debajo de la línea</b> (417 partidos, unos 2 errores estándar), pero apostar a eso no dio una ventaja confirmada. Con techo cerrado el clima no afecta.</p>
<div class="eqgrid" id="pgrid">{''.join(cards)}</div>
<script id="pq" type="application/json">{q}</script>"""


JS = """
<script>
(function(){
var QS=null;try{QS=JSON.parse(document.getElementById('pq').textContent);}catch(e){}
if(!QS)return;
function pc(p){var v=Math.round(p*1000)/10;return v<0.1?'<0.1%':(v>99.9?'>99.9%':v.toFixed(1)+'%');}
function cj(p){if(p<0.01||p>0.99)return '—';var o=p>=0.5?Math.round(-100*p/(1-p)):Math.round(100*(1-p)/p);return (o>0?'+':'')+o;}
function pmf(mu,q){var n=q.length,a=new Array(91).fill(0);for(var i=0;i<n;i++){var x=Math.round(mu+q[i]);if(x<0)x=0;if(x>90)x=90;a[x]+=1/n;}return a;}
function calc(b){
 var card=b.closest('.pjuego'),v=card.dataset.mod||'B',k=b.dataset.k,mu=parseFloat(b.dataset.mu),L=parseFloat(b.querySelector('.plineain').value);
 var q=(QS[card.dataset.mod]||QS.B)[k],pm=pmf(mu,q),ov=0,pu=0,un=0,i;
 if(isNaN(L)){b.querySelector('.pnum').innerHTML='<span>escribe una línea</span>';return;}
 for(i=0;i<pm.length;i++){if(i>L+1e-9)ov+=pm[i];else if(Math.abs(i-L)<1e-9)pu+=pm[i];else un+=pm[i];}
 var d=1-pu,po=d>0?ov/d:0.5,pun=d>0?un/d:0.5;
 b.querySelector('.pov').innerHTML='OVER <b>'+pc(ov)+'</b>';b.querySelector('.pun').innerHTML='UNDER <b>'+pc(un)+'</b>';
 b.querySelector('.ppu').innerHTML=pu>0.0005?'push '+pc(pu):'';
 b.querySelector('.pbar i').style.width=(po*100)+'%';
 b.querySelector('.pcj').innerHTML='cuota justa: OVER '+cj(po)+' · UNDER '+cj(pun)+(pu>0.0005?' <small>(sin contar el push)</small>':'')+' · con −110 hace falta 52.4 %';
 var c=0,lo=null,hi=null;for(i=0;i<pm.length;i++){c+=pm[i];if(lo===null&&c>=0.10)lo=i;if(hi===null&&c>=0.90)hi=i;}
 b.querySelector('.prng').textContent=lo+' a '+hi;
 var s=[],mx=Math.max.apply(null,pm),w=300/ (hi-lo+30>40?(hi-lo+30):40);
 var x0=Math.max(0,Math.round(mu)-Math.round(150/w)),n=Math.round(300/w);
 for(i=0;i<n;i++){var x=x0+i,p=(pm[x-1]||0)*.25+(pm[x]||0)*.5+(pm[x+1]||0)*.25,h=mx>0?p/mx*60:0,col=x>L+1e-9?'#d9822b':(Math.abs(x-L)<1e-9?'#999':'#4a7fb5');
  s.push('<rect x="'+(i*w).toFixed(1)+'" y="'+(68-h).toFixed(1)+'" width="'+(w*0.9).toFixed(1)+'" height="'+h.toFixed(1)+'" fill="'+col+'" opacity=".85"/>');}
 var lx=(L-x0+0.5)*w;s.push('<line x1="'+lx.toFixed(1)+'" x2="'+lx.toFixed(1)+'" y1="2" y2="70" stroke="#222" stroke-width="1.5" stroke-dasharray="3 2"/>');
 b.querySelector('.pdist').innerHTML=s.join('');b.querySelector('.pax0').textContent=x0;b.querySelector('.pax1').textContent=x0+n;
}
function todos(){document.querySelectorAll('#pgrid .pbl').forEach(calc);}
document.addEventListener('input',function(e){var t=e.target;if(t.classList&&t.classList.contains('plineain'))calc(t.closest('.pbl'));});
document.addEventListener('click',function(e){var t=e.target,b=t.closest&&t.closest('.pbl');if(!b)return;var inp=b.querySelector('.plineain');
 if(t.classList.contains('pmas')){inp.value=(parseFloat(inp.value||b.dataset.l0)+1);calc(b);}
 else if(t.classList.contains('pmenos')){inp.value=(parseFloat(inp.value||b.dataset.l0)-1);calc(b);}
 else if(t.classList.contains('preset')){inp.value=b.dataset.l0;calc(b);}});
function marca(){document.querySelectorAll('#pgrid .pjuego').forEach(function(c){var m=c.querySelector('.pav');c.dataset.mod=m?'A':'B';});todos();}
marca();
})();
</script>
"""

CSS = """
.pbl{padding:10px 0;border-top:1px solid var(--line)}.pbl:first-of-type{border-top:0}
.pt{font-size:.9rem}.pexp{color:var(--ink2);font-size:.8rem;display:block}
.plin{margin:6px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap}.plin label{font-size:.85rem}
input.plineain{width:80px;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit;text-align:right}
.plin button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:2px 9px;font:inherit;cursor:pointer}
.pnota{font-size:.72rem;color:var(--ink2)}
.pbar{height:9px;border-radius:5px;background:#4a7fb5;overflow:hidden;margin:4px 0}.pbar i{display:block;height:9px;background:#d9822b}
.pnum{display:flex;gap:14px;flex-wrap:wrap;font-size:.95rem}.ppu{color:var(--ink2)}
.pcj{font-size:.78rem;color:var(--ink2);margin-top:2px}
svg.pdist{width:100%;height:64px;margin-top:4px;display:block}
.pax{display:flex;justify-content:space-between;font-size:.7rem;color:var(--ink2)}
.pav{font-size:.8rem;color:var(--ink2);background:rgba(217,130,43,.12);border-radius:8px;padding:6px 8px;margin:4px 0}
"""
CSS = CSS + _clima.CSS
