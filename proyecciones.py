"""PROYECCIONES: cuanto PRODUCE cada ofensiva y cuanto PERMITE cada defensa (metodo del pizarron de @linemakersports).

Pestana de la pagina, sin lineas ni momios. Solo LEE datos (player_weeks, juegos, snaps): no escribe en la base ni
cambia ningun calculo del modelo. Todo lo que dibuja lleva el prefijo `py-` / `#py`.

Que muestra (promedios por partido de la temporada en curso, solo temporada regular):
  - Ofensivas: puntos, jugadas, puntos por jugada, yardas de pase / completos / intentos / yardas por completo,
    yardas por tierra / acarreos / yardas por acarreo, TD de pase y por tierra, yardas totales.
  - Defensas: lo mismo, pero lo que PERMITEN (lo que produjeron sus rivales).
  - Cruce: ofensiva de un equipo contra la defensa del rival, con las formulas del pizarron:
      pase   = completos por partido x yardas por completo que permite la defensa
      tierra = acarreos por partido x yardas por acarreo que permite la defensa
      puntos = (jugadas x pts por jugada propios + jugadas x pts por jugada que permite el rival) / 2
      WR/TE  = completos del equipo x yardas por completo permitidas x target share
"""
from __future__ import annotations

import json

import pandas as pd

# (clave, etiqueta, decimales). Orden fijo: es el orden de las columnas en los datos embebidos.
COLS = [("pts", "Puntos", 1), ("jug", "Jugadas", 1), ("ppj", "Pts por jugada", 3), ("tyd", "Yardas totales", 1),
        ("pyd", "Yardas de pase", 1), ("cmp", "Completos", 1), ("att", "Intentos", 1), ("ypc", "Yds por completo", 2),
        ("ryd", "Yardas por tierra", 1), ("car", "Acarreos", 1), ("ypa", "Yds por acarreo", 2),
        ("ptd", "TD de pase", 2), ("rtd", "TD por tierra", 2)]
POSS = ("QB", "RB", "WR", "TE")
MIN = {"QB": ("att", 20), "RB": ("car", 10), "WR": ("tgt", 8), "TE": ("tgt", 8)}   # para no listar a quien casi no juega


def _r(x, n=3):
    return None if x is None or pd.isna(x) else round(float(x), n)


def _vec(n, pts, plays, ppj, d):
    """Lista de valores en el orden de COLS. d: sumas por partido (cmp, att, pass_yds, pass_td, car, rush_yds, rush_td) ya promediadas."""
    ypc = d["pass_yds"] / d["cmp"] if d["cmp"] > 0 else None
    ypa = d["rush_yds"] / d["car"] if d["car"] > 0 else None
    return [_r(pts, 2), _r(plays, 1), _r(ppj, 4), _r(d["pass_yds"] + d["rush_yds"], 1), _r(d["pass_yds"], 1), _r(d["cmp"], 2), _r(d["att"], 2),
            _r(ypc, 3), _r(d["rush_yds"], 1), _r(d["car"], 2), _r(ypa, 3), _r(d["pass_td"], 2), _r(d["rush_td"], 2)]


def construir(r: dict, extras: dict, nm=lambda t: t) -> dict | None:
    pw, games = extras.get("pw"), r.get("games")
    if pw is None or len(pw) == 0 or games is None or len(games) == 0:
        return None
    cur = int(extras.get("cur") or r["cur"])
    g = games[games.get("game_type", "REG") == "REG"] if "game_type" in games else games
    g = g[g.season == cur]
    p = pw[(pw.season == cur) & pw.position.isin(POSS)]
    if "season_type" in p:
        p = p[p.season_type.fillna("REG") == "REG"]
    if len(p) == 0 or len(g) == 0:
        return None
    fin = g.dropna(subset=["home_score", "away_score"])
    if len(fin) == 0:
        return None
    vig = extras.get("vigente") or {}

    opp = {}
    for x in fin.itertuples():
        opp[(int(x.week), x.home_team)] = x.away_team
        opp[(int(x.week), x.away_team)] = x.home_team
    p = p.assign(opp=[opp.get((int(w), t)) for w, t in zip(p.week, p.team)]).dropna(subset=["opp"])
    num = ["cmp", "att", "pass_yds", "pass_td", "car", "rush_yds", "rush_td"]
    of_w = p.groupby(["team", "week"])[num].sum().groupby("team").mean()      # lo que produce cada ofensiva por partido
    de_w = p.groupby(["opp", "week"])[num].sum().groupby("opp").mean()        # lo que permite cada defensa por partido

    # jugadas = snaps ofensivos del equipo en el partido (sin quitar la "basura"); puntos propios y permitidos
    pts = {}
    for x in fin.itertuples():
        pts.setdefault(x.home_team, []).append((x.game_id, x.away_team, x.home_score, x.away_score))
        pts.setdefault(x.away_team, []).append((x.game_id, x.home_team, x.away_score, x.home_score))
    tp = None
    try:
        import db
        sn = db.leer("snaps", [cur])
        gw = fin[["game_id", "week"]].drop_duplicates()
        pt = p[["player_id", "week", "team"]].drop_duplicates()
        tp = sn.merge(gw, on="game_id").merge(pt, on=["player_id", "week"]).groupby(["game_id", "team"]).offense_snaps.max().to_dict()
    except Exception:
        tp = None

    equipos = sorted(pts)
    OFF, DEF, ngames = {}, {}, {}
    for t in equipos:
        lst = pts[t]
        ngames[t] = len(lst)
        pf, pa = sum(a[2] for a in lst) / len(lst), sum(a[3] for a in lst) / len(lst)
        jo = jd = ppo = ppd = None
        if tp:
            rows = [(tp.get((a[0], t)), tp.get((a[0], a[1])), a[2], a[3]) for a in lst]
            rows = [x for x in rows if x[0] and x[1]]
            if rows:
                jo, jd = sum(x[0] for x in rows) / len(rows), sum(x[1] for x in rows) / len(rows)
                ppo = sum(x[2] for x in rows) / sum(x[0] for x in rows)           # puntos propios / jugadas propias
                ppd = sum(x[3] for x in rows) / sum(x[1] for x in rows)           # puntos del rival / jugadas del rival
        if t in of_w.index:
            OFF[t] = [ngames[t]] + _vec(ngames[t], pf, jo, ppo, of_w.loc[t])
        if t in de_w.index:
            DEF[t] = [ngames[t]] + _vec(ngames[t], pa, jd, ppd, de_w.loc[t])

    # proximo rival (primer juego sin marcador) y jugadores con sus promedios
    nxt = {}
    pend = g[g.home_score.isna() | g.away_score.isna()].sort_values("week")
    for x in pend.itertuples():
        for t, o, h in ((x.home_team, x.away_team, 1), (x.away_team, x.home_team, 0)):
            nxt.setdefault(t, [o, h, int(x.week)])

    pl = []
    for pid, d in p.groupby("player_id"):
        pos = d.position.iloc[-1]
        col, mn = MIN[pos]
        if d[col].sum() < mn:
            continue
        team = vig.get(pid) or d.sort_values("week").team.iloc[-1]       # equipo vigente (traspasos recientes)
        n = len(d[d.att > 0]) if pos == "QB" else len(d)
        dq = d[d.att > 0] if pos == "QB" else d
        ts = d.tshare.mean() * 100 if d.tshare.notna().any() else None
        yds = {"QB": dq.pass_yds, "RB": dq.rush_yds}.get(pos, dq.rec_yds).mean()
        pl.append([pid, d.name.iloc[-1], pos, team, int(n), _r(dq.cmp.mean(), 2) if pos == "QB" else None,
                   _r(dq.car.mean(), 2) if pos == "RB" else None, _r(ts, 1), _r(yds, 1)])
    return {"cur": cur, "teams": {t: nm(t) for t in equipos}, "cols": [[k, l, dec] for k, l, dec in COLS],
            "off": OFF, "def": DEF, "pl": pl, "nxt": nxt}


def _json(d) -> str:
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def html_proyecciones(d: dict | None) -> str:
    if not d:
        return ""
    return f"""<h2 id="proyecciones">PROYECCIONES · cuánto produce cada ofensiva y cuánto permite cada defensa</h2>
<nav class="subnav"><a href="#proyecciones">Cruce ofensiva vs defensa</a><a href="#proy-of">Ofensivas</a><a href="#proy-de">Defensas</a></nav>
<p class="explain">Promedios <b>por partido</b> de la temporada {d["cur"]} (solo temporada regular): lo que <b>produce</b> cada ofensiva y lo que <b>permite</b> cada defensa (lo que le hicieron sus rivales).
Sin líneas ni momios: solo cuánto es. En el <b>cruce</b> eliges un equipo y su rival (se rellena con el próximo partido) y ves, para las dos ofensivas, cuánto produce, cuánto permite la defensa contra la que juega
y la <b>proyección por volumen</b> (método Linemaker: volumen del equipo o jugador × lo que permite la defensa). Verde = de los 8 mejores de la liga, rojo = de los 8 peores. Es una segunda opinión basada en promedios;
<b>no cambia</b> las probabilidades del modelo ni es asesoría financiera.</p>
<div class="py" id="py">
<div class="py-r"><label>Equipo<select id="py-a"></select></label><label>Rival<select id="py-b"></select></label><button type="button" class="py-sw" id="py-sw">⇄ cambiar</button></div>
<div class="py-n" id="py-i"></div>
<div id="py-x"></div>
<h3 id="proy-of">Ofensivas: cuánto produce cada una por partido</h3>
<div class="py-n">Toca el nombre de una columna para ordenar. La fila de abajo es el promedio de la liga.</div>
<div class="scroll"><table class="py-t" id="py-to"></table></div>
<h3 id="proy-de">Defensas: cuánto permite cada una por partido</h3>
<div class="py-n">Menos es mejor para la defensa. «Pts por jugada» = puntos que anotaron sus rivales ÷ jugadas de sus rivales.</div>
<div class="scroll"><table class="py-t" id="py-td"></table></div>
<details class="py-conf"><summary>¿Qué tan confiable es esto?</summary>
<ul><li>Son promedios de la temporada: no ajustan por lesiones, clima, ritmo ni marcador probable. Con pocos partidos el promedio se mueve mucho (verás cuántos partidos entran).</li>
<li>Los números de pase y carrera son de los QB, RB, WR y TE de la base; «Yardas por acarreo» incluye acarreos de QB y de receptores. Las yardas de pase son brutas (no restan sacks).</li>
<li>«Jugadas» son los snaps ofensivos del equipo en cada partido terminado, sin quitar la «basura».</li>
<li>La proyección de puntos usa la fórmula del pizarrón: promedio de (jugadas × pts por jugada propios) y (jugadas × pts por jugada que permite el rival).</li>
<li>La lista de jugadores no sabe de lesiones de última hora. Úsalo como segunda opinión junto al modelo, no como reemplazo.</li></ul></details>
<script type="application/json" id="py-data">{_json(d)}</script>
</div>"""


CSS = """
.py{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:8px 0}
.py h3{margin:18px 0 4px}
.py-r{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:0 0 10px}
.py-r label{display:flex;flex-direction:column;font-size:.8rem;color:var(--ink2);gap:2px}
.py select{font:inherit;font-size:.95rem;padding:5px 6px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);min-width:12em;max-width:100%}
.py-sw{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}
.py-n{font-size:.8rem;color:var(--ink2);margin:2px 0 8px}
.py-t{border-collapse:collapse;width:100%;font-size:.85rem}.py-t th,.py-t td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;white-space:nowrap}
.py-t th:first-child,.py-t td:first-child{text-align:left}.py-t th{cursor:pointer;color:var(--ink2);font-weight:600;user-select:none}.py-t th.on{color:var(--blue)}
.py-t tr.lg td{font-weight:700;border-top:2px solid var(--line)}
.py-t td.g,.py-x td.g{color:#1f9d4d;font-weight:600}.py-t td.r,.py-x td.r{color:#d33a30;font-weight:600}
.py-x table{border-collapse:collapse;width:100%;font-size:.88rem;margin:4px 0 12px}.py-x th,.py-x td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right}
.py-x th:first-child,.py-x td:first-child{text-align:left}.py-x th{color:var(--ink2);font-weight:600}.py-x td.pr{font-weight:700;color:var(--blue)}
.py-x h4{margin:14px 0 2px}.py-conf{margin-top:14px}.py-conf ul{margin:6px 0 0 18px;padding:0}
"""

JS = r"""
<script>
(function(){
var el=document.getElementById('py-data');if(!el)return;
var D=JSON.parse(el.textContent),$=function(i){return document.getElementById(i);};
var H=function(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');};
var C=D.cols,K={};C.forEach(function(c,i){K[c[0]]=i+1;});      // columna i+1: la 0 es el numero de partidos
var teams=Object.keys(D.teams).sort();
function fm(v,dec){return v==null||isNaN(v)?'—':Number(v).toFixed(dec);}
// ---- formulas del pizarron
function projPase(cmp,ypc){return cmp*ypc;}
function projTierra(car,ypa){return car*ypa;}
function projWR(cmp,ypc,sh){return cmp*ypc*(sh>1?sh/100:sh);}
function projPts(j,po,pd){return (j*po+j*pd)/2;}
window.PY={projPase:projPase,projTierra:projTierra,projWR:projWR,projPts:projPts,D:D};
function ov(t,k){var v=D.off[t];return v?v[K[k]]:null;}
function dv(t,k){var v=D.def[t];return v?v[K[k]]:null;}
// ---- tablas ofensiva / defensa (ordenables, con color por ranking)
var sortO={k:'pts',d:-1},sortD={k:'pts',d:1};
function table(id,src,st,alto){
 var T=$(id),ks=C.map(function(c){return c[0];}),rows=teams.filter(function(t){return src[t];}),rank={};
 ks.forEach(function(k){var a=rows.slice().sort(function(x,y){return (src[y][K[k]]||0)-(src[x][K[k]]||0);});rank[k]={};a.forEach(function(t,i){rank[k][t]=i;});});
 // ofensiva: mas = mejor. defensa: menos = mejor
 function cls(k,t){var i=rank[k][t],n=rows.length,top=8;var best=alto?i<top:i>=n-top,bad=alto?i>=n-top:i<top;
  if(k==='jug'||k==='att'||k==='car'||k==='cmp')return '';return best?'g':(bad?'r':'');}
 rows.sort(function(x,y){var a=src[x][K[st.k]],b=src[y][K[st.k]];a=a==null?-1e9:a;b=b==null?-1e9:b;return st.d*(b-a)*-1;});
 var h='<tr><th data-s="n">Equipo</th><th>PJ</th>'+C.map(function(c){return '<th data-s="'+c[0]+'" class="'+(st.k===c[0]?'on':'')+'">'+c[1]+(st.k===c[0]?(st.d<0?' ▼':' ▲'):'')+'</th>';}).join('')+'</tr>';
 rows.forEach(function(t){h+='<tr><td title="'+H(D.teams[t])+'"><b>'+t+'</b></td><td>'+src[t][0]+'</td>'+C.map(function(c){return '<td class="'+cls(c[0],t)+'">'+fm(src[t][K[c[0]]],c[2])+'</td>';}).join('')+'</tr>';});
 h+='<tr class="lg"><td>Liga</td><td></td>'+C.map(function(c){var s=0,n=0;rows.forEach(function(t){var v=src[t][K[c[0]]];if(v!=null){s+=v;n++;}});return '<td>'+fm(n?s/n:null,c[2])+'</td>';}).join('')+'</tr>';
 T.innerHTML=h;}
function tables(){table('py-to',D.off,sortO,true);table('py-td',D.def,sortD,false);}
function sortClick(e,st,fn){var th=e.target.closest('th');if(!th||!th.dataset.s)return;var k=th.dataset.s;if(k==='n'){st.k='pts';st.d=-1;}else{if(st.k===k)st.d=-st.d;else{st.k=k;st.d=-1;}}fn();}
// ---- cruce
function teamOpts(sel){return teams.map(function(t){return '<option value="'+t+'"'+(t===sel?' selected':'')+'>'+H(t+' · '+D.teams[t])+'</option>';}).join('');}
function lado(A,B){ // ofensiva de A contra la defensa de B
 var o=D.off[A],d=D.def[B];if(!o||!d)return '<div class="py-n">Sin datos suficientes de '+A+' o '+B+'.</div>';
 var cmp=ov(A,'cmp'),car=ov(A,'car'),ypcP=dv(B,'ypc'),ypaP=dv(B,'ypa');
 var pp=cmp!=null&&ypcP!=null?projPase(cmp,ypcP):null,pt=car!=null&&ypaP!=null?projTierra(car,ypaP):null;
 var pu=(ov(A,'jug')!=null&&ov(A,'ppj')!=null&&dv(B,'ppj')!=null)?projPts(ov(A,'jug'),ov(A,'ppj'),dv(B,'ppj')):null;
 function row(l,k,dec,proj){return '<tr><td>'+l+'</td><td>'+fm(ov(A,k),dec)+'</td><td>'+fm(dv(B,k),dec)+'</td><td class="pr">'+(proj==null?'—':fm(proj,dec))+'</td></tr>';}
 var h='<h4>Ofensiva de '+H(D.teams[A])+' ('+o[0]+' partidos) contra la defensa de '+H(D.teams[B])+' ('+d[0]+' partidos)</h4>'+
  '<table><tr><th></th><th>'+A+' produce</th><th>'+B+' permite</th><th>Proyección</th></tr>'+
  row('Puntos','pts',1,pu)+row('Jugadas','jug',1,null)+row('Pts por jugada','ppj',3,null)+
  row('Yardas de pase','pyd',1,pp)+row('Completos','cmp',1,null)+row('Yds por completo','ypc',2,null)+
  row('Yardas por tierra','ryd',1,pt)+row('Acarreos','car',1,null)+row('Yds por acarreo','ypa',2,null)+
  row('Yardas totales','tyd',1,pp!=null&&pt!=null?pp+pt:null)+'</table>';
 // jugadores del equipo A
 var L=D.pl.filter(function(x){return x[3]===A;}),qb=L.filter(function(x){return x[2]==='QB';}).sort(function(a,b){return b[4]-a[4];}).slice(0,2),
  rb=L.filter(function(x){return x[2]==='RB';}).sort(function(a,b){return (b[6]||0)-(a[6]||0);}).slice(0,3),
  wr=L.filter(function(x){return x[2]==='WR'||x[2]==='TE';}).sort(function(a,b){return (b[7]||0)-(a[7]||0);}).slice(0,6),pr='';
 qb.forEach(function(x){var v=x[5]!=null&&ypcP!=null?projPase(x[5],ypcP):null;pr+='<tr><td>'+H(x[1])+' · QB</td><td>'+x[4]+'</td><td>'+fm(x[5],1)+' completos</td><td>'+fm(x[8],1)+'</td><td class="pr">'+fm(v,1)+'</td></tr>';});
 rb.forEach(function(x){var v=x[6]!=null&&ypaP!=null?projTierra(x[6],ypaP):null;pr+='<tr><td>'+H(x[1])+' · RB</td><td>'+x[4]+'</td><td>'+fm(x[6],1)+' acarreos</td><td>'+fm(x[8],1)+'</td><td class="pr">'+fm(v,1)+'</td></tr>';});
 wr.forEach(function(x){var v=x[7]!=null&&cmp!=null&&ypcP!=null?projWR(cmp,ypcP,x[7]):null;pr+='<tr><td>'+H(x[1])+' · '+x[2]+'</td><td>'+x[4]+'</td><td>'+fm(x[7],1)+' % target share</td><td>'+fm(x[8],1)+'</td><td class="pr">'+fm(v,1)+'</td></tr>';});
 if(pr)h+='<table><tr><th>Jugador</th><th>PJ</th><th>Volumen por partido</th><th>Yardas promedio</th><th>Proyección de yardas vs '+B+'</th></tr>'+pr+'</table>';
 return h;}
function cruce(setRival){
 var A=$('py-a').value,B=$('py-b').value;
 if(setRival){var n=D.nxt[A];if(n){B=n[0];$('py-b').value=B;}}
 var n1=D.nxt[A];$('py-i').textContent=n1?('Próximo partido de '+A+': '+(n1[1]?'vs':'@')+' '+n1[0]+' (semana '+n1[2]+').'+(n1[0]!==B?' Estás viendo otro cruce.':'')):'Sin próximo partido en el calendario: elige tú el rival.';
 $('py-x').innerHTML=lado(A,B)+lado(B,A);}
document.addEventListener('change',function(e){var t=e.target;if(!t.closest||!t.closest('#py'))return;if(t.id==='py-a')cruce(true);else if(t.id==='py-b')cruce(false);});
document.addEventListener('click',function(e){var t=e.target;if(!t.closest||!t.closest('#py'))return;
 if(t.closest('#py-sw')){var a=$('py-a').value;$('py-a').value=$('py-b').value;$('py-b').value=a;cruce(false);return;}
 if(t.closest('#py-to')){sortClick(e,sortO,tables);return;}if(t.closest('#py-td')){sortClick(e,sortD,tables);}});
var A0=teams.filter(function(t){return D.nxt[t];})[0]||teams[0];
$('py-a').innerHTML=teamOpts(A0);$('py-b').innerHTML=teamOpts(D.nxt[A0]?D.nxt[A0][0]:teams[1]);
cruce(true);tables();
})();
</script>
"""
