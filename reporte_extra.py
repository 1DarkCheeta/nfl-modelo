"""Secciones del reporte para jugadores (props) y matchups. Se usan desde reporte.construir()."""
from __future__ import annotations

import html
import io

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reporte import C_A, C_B, C_MUTED, GRID, INK, INK2, SURF, _b64, _style, nm

FUENTE = {"kalshi": "Kalshi", "draftkings": "DraftKings"}
ESTADO = {"Questionable": "Cuestionable", "Doubtful": "Dudoso", "Out": "Fuera"}
OURL = {"Q": "Cuestionable (Ourlads)", "GTD": "Cuestionable (Ourlads)", "P": "Probable (Ourlads)"}
PRACT = {"Did Not Participate In Practice": "No practicó", "Limited Participation in Practice": "Práctica limitada"}
ORDEN_MERCADO = ["pass_yds", "pass_cmp", "pass_td", "pass_int", "rush_yds", "rush_att", "rec_yds", "rec", "tgt"]   # td va en su propia seccion
SENAL_TXT = {"pass_yds": "Yardas por pase", "pass_cmp": "Pases completos", "pass_td": "TD de pase", "pass_int": "Intercepciones",
             "rush_yds": "Yardas por tierra", "rush_att": "Acarreos", "rec_yds": "Yardas de recepción", "rec": "Recepciones",
             "tgt": "Targets"}
CHIP = {"fav": ("fav", "Favorable al ataque"), "dif": ("dif", "Favorable a la defensa"), "neu": ("neu", "Parejo")}

CSS = """
.nav{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:5;display:flex;gap:14px;flex-wrap:wrap;font-size:.9rem}
.nav a{color:var(--blue);text-decoration:none}
details.sub2{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px}details.sub2>summary{cursor:pointer;font-weight:600}
.mcols{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px}@media(max-width:900px){.mcols{grid-template-columns:1fr}}
.mi{border-top:1px solid var(--line);padding:7px 0}.mi:first-of-type{border-top:0}.mt{font-weight:600;font-size:.92rem;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.mn{font-size:.85rem;color:var(--ink2);margin:2px 0}.note{font-size:.85rem;margin-top:2px}
.chip{border-radius:999px;padding:1px 9px;font-size:.75rem;font-weight:600}.chip.fav{background:var(--yes);color:var(--yesink)}.chip.neu{background:var(--no);color:var(--ink2)}
.chip.dif{background:#fde2dc;color:#8a2a14}@media(prefers-color-scheme:dark){.chip.dif{background:#4a2018;color:#ffb4a2}}
.trk{display:inline-block;position:relative;width:96px;height:8px;border-radius:4px;vertical-align:middle;margin:0 6px;background:linear-gradient(90deg,#f1c3b8,#e6e5e1 50%,#bfe0cb)}
.trk i{position:absolute;top:-4px;width:4px;height:16px;border-radius:2px;background:var(--ink)}
.trkrow{font-size:.8rem;color:var(--ink2);white-space:nowrap}.trkrow small{color:var(--ink2)}
table.pt{width:100%;font-size:.84rem;margin:6px 0}table.pt th{font-size:.75rem;color:var(--ink2);text-transform:uppercase;letter-spacing:.03em}
table.pt td{vertical-align:middle}.num{text-align:right;font-variant-numeric:tabular-nums}.pl{font-weight:600}.rol{font-size:.72rem;color:var(--ink2);margin-left:4px}
.est{display:inline-block;border-radius:6px;padding:0 6px;font-size:.72rem;background:#fff3cd;color:#5c4400;margin-left:4px}
@media(prefers-color-scheme:dark){.est{background:#4a3c10;color:#ffe9a8}}
.rng{position:relative;display:inline-block;width:110px;height:8px;background:var(--line);border-radius:4px}.rng b{position:absolute;top:0;height:8px;background:var(--blue);opacity:.55;border-radius:4px}
.rng i{position:absolute;top:-3px;width:3px;height:14px;background:var(--ink);border-radius:2px}
input.lin,input.cuo,input.cuu{width:56px;padding:2px 4px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit}
.res{font-size:.8rem;min-width:170px}.res.yes{color:var(--yesink);font-weight:600}.pos{color:var(--yesink)}.neg{color:#b3361b}
@media(prefers-color-scheme:dark){.neg{color:#ffb4a2}}
.scroll{overflow-x:auto;max-width:100%}
.calc{display:flex;gap:4px;align-items:flex-end}.calc label{display:flex;flex-direction:column;font-size:.64rem;color:var(--ink2)}
table.pt td,table.pt th{padding:4px 6px}.mi,.mn,.note{overflow-wrap:anywhere}.trkrow{white-space:normal}
.mcols>div,.card .cols>section{min-width:0}
.bar{display:inline-block;width:120px;height:10px;border-radius:5px;background:var(--line);vertical-align:middle;margin-right:6px;overflow:hidden}
.bar i{display:block;height:10px;background:var(--blue);border-radius:5px}
.hist{font-size:.78rem;line-height:1.35;min-width:200px}.hist small{color:var(--ink2)}.hist .v{color:var(--ink);font-weight:700}
input.cutd{width:64px;padding:2px 4px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit}
.tdp{font-weight:700;font-variant-numeric:tabular-nums}
.auto{color:var(--blue);font-size:.68rem}
input.leg{margin-right:4px;vertical-align:middle}
#parlay{position:fixed;left:0;right:0;bottom:0;max-height:46vh;overflow:auto;background:var(--card);border-top:2px solid var(--blue);padding:8px 16px;z-index:50;box-shadow:0 -4px 14px rgba(0,0,0,.18);font-size:.85rem}
.mn.rec{color:var(--blue);font-size:.74rem}
#parlay .pl-row{padding:2px 0}.pbtn{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:0 8px;font:inherit;cursor:pointer}.pbtn.x{padding:0 6px}
#parlay .pp{font-weight:700}#parlay .pl-r{margin:6px 0;font-size:.9rem}#parlay .pl-n{font-size:.7rem;color:var(--ink2)}#parlay input{width:90px;padding:2px 4px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit}
body{padding-bottom:0}
"""

JS_TPL = """
<script>
function nbCdf(k,mu,phi){if(k<0)return 0;var n=1/phi,p=n/(n+mu),pmf=Math.exp(n*Math.log(p)),c=pmf;for(var i=0;i<k;i++){pmf=pmf*(i+n)/(i+1)*(1-p);c+=pmf;}return Math.min(c,1);}
function imp(o){return o<0?-o/(-o+100):100/(o+100);}
function calc(tr){var out=tr.querySelector('.res'),L=parseFloat(tr.querySelector('.lin').value);
 if(isNaN(L)){out.textContent='escribe la línea →';out.className='res';return;}
 var mu=+tr.dataset.mu,phi=+tr.dataset.phi,s=+tr.dataset.s,thr=0.02;
 var pu=nbCdf(Math.ceil(L)-1,mu,phi),po=1-nbCdf(Math.floor(L),mu,phi),o=po/(po+pu);o=0.5+s*(o-0.5);var pj=+tr.dataset.pj;if(pj>0&&pj<1)o=o*pj;var u=1-o;tr.dataset.po=o;
 var oo=parseFloat(tr.querySelector('.cuo').value)||-110,ou=parseFloat(tr.querySelector('.cuu').value)||-110;
 var eo=o-imp(oo),eu=u-imp(ou),side=eo>=eu?'OVER':'UNDER',e=Math.max(eo,eu);
 var t='OVER '+Math.round(o*100)+'% · UNDER '+Math.round(u*100)+'% → ';
 if(e>=thr){t+='✔ posible valor: '+side+' ('+(e*100>=0?'+':'')+(e*100).toFixed(1)+' pts)';out.className='res yes';}
 else{t+='sin ventaja (mejor lado '+side+', '+(e*100).toFixed(1)+' pts)';out.className='res';}
 out.textContent=t;btns(out,[['over','copiar OVER'],['under','copiar UNDER']]);}
function calcTd(tr){var out=tr.querySelector('.res'),o=parseFloat(tr.querySelector('.cutd').value);
 if(isNaN(o)||o===0||(o>-100&&o<100)){out.textContent='escribe la cuota (ej. +150) →';out.className='res';return;}
 var p=+tr.dataset.ptd,ip=imp(o),e=p-ip,t='La cuota exige '+Math.round(ip*100)+'% · el modelo da '+Math.round(p*100)+'% → ';
 if(e>=0.03){t+='✔ posible valor (+'+(e*100).toFixed(1)+' pts)';out.className='res yes';}
 else{t+='sin ventaja ('+(e*100>=0?'+':'')+(e*100).toFixed(1)+' pts)';out.className='res';}
 out.textContent=t;btns(out,[['si','copiar Sí']]);}
document.addEventListener('DOMContentLoaded',function(){panelInit();document.querySelectorAll('tr[data-mu]').forEach(function(tr){if(tr.querySelector('.lin').value!=='')calc(tr);});document.querySelectorAll('tr[data-ptd]').forEach(function(tr){if(tr.querySelector('.cutd').value!=='')calcTd(tr);});});
document.addEventListener('input',function(ev){var tr=ev.target.closest('tr[data-mu]');if(tr)calc(tr);var t2=ev.target.closest('tr[data-ptd]');if(t2)calcTd(t2);});

var RHO=__RHO__,LEGS={};
function ninv(p){p=Math.min(Math.max(p,1e-6),1-1e-6);var a=[-39.69683028665376,220.9460984245205,-275.9285104469687,138.357751867269,-30.66479806614716,2.506628277459239],b=[-54.47609879822406,161.5858368580409,-155.6989798598298,66.80131188771908,-13.28068155288572],c=[-0.007784894002430293,-0.3223964580411365,-2.400758277161838,-2.549732539343734,4.374664141464968,2.938163982698783],d=[0.007784695709041462,0.3224671290700398,2.445134137142996,3.754408661907416],q,r;
 if(p<0.02425){q=Math.sqrt(-2*Math.log(p));return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);}
 if(p>1-0.02425){q=Math.sqrt(-2*Math.log(1-p));return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);}
 q=p-0.5;r=q*q;return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);}
function chol(R){var n=R.length,L=[],i,j,k,s;for(i=0;i<n;i++){L.push(new Array(n).fill(0));}
 for(i=0;i<n;i++){for(j=0;j<=i;j++){s=R[i][j];for(k=0;k<j;k++)s-=L[i][k]*L[j][k];if(i==j){if(s<=1e-9)return null;L[i][i]=Math.sqrt(s);}else L[i][j]=s/L[j][j];}}return L;}
function rng32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
function gauss(r){var u=0,v=0;while(u===0)u=r();v=r();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);}
function relKey(a,b){var rel=a.pid===b.pid?'mismo_jugador':(a.team===b.team?'mismo_equipo':'rivales');
 var ka=a.pos+'|'+(a.mkt==='tgt'?'rec':a.mkt),kb=b.pos+'|'+(b.mkt==='tgt'?'rec':b.mkt);if(ka>kb){var t=ka;ka=kb;kb=t;}return rel+'|'+ka+'|'+kb;}
function joint(L){var n=L.length,p=L.map(function(x){return Math.min(Math.max(x.p,1e-4),1-1e-4);}),ind=p.reduce(function(a,b){return a*b;},1);
 if(n<2)return {ind:ind,con:ind};
 var R=[],i,j;for(i=0;i<n;i++){R.push(new Array(n).fill(0));R[i][i]=1;}
 for(i=0;i<n;i++)for(j=i+1;j<n;j++){var a=L[i],b=L[j],r=0;if(a.game===b.game){r=RHO[relKey(a,b)]||0;}
  var sg=(a.lado==='under'?1:-1)*(b.lado==='under'?1:-1);R[i][j]=R[j][i]=r*sg;}
 var C=chol(R),f=1;while(!C&&f>0.05){f*=0.85;for(i=0;i<n;i++)for(j=0;j<n;j++)if(i!==j)R[i][j]*=0.85;C=chol(R);}
 if(!C)return {ind:ind,con:ind};
 var c=p.map(ninv),rnd=rng32(12345),N=60000,hit=0,z=new Array(n),w;
 for(var s=0;s<N;s++){for(i=0;i<n;i++)z[i]=gauss(rnd);var ok=true;
  for(i=0;i<n&&ok;i++){w=0;for(j=0;j<=i;j++)w+=C[i][j]*z[j];if(w>=c[i])ok=false;}if(ok)hit++;}
 return {ind:ind,con:hit/N};}
function cuotaJusta(p){p=Math.min(Math.max(p,0.01),0.99);return p>=0.5?Math.round(-100*p/(1-p)):Math.round(100*(1-p)/p);}
function legData(tr){var d=tr.dataset,td=d.ptd!==undefined,po=td?+d.ptd:(d.po!==undefined?+d.po:NaN),ln=td?'':(tr.querySelector('.lin')?tr.querySelector('.lin').value:'');
 return {pid:d.pid,team:d.team,game:d.game,pos:d.pos,mkt:d.mkt,nm:d.nm,lab:d.lab,po:po,td:td,ln:ln};}
function btns(out,L){L.forEach(function(x){var b=document.createElement('button');b.className='pbtn cb';b.dataset.l=x[0];b.textContent=x[1];b.title='Copia la apuesta para registrarla en «Mis apuestas» (mis_apuestas.py)';out.appendChild(document.createTextNode(' '));out.appendChild(b);});}
function copiar(s,b){function ok(){var t=b.textContent;b.textContent='copiado ✔';setTimeout(function(){b.textContent=t;},1500);}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(ok,function(){fb();});}else fb();
 function fb(){var a=document.createElement('textarea');a.value=s;document.body.appendChild(a);a.select();try{document.execCommand('copy');ok();}catch(e){}document.body.removeChild(a);}}
document.addEventListener('click',function(ev){var b=ev.target.closest('button.cb');if(!b)return;var tr=b.closest('tr'),d=tr.dataset,lado=b.dataset.l,auto=tr.querySelector('.auto'),casa=auto&&/kalshi/i.test(auto.textContent)?'kalshi':'',L,cu,p;
 if(d.ptd!==undefined){L='0.5';cu=tr.querySelector('.cutd').value;p=+d.ptd;}
 else{L=tr.querySelector('.lin').value;var po=+d.po;if(lado==='over'){cu=tr.querySelector('.cuo').value;p=po;}else{cu=tr.querySelector('.cuu').value;p=1-po;}}
 copiar(['NFLBET',d.game,'prop',d.nm,d.pid,d.team,d.mkt,L,lado,cu,p.toFixed(3),casa].join('|'),b);});
function panelInit(){if(document.getElementById('parlay'))return;var d=document.createElement('div');d.id='parlay';d.hidden=true;document.body.appendChild(d);
 d.addEventListener('click',function(ev){var b=ev.target.closest('button[data-k]');if(b){var L=LEGS[b.dataset.k];if(L){L.lado=L.lado==='over'?'under':'over';renderP();}}
  var q=ev.target.closest('button[data-q]');if(q){var K=q.dataset.q;if(LEGS[K]){LEGS[K].tr.querySelector('input.leg').checked=false;delete LEGS[K];renderP();}}
  if(ev.target.id==='parlayClear'){Object.keys(LEGS).forEach(function(k){LEGS[k].tr.querySelector('input.leg').checked=false;});LEGS={};renderP();}});
 d.addEventListener('input',function(ev){if(ev.target.id==='parlayOdds')renderP(true);});}
document.addEventListener('change',function(ev){var c=ev.target;if(c.classList&&c.classList.contains('leg')){var tr=c.closest('tr'),k=tr.dataset.pid+'|'+tr.dataset.mkt;
 if(c.checked)LEGS[k]={tr:tr,lado:'over'};else delete LEGS[k];renderP();}});
function renderP(keep){var d=document.getElementById('parlay'),ks=Object.keys(LEGS);if(!d)return;if(!ks.length){d.hidden=true;document.body.style.paddingBottom='';return;}d.hidden=false;
 var odds=keep&&document.getElementById('parlayOdds')?document.getElementById('parlayOdds').value:(d.dataset.odds||'');d.dataset.odds=odds;
 var rows='',use=[],miss=0;
 ks.forEach(function(k){var x=legData(LEGS[k].tr),lado=LEGS[k].lado,p=isNaN(x.po)?NaN:(lado==='over'?x.po:1-x.po),
  nombre=x.td?(lado==='over'?'Sí anota':'No anota'):(lado==='over'?'OVER':'UNDER')+' '+(x.ln!==''?x.ln:'?');
  if(isNaN(p)){miss++;}else use.push({pid:x.pid,team:x.team,game:x.game,pos:x.pos,mkt:x.mkt,p:p,lado:lado});
  rows+='<div class="pl-row"><b>'+x.nm+'</b> <span class="rol">'+x.lab+'</span> <button data-k="'+k+'" class="pbtn">'+nombre+'</button> <span class="pp">'+(isNaN(p)?'escribe la línea en su fila':Math.round(p*100)+'%')+'</span> <button data-q="'+k+'" class="pbtn x" title="Quitar">×</button></div>';});
 var j=use.length>=1?joint(use):null,txt='';
 if(j&&use.length>=2){var f=j.con/j.ind-1,o=parseFloat(odds),extra='';
  if(!isNaN(o)&&(o<=-100||o>=100)){var ip=o<0?-o/(-o+100):100/(o+100),e=j.con-ip;extra=' · tu cuota exige '+Math.round(ip*100)+'% → '+(e>=0.02?'<b class="pos">posible valor ('+(e*100>=0?'+':'')+(e*100).toFixed(1)+' pts)</b>':'sin ventaja ('+(e*100>=0?'+':'')+(e*100).toFixed(1)+' pts)');}
  txt='Si fueran independientes: <b>'+(j.ind*100).toFixed(1)+'%</b> · Con la correlación medida: <b>'+(j.con*100).toFixed(1)+'%</b> ('+(f>=0?'+':'')+(f*100).toFixed(0)+'% relativo) · cuota justa '+(cuotaJusta(j.con)>0?'+':'')+cuotaJusta(j.con)+extra;}
 else if(use.length===1)txt='Una sola apuesta: '+Math.round(use[0].p*100)+'%. Marca otra casilla para combinarlas.';
 else txt='Escribe la línea de cada jugador seleccionado.';
 d.innerHTML='<div class="pl-h"><b>Combinada ('+ks.length+')</b> <button id="parlayClear" class="pbtn">limpiar</button></div>'+rows+'<div class="pl-r">'+txt+'</div>'+
  '<div class="pl-o">Cuota que te pagan por la combinada (ej. +450): <input id="parlayOdds" type="number" value="'+odds+'"></div>'+
  '<div class="pl-n">La correlación entre jugadores del mismo partido es modesta (QB con sus receptores ≈ +0.15; entre receptores ≈ 0). Apuestas de partidos distintos se tratan como independientes. Muchas casas ya ajustan sus combinadas del mismo partido. No es asesoría financiera.</div>';document.body.style.paddingBottom=d.offsetHeight+'px';}
</script>
"""


def _armar_js() -> str:
    import json
    try:
        import correlaciones
        tabla = correlaciones.cargar()
    except Exception:
        tabla = {}
    return JS_TPL.replace("__RHO__", json.dumps(tabla, separators=(",", ":")))


JS = _armar_js()


def _inputs(line_n, auto=None) -> str:
    """Cuadros de linea y cuotas. Si hay linea automatica (Kalshi / casa), ya vienen llenos."""
    if auto:
        return (f'<div class="calc"><label>línea<input class="lin" type="number" step="0.5" value="{auto["linea"]:g}"></label>'
                f'<label>over<input class="cuo" type="number" value="{auto["over"]}"></label>'
                f'<label>under<input class="cuu" type="number" value="{auto["under"]}"></label></div>'
                f'<small class="auto">{FUENTE.get(auto["fuente"], auto["fuente"])} (automática)</small>')
    return (f'<div class="calc"><label>línea<input class="lin" type="number" step="0.5" placeholder="{line_n:g}"></label>'
            f'<label>over<input class="cuo" type="number" value="-110"></label><label>under<input class="cuu" type="number" value="-110"></label></div>')


def _trk(rank, etiqueta) -> str:
    if rank is None:
        return ""
    pos = (32 - rank) / 31 * 100
    return f'<span class="trkrow">{etiqueta} <span class="trk"><i style="left:calc({pos:.0f}% - 2px)"></i></span><small>#{rank} de 32</small></span>'


def _rbs_html(m: dict, rbs) -> str:
    """Referencia rbsdm: EPA/jugada y tasa de exito de cada equipo (con ranking) para contrastar con el matchup."""
    if rbs is None or len(rbs) == 0 or len(m["lados"]) < 2:
        return ""
    equipos = [m["lados"][0]["ataque"], m["lados"][1]["ataque"]]
    if any(t not in rbs.index for t in equipos):
        return ""
    f = lambda t, c, d=3: f'{rbs.loc[t, c]:+.{d}f} <small>#{rbs.loc[t, "r_" + c]}</small>' if d else ""
    pc = lambda t, c: f'{rbs.loc[t, c] * 100:.0f}% <small>#{rbs.loc[t, "r_" + c]}</small>'
    filas = [("EPA por jugada (ataque)", "off_epa"), ("EPA por jugada (defensa; menor = mejor)", "def_epa"),
             ("EPA por pase (ataque)", "off_pase_epa"), ("EPA por pase (defensa; menor = mejor)", "def_pase_epa")]
    cuerpo = "".join(f'<tr><td>{n}</td><td class="num">{f(equipos[0], c)}</td><td class="num">{f(equipos[1], c)}</td></tr>' for n, c in filas)
    cuerpo += "".join(f'<tr><td>{n}</td><td class="num">{pc(equipos[0], c)}</td><td class="num">{pc(equipos[1], c)}</td></tr>'
                      for n, c in (("Tasa de éxito (ataque)", "off_sr"), ("Tasa de éxito (defensa; menor = mejor)", "def_sr")))
    sem = rbs.semanas.iloc[0]
    return (f'<p class="explain"><b>Referencia rbsdm.com</b> (temporada regular, semanas {sem}; «#» = lugar entre 32 equipos, 1 = mejor). '
            f'Es otra fuente para contrastar el matchup de arriba.</p><div class="scroll"><table class="pt"><tr><th>Métrica</th>'
            f'<th>{nm(equipos[0])}</th><th>{nm(equipos[1])}</th></tr>{cuerpo}</table></div>')


def matchup_html(m: dict, rbs=None) -> str:
    cols = []
    for l in m["lados"]:
        rows = []
        for it in l["items"]:
            cls, txt = CHIP[it["v"]]
            tr = _trk(it["ra"], "Ataque") + " " + _trk(it["rd"], "Defensa")
            rc = it.get("reciente")
            if rc:
                tr += (f'<div class="mn rec" title="Ranking real de EPA por jugada, sin pasar por los ratings del modelo (que tienen memoria larga a propósito)">'
                       f'Ranking real (EPA/jugada) · esta temporada: ataque #{rc["at"]}, defensa #{rc["dt"]} · últimos 4 partidos: ataque #{rc["au"]}, defensa #{rc["du"]}'
                       + (f' · yardas por partido del ataque: #{rc["yt"]} (últimos 4: #{rc["yu"]})' if rc.get("yt") else "") + '</div>')
            rows.append(f'<div class="mi"><div class="mt">{it["tema"]} <span class="chip {cls}">{txt}</span></div>'
                        f'<div class="mn">{html.escape(it["ataque"])}</div><div class="mn">{html.escape(it["defensa"])}</div>'
                        f'<div>{tr}</div><div class="note">{html.escape(it["nota"])}</div></div>')
        cols.append(f'<div><h4>Ataque de {nm(l["ataque"])} vs defensa de {nm(l["defensa"])}</h4>{"".join(rows)}</div>')
    return (f'<details class="sub2"><summary>Matchup: cómo se enfrenta cada ataque a la defensa rival</summary>'
            f'<p class="explain">Cada franja va de «peor» (izquierda) a «mejor» (derecha) entre los 32 equipos. «Favorable al ataque» '
            f'significa que ese ataque debería tenerla más fácil que contra un rival promedio.</p>'
            f'<div class="mcols">{"".join(cols)}</div>{_rbs_html(m, rbs)}</details>')


def _chips(x) -> str:
    out = ""
    e = ESTADO.get(x.estado, "")
    if e:
        out += f'<span class="est">{e}</span>'
    p = PRACT.get(x.practica, "")
    if p:
        out += f'<span class="est">{p}</span>'
    npr = getattr(x, "n_prior", 99)
    if npr is not None and npr < 2:
        out += ('<span class="est" title="Sin historial suficiente: la proyección parte del promedio de su lugar en el depth chart (o, en QB, de su ronda del draft); '
                'es una estimación con más incertidumbre">' + ("sin historial" if npr == 0 else "1 partido previo") + '</span>')
    pj = getattr(x, "p_juega", 1.0)
    if pj is not None and pj < 0.995 and x.estado == "Questionable":
        out += f'<span class="est" title="Probabilidad de jugar según estado y práctica; la proyección es «si juega»">juega ~{pj * 100:.0f}%</span>'
    o = OURL.get(getattr(x, "ourlads", ""), "")
    if o and not e:
        out += f'<span class="est">{o}</span>'
    return out


def _perfil_txt(pos, p) -> str:
    if p is None:
        return "sin partidos esta temporada"
    f = lambda v, d=1: "—" if pd.isna(v) else f"{v:.{d}f}"
    if pos == "QB":
        return (f"{int(p.G)} partidos · {f(p.att_pg, 0)} pases/p · {f(p.cmp_pct, 0)}% completos · <b>{f(p.pass_yds_pg, 0)} yds/p</b> "
                f"(últ. 3: {f(p.u3_pass_yds, 0)}) · {int(p.pass_td)} TD / {int(p.pass_int)} INT")
    if pos == "RB":
        return (f"{int(p.G)} partidos · <b>{f(p.car_pg)} acarreos/p</b> · {f(p.rush_yds_pg, 0)} yds/p ({f(p.ypc)} por acarreo) · "
                f"como receptor: {f(p.tgt_pg)} targets/p, {f(p.rec_pg)} rec/p, {f(p.rec_yds_pg, 0)} yds/p")
    return (f"{int(p.G)} partidos · <b>{f(p.tgt_pg)} targets/p</b> · {f(p.rec_pg)} rec/p ({f(p.catch_pct, 0)}% atrapadas) · "
            f"{f(p.rec_yds_pg, 0)} yds/p ({f(p.ypr)} por recepción, últ. 3: {f(p.u3_rec_yds, 0)}) · target share {f(p.tshare * 100, 0)}%")


def _hist(cres, pid, market, cur, is_home, tasas=None, que="cubrió") -> str:
    """Historial real: en cuantos partidos se cumplio (temporada pasada y actual), en total, de local y de visita.
    Resalta el renglon que corresponde a la localia de ESTE partido."""
    d = (cres or {}).get((pid, market), {})
    lin = []
    for season in (cur - 1, cur):
        h = d.get(season)
        if not h:
            continue
        c, n, cl, nl, cv, nv = h
        pc = lambda a, b: f"{a}/{b}" + (f" ({a / b * 100:.0f}%)" if b else "")
        loc = f"local {pc(cl, nl)}"
        vis = f"visita {pc(cv, nv)}"
        loc, vis = (f'<span class="v">{loc}</span>', vis) if is_home else (loc, f'<span class="v">{vis}</span>')
        lig = ""
        if tasas and (season, market) in tasas and season == cur - 1:
            lig = f' <small>· liga {tasas[(season, market)] * 100:.0f}%</small>'
        lin.append(f"<b>{season}</b>: {pc(c, n)} · {loc} · {vis}{lig}")
    return "<br>".join(lin) if lin else '<small>sin partidos previos</small>'


def _leg(x, mkt=None) -> str:
    """Atributos para la combinada (parlay): identifican al jugador, su equipo, el partido y el mercado."""
    return (f' data-pid="{x.player_id}" data-team="{x.team}" data-game="{x.game_id}" data-pos="{x.position}" '
            f'data-mkt="{mkt or x.market}" data-nm="{html.escape(x.name, quote=True)}" data-lab="{html.escape(str(x.label), quote=True)}"')


_CAJA = '<input type="checkbox" class="leg" title="Añadir a la combinada (abajo verás la probabilidad conjunta)"> '


def _pj(x, auto) -> str:
    """Si la linea viene de Kalshi, el «Si» pierde cuando el jugador no juega: el calculador debe multiplicar por P(juega)."""
    a = (auto or {}).get((x.player_id, x.market))
    pj = getattr(x, "p_juega", 1.0)
    return f' data-pj="{pj:.3f}"' if a and pj is not None and pj < 0.995 else ""


def _fila(x, fmt_n, cres=None, cur=0, tasas=None, auto=None) -> str:
    rng = ""
    scale = max(x.p90 * 1.1, 1)
    rng = (f'<span class="rng"><b style="left:{x.p25 / scale * 100:.0f}%;width:{max((x.p75 - x.p25) / scale * 100, 3):.0f}%"></b>'
           f'<i style="left:calc({x.mu / scale * 100:.0f}% - 1px)"></i></span>')
    aj = x.ajuste * 100
    cls = "pos" if aj > 0 else "neg"
    return (f'<tr data-mu="{x.mu:.4f}" data-phi="{x.phi:.4f}" data-s="{x.s_cal:.3f}"{_pj(x, auto)}{_leg(x)}>'
            f'<td>{_CAJA}<span class="pl">{html.escape(x.name)}</span><span class="rol">{x.rol} {x.position}</span>{_chips(x)}</td>'
            f'<td>{x.label}</td><td class="num">{fmt_n(x.base)}</td><td class="num"><b>{fmt_n(x.mu)}</b></td>'
            f'<td>{rng} <small>{fmt_n(x.p25)}–{fmt_n(x.p75)}</small></td>'
            f'<td class="num">{fmt_n(x.line_n)} <small class="{cls}">({aj:+.0f}%)</small></td>'
            f'<td class="num tdp">{x.p_linea * 100:.0f}%</td>'
            f'<td class="hist">{_hist(cres, x.player_id, x.market, cur, x.is_home == 1, tasas)}</td>'
            f'<td>{_inputs(x.line_n, (auto or {}).get((x.player_id, x.market)))}</td><td class="res">escribe la línea →</td></tr>')


_TH_PROPS = ('<tr><th>Jugador</th><th>Mercado</th><th>Prom. reciente</th><th>Proyección</th><th>Rango típico (25–75%)</th>'
             '<th>Línea «normal» (ajuste)</th><th>% de superarla</th><th>Historial vs esa línea</th>'
             '<th>Tu línea y cuotas</th><th>Resultado</th></tr>')


def props_html(game, home, away, P: pd.DataFrame, perf: pd.DataFrame, excl: pd.DataFrame, cres=None, cur: int = 0, tasas=None, auto=None) -> str:
    g = P[(P.game_id == game) & (P.market != "td")]
    if g.empty:
        return ""
    pf = perf.set_index("player_id")
    blocks = []
    for team in (away, home):
        t = g[g.team == team]
        uniq = t.drop_duplicates("player_id")
        sel = []
        for pos, k in (("QB", 1), ("RB", 2), ("WR", 4), ("TE", 2)):
            u = uniq[uniq.position == pos]
            key = "e_att" if pos == "QB" else "e_car" if pos == "RB" else "e_tgt"
            sel += list(u.sort_values(key, ascending=False).head(k).player_id)
        # el resto de jugadores proyectados (ordenados por posicion y volumen), tambien visibles pero plegados
        resto = []
        for pos in ("QB", "RB", "WR", "TE"):
            u = uniq[(uniq.position == pos) & ~uniq.player_id.isin(sel)]
            key = "e_att" if pos == "QB" else "e_car" if pos == "RB" else "e_tgt"
            resto += list(u.sort_values(key, ascending=False).player_id)
        perf_rows = "".join(
            f'<tr><td><span class="pl">{html.escape(r.name)}</span><span class="rol">{r.rol} {r.position}</span>{_chips(r)}</td>'
            f'<td>{_perfil_txt(r.position, pf.loc[r.player_id] if r.player_id in pf.index else None)}</td></tr>'
            for r in uniq.set_index("player_id").loc[sel].reset_index().itertuples())
        n_dec = lambda v: f"{v:.0f}" if v >= 20 else f"{v:.1f}"

        def tabla(ids):
            pr = t[t.player_id.isin(ids)].copy()
            pr["_o"] = pr.market.map({m: i for i, m in enumerate(ORDEN_MERCADO)})
            pr["_p"] = pr.player_id.map({p: i for i, p in enumerate(ids)})
            pr = pr.sort_values(["_p", "_o"])
            return "".join(_fila(r, n_dec, cres, cur, tasas, auto) for r in pr.itertuples())

        fuera = excl[excl.team == team] if len(excl) else excl
        aviso = ("" if fuera.empty else '<p class="warn">Fuera/dudosos según el reporte oficial, ESPN y Ourlads: ' +
                 ", ".join(f"{html.escape(r.name)} ({r.position}, {ESTADO.get(r.estado, r.estado)})" for r in fuera.itertuples()) +
                 ". No se proyectan.</p>")
        mas = (f'<details class="sub2"><summary>Ver a los demás jugadores de {nm(team)} ({len(resto)})</summary>'
               f'<div class="scroll"><table class="pt">{_TH_PROPS}{tabla(resto)}</table></div></details>') if resto else ""
        blocks.append(f'<h4>{nm(team)}</h4>{aviso}<div class="scroll"><table class="pt"><tr><th>Jugador</th><th>Cómo va la temporada</th></tr>{perf_rows}</table></div>'
                      f'<div class="scroll"><table class="pt">{_TH_PROPS}{tabla(sel)}</table></div>{mas}')
    return ('<details class="sub2"><summary>Props de jugadores: proyección, % de superar la línea e historial</summary>'
            '<p class="explain"><b>Proyección</b> = lo que el modelo espera hoy (incluye rival, guion del partido y clima). '
            '<b>Rango típico</b> = en la mitad de los casos el resultado cae ahí. <b>Línea «normal»</b> = lo que se esperaría del jugador sin '
            'mirar este partido; el % entre paréntesis es cuánto lo mueve el contexto. <b>% de superarla</b> = probabilidad del modelo de que el jugador '
            'pase esa línea hoy. <b>Historial</b> = en cuántos partidos de la temporada pasada y de esta superó esa línea, en total, de local y de visita '
            '(en negritas lo que corresponde a este partido; «liga» = lo que logra el jugador promedio de ese mercado, para comparar). '
            'Ojo: no son las líneas reales de las casas (no hay históricas gratis); son la línea «normal» calculada con información previa a cada partido. '
            'En <b>Tu línea y cuotas</b>, si Kalshi publica ese jugador, ya vienen puestas la línea y las cuotas equivalentes (con comisión); si no, escribe las de tu casa. «p» = por partido.</p>'
            + "".join(blocks) + '</details>')


_TH_TD = ('<tr><th>#</th><th>Jugador</th><th>Probabilidad de anotar</th><th>Cuota justa</th><th>Contexto</th>'
          '<th>Historial: partidos en que anotó</th><th>Tu cuota</th><th>Resultado</th></tr>')


def _input_td(a) -> str:
    if a:
        return f'<input class="cutd" type="number" value="{a["over"]:+d}"><br><small class="auto">{FUENTE.get(a["fuente"], a["fuente"])} (automática)</small>'
    return '<input class="cutd" type="number" placeholder="+150">'


def _fila_td(i, x, cres, cur, mostrar_equipo=False, tdauto=None) -> str:
    p = float(x.p_td)
    from extras import cuota_justa
    cj = cuota_justa(p)
    ctx = f"{x.base:.2f} TD/p reciente · equipo espera {x.implied:.1f} pts"
    eq = f' <span class="rol">{x.team} {"vs" if x.is_home == 1 else "@"} {x.opp}</span>' if mostrar_equipo else ""
    pj = getattr(x, "p_juega", 1.0)
    pa = p * pj if (tdauto and tdauto.get(x.player_id) and pj is not None and pj < 0.995) else p     # Kalshi: el «Si» pierde si no juega
    return (f'<tr data-ptd="{pa:.4f}"{_leg(x, "td")}><td class="num">{i}</td>'
            f'<td>{_CAJA}<span class="pl">{html.escape(x.name)}</span><span class="rol">{x.rol} {x.position}</span>{eq}{_chips(x)}</td>'
            f'<td><span class="bar"><i style="width:{min(p / 0.7, 1) * 100:.0f}%"></i></span><span class="tdp">{p * 100:.0f}%</span></td>'
            f'<td class="num">{cj:+d}</td><td class="mn">{ctx}</td>'
            f'<td class="hist">{_hist(cres, x.player_id, "td", cur, x.is_home == 1)}</td>'
            f'<td>{_input_td(tdauto.get(x.player_id) if tdauto else None)}</td><td class="res">escribe la cuota (ej. +150) →</td></tr>')


def td_html(game, home, away, P: pd.DataFrame, cres=None, cur: int = 0, tdauto=None) -> str:
    """Todos los jugadores del partido ordenados por probabilidad de anotar (al menos 1 TD por tierra o recepcion)."""
    g = P[(P.game_id == game) & (P.market == "td")].sort_values("p_td", ascending=False).reset_index(drop=True)
    if g.empty:
        return ""
    rows = [_fila_td(i + 1, x, cres, cur, True, tdauto) for i, x in enumerate(g.itertuples())]
    vis, resto = rows[:10], rows[10:]
    mas = (f'<details class="sub2"><summary>Ver los demás jugadores ({len(resto)})</summary><div class="scroll"><table class="pt">'
           f'{_TH_TD}{"".join(resto)}</table></div></details>') if resto else ""
    return ('<details class="sub2" open><summary>Touchdowns: ¿quién tiene más probabilidad de anotar en este partido?</summary>'
            '<p class="explain">Probabilidad de que cada jugador anote <b>al menos un touchdown</b> (por tierra o por recepción; el TD de pase del '
            'mariscal no cuenta, como en el mercado «anytime TD»). Ordenado de más a menos probable. <b>Cuota justa</b> = la cuota sin comisión que '
            'corresponde a esa probabilidad: si tu casa paga <i>más</i>, hay valor. Escribe la cuota de tu casa para compararla. '
            'El historial muestra en cuántos partidos anotó el año pasado y este, de local y de visita (en negritas el que toca hoy).</p>'
            f'<div class="scroll"><table class="pt">{_TH_TD}{"".join(vis)}</table></div>{mas}</details>')


def td_semana_html(P: pd.DataFrame, cres=None, cur: int = 0, n: int = 20, tdauto=None) -> str:
    g = P[P.market == "td"].sort_values("p_td", ascending=False).head(n).reset_index(drop=True)
    if g.empty:
        return ""
    rows = "".join(_fila_td(i + 1, x, cres, cur, True, tdauto) for i, x in enumerate(g.itertuples()))
    return (f'<div class="scroll"><table class="pt">{_TH_TD}{rows}</table></div>')


_TH_V = ('<tr><th>Jugador</th><th>Mercado</th><th>Umbral</th><th>Compra «Sí» (ask)</th><th>Compra «No» (1 − bid)</th>'
         '<th>Modelo: prob. de llegar</th><th>Mezcla con Kalshi</th><th>Mejor lado</th><th>Ventaja neta (mezcla)</th></tr>')


def _fila_v(r, n=0) -> str:
    um = f"{r.umbral:g}+" + (" yds" if "yds" in r.mercado else "")
    si = f"{r.ask * 100:.0f}¢" if pd.notna(r.ask) else "—"
    no = f"{(1 - r.bid) * 100:.0f}¢" if pd.notna(r.bid) else "—"
    cls = "pos" if r.edge >= 0.03 else ""
    lado = "Sí (over)" if r.lado.startswith("SI") else "No (under)"
    marca = "✔ " if r.edge >= 0.03 else ""
    return (f'<tr><td><span class="pl">{html.escape(r.jugador)}</span><span class="rol">{r.equipo} vs {r.rival}</span></td><td>{r.label}</td>'
            f'<td class="num">{um}</td><td class="num">{si}</td><td class="num">{no}</td><td class="num">{r.p_modelo * 100:.0f}%</td><td class="num">{r.p_mezcla * 100:.0f}%</td>'
            f'<td>{lado}</td><td class="num {cls}"><b>{marca}{r.edge * 100:+.1f} pts</b></td></tr>')


def casas_juego_html(game, V: pd.DataFrame, n: int = 12) -> str:
    """Donde el modelo difiere de Kalshi (o la casa) en este partido: escalones con mayor ventaja neta."""
    if V is None or V.empty:
        return ""
    g = V[(V.game_id == game) & V.edge.notna() & ~V.discrepa].sort_values("edge", ascending=False)
    if g.empty:
        return ""
    top = g[g.edge >= 0.03].head(n)
    cuerpo = "".join(_fila_v(r) for r in top.itertuples()) if len(top) else \
        '<tr><td colspan="9">Ningún escalón supera 3 puntos de ventaja neta: el modelo y el mercado coinciden en este partido.</td></tr>'
    return (f'<details class="sub2"><summary>Líneas de Kalshi vs modelo ({len(g)} precios útiles, {len(top)} con ventaja ≥ 3 pts)</summary>'
            '<p class="explain">Kalshi publica «escaleras» (p. ej. 40+, 50+, 60+ yardas) con un precio por cada escalón. El precio es una probabilidad: '
            '60¢ = 60 %. <b>Comprar «Sí» cuesta el ask; comprar «No» cuesta 1 − bid.</b> La ventaja neta usa una <b>mezcla</b> (80 % precio de Kalshi + 20 % modelo (10 % en acarreos y yardas por tierra), el peso que mejor funcionó al medirlo contra partidos ya jugados) menos lo que cuesta, '
            'ya descontada la comisión de Kalshi (≈ 7 % × precio × (1 − precio)). Solo se muestran precios con diferencia compra-venta ≤ 10¢. '
            'Los mercados de Kalshi suelen tener poca liquidez: el precio puede no estar disponible en cantidad.</p>'
            f'<div class="scroll"><table class="pt">{_TH_V}{cuerpo}</table></div></details>')


def discrepancias_html(V: pd.DataFrame, n: int = 14) -> str:
    """Jugadores donde Kalshi y el modelo difieren MUCHO en todo el mercado: casi siempre falta informacion en el modelo."""
    if V is None or V.empty or "discrepa" not in V:
        return ""
    d = V[V.discrepa].copy()
    if d.empty:
        return ""
    d["mid"] = d[["bid", "ask"]].mean(axis=1).fillna(d.ask)
    g = d.groupby(["player_id", "mercado"]).agg(jugador=("jugador", "first"), equipo=("equipo", "first"), rival=("rival", "first"), label=("label", "first"),
                                              brecha=("brecha_med", "first"), estado=("estado", "first"), practica=("practica", "first"),
                                              n=("brecha", "size"), p=("p_modelo", "median"), mid=("mid", "median")).reset_index()
    g = g.reindex(g.brecha.abs().sort_values(ascending=False).index).head(n)
    filas = []
    for r in g.itertuples():
        est = ESTADO.get(r.estado, "")
        pr = PRACT.get(r.practica, "")
        motivo = ", ".join(x for x in (est, pr) if x) or "sin reporte de lesión: revisa si es titular / su rol"
        sentido = "el mercado espera MENOS que el modelo" if r.brecha > 0 else "el mercado espera MÁS que el modelo"
        filas.append(f'<tr><td><span class="pl">{html.escape(r.jugador)}</span><span class="rol">{r.equipo} vs {r.rival}</span></td><td>{r.label}</td>'
                     f'<td class="num">{r.p * 100:.0f}%</td><td class="num">{r.mid * 100:.0f}%</td><td>{sentido}</td><td class="mn">{html.escape(motivo)}</td></tr>')
    return ('<h4>Donde el mercado ve algo muy distinto (no se marca como ventaja)</h4>'
            '<p class="explain">Cuando Kalshi y el modelo se separan más de 10 puntos <b>en todo el mercado de un jugador</b>, casi siempre es porque el mercado sabe algo '
            'que el modelo no (si juega, si es titular, su rol nuevo) y no porque esté equivocado. Ojo: en Kalshi estos contratos pierden si el jugador no juega. '
            'Estos casos no se cuentan como ventaja; revísalos como alerta.</p>'
            '<div class="scroll"><table class="pt"><tr><th>Jugador</th><th>Mercado</th><th>Modelo (mediana)</th><th>Kalshi (mediana)</th><th>Diferencia</th><th>Dato disponible</th></tr>'
            + "".join(filas) + '</table></div>')


def casas_semana_html(V: pd.DataFrame, L: pd.DataFrame, n: int = 15) -> str:
    if L is None or L.empty:
        return ('<div class="box"><p>No pude leer líneas de Kalshi en esta ejecución (sin internet o sin mercados abiertos). '
                'El reporte funciona igual: escribe tú la línea en las calculadoras.</p></div>')
    cap = L.groupby("fuente").capturado.max().to_dict()
    nota = " · ".join(f"{FUENTE.get(f, f)}: leído {c} UTC" for f, c in cap.items())
    top = V[V.edge.notna() & ~V.discrepa & (V.edge >= 0.03)].sort_values("edge", ascending=False).head(n) if V is not None and len(V) else pd.DataFrame()
    cuerpo = "".join(_fila_v(r) for r in top.itertuples()) if len(top) else \
        '<tr><td colspan="9">Ningún precio supera 3 puntos de ventaja neta frente al modelo.</td></tr>'
    return (f'<p class="explain">El modelo lee solo los precios de Kalshi ({nota}) y los compara con su probabilidad. '
            'Abajo, los escalones donde la mezcla (80 % Kalshi + 20 % modelo) ve más de 3 puntos de ventaja <b>después de comisión</b>; con este método casi nunca hay alguno, y eso es lo normal. '
            '<b>Ojo:</b> si el modelo y un mercado de apuestas discrepan mucho, lo más probable es que el mercado sepa algo que el modelo no '
            '(lesión de última hora, rol del jugador, clima), no que el mercado esté equivocado. En las pruebas, el modelo mejora poco al promedio simple. '
            '<b>Medido contra el propio Kalshi</b> (partidos de 2025 y 2026, ver <code>evaluar_mercado.py</code>), el precio tuvo menos error que el modelo y mezclarlos mejoró apenas (diferencia dentro del ruido): estas «ventajas» son más probablemente ruido que valor. '
            'Úsalo como una segunda opinión y revisa lesiones antes de decidir. No es asesoría financiera.</p>'
            f'<div class="scroll"><table class="pt">{_TH_V}{cuerpo}</table></div>' + discrepancias_html(V))


def fig_top(top: pd.DataFrame) -> str:
    n = len(top)
    fig, ax = plt.subplots(figsize=(8.6, 0.42 * n + 1.1), facecolor=SURF)
    _style(ax)
    y = np.arange(n)
    v = top.ajuste.values * 100
    ax.barh(y, v, color=[C_B if x > 0 else C_A for x in v], height=0.55)
    ax.axvline(0, color=INK2, lw=1)
    for i, (x, lado) in enumerate(zip(v, top.lado)):
        ax.text(x + (1 if x > 0 else -1), i, lado, va="center", ha="left" if x > 0 else "right", fontsize=8, color=INK)
    ax.set_yticks(y, [f"{a} · {b}" for a, b in zip(top.name, top.label)])
    ax.invert_yaxis()
    lim = max(abs(v).max() + 12, 25)
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("← el contexto BAJA la proyección      cuánto la mueve vs la línea «normal» (%)      la SUBE →", color=INK2, fontsize=9)
    return _b64(fig)


def top_html(top: pd.DataFrame, auto=None) -> str:
    if top.empty:
        return ('<div class="box"><p>Esta semana ningún jugador tiene un ajuste de contexto lo bastante grande (≥ 8%) en los mercados donde el '
                'modelo ha demostrado señal. Las proyecciones de cada partido siguen disponibles abajo.</p></div>')
    rows = []
    for x in top.itertuples():
        d = lambda v: f"{v:.0f}" if v >= 20 else f"{v:.1f}"
        rows.append(f'<tr data-mu="{x.mu:.4f}" data-phi="{x.phi:.4f}" data-s="{x.s_cal:.3f}"{_pj(x, auto)}{_leg(x)}><td>{_CAJA}<span class="pl">{html.escape(x.name)}</span>'
                    f'<span class="rol">{x.team} vs {x.opp}</span>{_chips(x)}</td><td>{x.label}</td>'
                    f'<td class="num">{d(x.line_n)} → <b>{d(x.mu)}</b></td><td><b>{x.lado}</b></td>'
                    f'<td>{x.evid_p * 100:.0f}% <small>(n={x.evid_n}; sin ajuste {x.evid_base * 100:.0f}%)</small></td>'
                    f'<td class="mn">{html.escape(x.razon)}</td>'
                    f'<td>{_inputs(x.line_n, (auto or {}).get((x.player_id, x.market)))}</td><td class="res">escribe la línea →</td></tr>')
    return (f'<div class="chart"><img alt="Props destacados" src="data:image/png;base64,{fig_top(top)}"></div>'
            f'<div class="scroll"><table class="pt"><tr><th>Jugador</th><th>Mercado</th><th>Línea normal → proyección</th><th>Lado</th>'
            f'<th>Respaldo histórico del lado</th><th>Por qué</th><th>Tu línea y cuotas</th><th>Resultado</th></tr>{"".join(rows)}</table></div>')


def calidad_td_html(ev: dict) -> str:
    t = (ev.get("td") or {}).get("td")
    if not t:
        return ""
    c = t["cal"]
    rows = "".join(f"<tr><td>{p * 100:.0f}%</td><td>{r * 100:.0f}%</td><td>{n:,}</td></tr>" for p, r, n in zip(c["pred"], c["real"], c["n"]))
    mej = (1 - t["ll_cal"] / t["ll_base"]) * 100
    return ('<h2 id="fiab-td">¿Qué tan confiables son las probabilidades de touchdown?</h2>'
            f'<p class="explain keep">Probado con {t["n"]:,} jugador-partidos de 2021-2025, cada temporada predicha solo con años anteriores. '
            f'En promedio un jugador elegible anota en {t["tasa"] * 100:.0f}% de sus partidos. Contra el simple promedio reciente de TD, '
            f'el modelo reduce el error de probabilidad (log-loss) {mej:.1f}% ({t["ll_cal"]:.3f} vs {t["ll_base"]:.3f}). '
            f'Entre el 10% de jugadores con mayor probabilidad, el modelo decía {t["top10_pred"] * 100:.0f}% y anotó {t["top10_real"] * 100:.0f}%.</p>'
            '<div class="scroll"><table><tr><th>Cuando el modelo dice…</th><th>…anotó en realidad</th><th>Casos</th></tr>' + rows + '</table></div>'
            '<p class="explain">Lectura: las probabilidades están <b>bien calibradas</b> (lo que dice el modelo coincide con lo que pasó). '
            'Eso no significa ventaja contra la casa: las cuotas de «anytime TD» ya traen una comisión alta (7-10%), así que la calculadora exige '
            'una diferencia de al menos 3 puntos. Los touchdowns tienen mucho azar: incluso un 50% falla la mitad de las veces.</p>')


def local_visita_html(cov) -> str:
    """Tasa de superar la linea «normal» de todos los jugadores, de local vs de visita, por mercado (temporada pasada + actual)."""
    if cov is None or len(cov) == 0:
        return ""
    c = cov[cov.cubrio.notna()]
    if c.empty:
        return ""
    t = c.groupby(["market", "is_home"]).cubrio.agg(["mean", "count"]).unstack()
    rows = []
    for m in ORDEN_MERCADO + ["td"]:
        if m not in t.index:
            continue
        v, l = t.loc[m, ("mean", 0)], t.loc[m, ("mean", 1)]
        nom = "Anotar touchdown" if m == "td" else SENAL_TXT[m]
        rows.append(f"<tr><td>{nom}</td><td>{l * 100:.0f}%</td><td>{v * 100:.0f}%</td><td>{(l - v) * 100:+.1f} pts</td>"
                    f"<td>{int(t.loc[m, ('count', 1)]):,} / {int(t.loc[m, ('count', 0)]):,}</td></tr>")
    ss = sorted(c.season.unique())
    return (f'<h2 id="local-visita">¿Rinden más de local que de visita?</h2>'
            f'<p class="explain">Porcentaje de jugador-partidos (temporadas {" y ".join(str(int(x)) for x in ss)}, incluye playoffs) en que el jugador superó su línea «normal», '
            'según jugara de local o de visita. Los jugadores rinden un poco más de local en pases, yardas y acarreos, pero la diferencia es chica '
            '(el modelo ya la incluye al proyectar). Lo útil es ver cada caso concreto en el historial de cada jugador.</p>'
            '<div class="scroll"><table><tr><th>Mercado</th><th>De local</th><th>De visita</th><th>Diferencia</th><th>Casos (local / visita)</th></tr>'
            + "".join(rows) + '</table></div>')


def _props_vivo() -> str:
    try:
        import props_vivo
        return props_vivo.html_bloque()
    except Exception as e:  # nunca romper el reporte por este bloque
        print(f"  [aviso] calificación en vivo de props no disponible ({e})")
        return ""


def calidad_html(ev: dict, cov=None) -> str:
    rows = []
    for m in ORDEN_MERCADO:
        r = ev.get(m)
        if not r:
            continue
        a = r["adj"]
        mej = (1 - r["mae_modelo"] / r["mae_base"]) * 100
        up = f'{a["p_over_up"] * 100:.0f}% (n={a["n_up"]})' if a["p_over_up"] is not None else "—"
        dn = f'{a["p_over_dn"] * 100:.0f}% (n={a["n_dn"]})' if a["p_over_dn"] is not None else "—"
        rows.append(f"<tr><td>{SENAL_TXT[m]}</td><td>{mej:.1f}%</td><td>{a['p_over_all'] * 100:.0f}%</td><td>{up}</td><td>{dn}</td></tr>")
    return ('<h2 id="fiab-props">¿Qué tanto confiar en las proyecciones de jugadores?</h2>'
            '<p class="explain">Probado con las temporadas 2021-2025 (cada una predicha solo con años anteriores). No hay líneas históricas gratuitas de props, '
            'así que se mide <b>precisión</b>, no ganancias.</p>'
            '<div class="scroll"><table><tr><th>Mercado</th><th>Mejora del error vs promedio reciente</th><th>Veces que superó la línea «normal»</th>'
            '<th>…si el modelo la SUBE ≥ 8%</th><th>…si la BAJA ≥ 8%</th></tr>' + "".join(rows) + '</table></div>'
            '<p class="explain">Lectura: el modelo mejora poco el error frente al simple promedio (1-5%). Lo que sí aporta es el <b>sentido</b> del ajuste: '
            'cuando baja la proyección ≥ 8% por el contexto, el jugador se queda por debajo de su línea normal con mucha más frecuencia que sin ajuste, '
            'sobre todo en yardas por pase, pases completos, acarreos y yardas por tierra. Las casas de apuestas también usan ese contexto, '
            'así que esto <b>no demuestra ventaja contra la línea real</b>: úsalo como segunda opinión y compara con la línea de tu casa en la calculadora.</p>'
            + calidad_td_html(ev) + local_visita_html(cov) + _props_vivo())
