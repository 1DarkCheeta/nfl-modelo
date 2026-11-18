"""PROYECCIONES: proyeccion por volumen (metodo del pizarron de @linemakersports) como pestana aparte de la pagina.

Es la version estatica (HTML + JS embebido) de `proyeccion_linemaker.py`. Reglas:
- Solo LEE datos (player_weeks, juegos, team_games). No escribe en la base ni cambia ningun calculo del modelo.
- Todo lo que dibuja lleva el prefijo `py-` / `#py` para no chocar con las demas secciones.
- Las formulas son las mismas del archivo original (ver `proy_*` en el JS) y se probaron contra la version en Python.

Formulas:
  QB   yardas de pase     = completos por partido x yardas por completo que permite la defensa rival
  WR   yardas de recepcion = completos del QB x yardas por completo permitidas x target share
  RB   yardas por tierra  = acarreos por partido x yardas por acarreo que permite la defensa rival
  Equipo puntos           = (jugadas x pts por jugada propios + jugadas x pts por jugada que permite el rival) / 2
  1T   puntos en el 1T    = (lo que anota en 1T + lo que permite el rival en 1T) / 2   (no hay marcador por mitades en la base: se escribe a mano)
  % over/under = distribucion normal con desviacion de referencia (QB 60, WR 25, RB 25, equipo 7, 1T 5)
"""
from __future__ import annotations

import html
import json

import pandas as pd

DESV = {"QB": 60.0, "WR": 25.0, "RB": 25.0, "TEAM": 7.0, "1T": 5.0}
MIN = {"QB": ("att", 20), "RB": ("car", 10), "WR": ("tgt", 8), "TE": ("tgt", 8)}   # para no listar a quien casi no juega


def _r(x, n=3):
    return None if x is None or pd.isna(x) else round(float(x), n)


def construir(r: dict, extras: dict, nm=lambda t: t) -> dict | None:
    pw, games = extras.get("pw"), r.get("games")
    if pw is None or len(pw) == 0 or games is None or len(games) == 0:
        return None
    cur = int(extras.get("cur") or r["cur"])
    g = games[games.get("game_type", "REG") == "REG"] if "game_type" in games else games
    g = g[g.season == cur]
    p = pw[(pw.season == cur) & pw.position.isin(["QB", "RB", "WR", "TE"])]
    if "season_type" in p:
        p = p[p.season_type.fillna("REG") == "REG"]
    if len(p) == 0 or len(g) == 0:
        return None
    fin = g.dropna(subset=["home_score", "away_score"])
    vig = extras.get("vigente") or {}

    # rival de cada equipo en cada semana (solo juegos terminados)
    opp = {}
    for x in fin.itertuples():
        opp[(int(x.week), x.home_team)] = x.away_team
        opp[(int(x.week), x.away_team)] = x.home_team
    p = p.assign(opp=[opp.get((int(w), t)) for w, t in zip(p.week, p.team)])
    pj = p.dropna(subset=["opp"])

    # lo que PERMITE cada defensa: yardas por completo y por acarreo
    perm = {}
    for t, d in pj.groupby("opp"):
        c, y, a, ry = d.cmp.sum(), d.pass_yds.sum(), d.car.sum(), d.rush_yds.sum()
        perm[t] = {"ypc": y / c if c > 0 else None, "ypa": ry / a if a > 0 else None}

    # jugadas (snaps ofensivos del equipo en el partido, sin filtro de "basura") y puntos por jugada:
    # propios = puntos / jugadas; permitidos = puntos del rival / jugadas del rival
    of, de = {}, {}
    try:
        import db
        sn = db.leer("snaps", [cur])
    except Exception:
        sn = None
    if sn is not None and len(sn):
        gw = fin[["game_id", "week"]].drop_duplicates()
        pt = p[["player_id", "week", "team"]].drop_duplicates()
        tp = sn.merge(gw, on="game_id").merge(pt, on=["player_id", "week"]).groupby(["game_id", "team"]).offense_snaps.max()
        rows = []
        for x in fin.itertuples():
            for t, o, ps, pr in ((x.home_team, x.away_team, x.home_score, x.away_score), (x.away_team, x.home_team, x.away_score, x.home_score)):
                a_, b_ = tp.get((x.game_id, t)), tp.get((x.game_id, o))
                if a_ and b_:
                    rows.append((t, o, float(a_), float(b_), float(ps), float(pr)))
        tg = pd.DataFrame(rows, columns=["team", "opp", "plays", "plays_rival", "pts", "ptsr"])
        for t, d in tg.groupby("team"):
            of[t] = {"n": len(d), "jug": d.plays.mean(), "ppj": d.pts.sum() / d.plays.sum()}
            de[t] = {"ppj": d.ptsr.sum() / d.plays_rival.sum()}
    # completos del QB por partido de cada equipo (suma del equipo por semana)
    cmp_eq = p.groupby(["team", "week"]).cmp.sum().groupby("team").mean().to_dict()

    # proximo rival de cada equipo (primer juego sin marcador)
    nxt = {}
    pend = g[g.home_score.isna() | g.away_score.isna()].sort_values("week")
    for x in pend.itertuples():
        for t, o, h in ((x.home_team, x.away_team, 1), (x.away_team, x.home_team, 0)):
            nxt.setdefault(t, [o, h, int(x.week)])

    equipos = sorted(set(g.home_team) | set(g.away_team))
    DEF = {}
    for t in equipos:
        a, b, c = perm.get(t, {}), of.get(t, {}), de.get(t, {})
        DEF[t] = [_r(a.get("ypc")), _r(a.get("ypa")), _r(c.get("ppj"), 4), _r(b.get("jug"), 1), _r(b.get("ppj"), 4), _r(cmp_eq.get(t), 1), int(b.get("n", 0))]

    # jugadores: promedios de la temporada
    pl = []
    for pid, d in p.groupby("player_id"):
        pos = d.position.iloc[-1]
        col, mn = MIN[pos]
        if d[col].sum() < mn:
            continue
        team = vig.get(pid) or d.sort_values("week").team.iloc[-1]     # equipo vigente (traspasos recientes)
        if pos == "QB":
            dq = d[d.att > 0]
            cp, ca, ts = dq.cmp.mean() if len(dq) else None, None, None
        elif pos == "RB":
            cp, ca, ts = None, d.car.mean(), d.tshare.mean() * 100 if d.tshare.notna().any() else None
        else:
            cp, ca, ts = None, None, d.tshare.mean() * 100 if d.tshare.notna().any() else None
        pl.append([pid, d.name.iloc[-1], pos, team, int(len(d)), _r(cp, 2), _r(ca, 2), _r(ts, 1)])
    pl.sort(key=lambda x: (x[3], ["QB", "RB", "WR", "TE"].index(x[2]), -x[4], x[1]))
    return {"cur": cur, "teams": {t: nm(t) for t in equipos}, "def": DEF, "pl": pl, "nxt": nxt, "desv": DESV}


def _json(d) -> str:
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def html_proyecciones(d: dict | None) -> str:
    if not d:
        return ""
    return f"""<h2 id="proyecciones">PROYECCIONES · proyección por volumen (método Linemaker)</h2>
<p class="explain">Cálculo <b>aparte y solo de referencia</b>: volumen del jugador × lo que permite la defensa rival. <b>No modifica ni reemplaza</b> las probabilidades del modelo.
Elige equipo, jugador y rival (el rival se rellena solo con su próximo partido; puedes cambiarlo); los números salen de los promedios de la temporada {d["cur"]} y todos se pueden editar.
Escribe la línea y el momio de tu app (por ejemplo −110, +105) para ver el porcentaje de Over/Under, lo que implica el momio y la ventaja. Es una <b>segunda opinión</b>, no una apuesta segura ni asesoría financiera.</p>
<div class="py" id="py">
<div class="py-nav" role="tablist">
<button type="button" class="py-b on" data-p="qb">QB</button><button type="button" class="py-b" data-p="wr">WR / TE</button><button type="button" class="py-b" data-p="rb">RB</button>
<button type="button" class="py-b" data-p="tt">Puntos de equipo</button><button type="button" class="py-b" data-p="t1">1er tiempo</button><button type="button" class="py-b" data-p="hr">Ventaja (hit rate)</button>
</div>
<div class="py-p on" data-p="qb"></div><div class="py-p" data-p="wr"></div><div class="py-p" data-p="rb"></div>
<div class="py-p" data-p="tt"></div><div class="py-p" data-p="t1"></div><div class="py-p" data-p="hr"></div>
<details class="py-conf"><summary>¿Qué tan confiable es esto?</summary>
<ul><li>Usa promedios de la temporada: no ajusta por lesiones, clima, ritmo ni marcador probable. Con pocos partidos (verás cuántos) el promedio se mueve mucho.</li>
<li>El % Over/Under sale de una distribución normal con desviaciones aproximadas (QB 60, WR 25, RB 25, equipo 7, 1er tiempo 5); son valores de referencia.</li>
<li>«Yardas por acarreo permitidas» cuenta los acarreos de QB, RB, WR y TE contra esa defensa; «puntos por jugada» usa los snaps ofensivos del equipo en cada partido terminado (sin quitar la «basura»).</li>
<li>No hay marcador por mitades en la base de datos, así que en «1er tiempo» escribes tú los puntos que anota y permite cada equipo en el 1T.</li>
<li>Úsalo como segunda opinión junto al modelo, no como reemplazo.</li></ul></details>
<script type="application/json" id="py-data">{_json(d)}</script>
</div>"""


CSS = """
.py{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:8px 0}
.py-nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
.py-b{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:6px 14px;font:inherit;font-weight:600;cursor:pointer}
.py-b.on{background:var(--blue);border-color:var(--blue);color:#fff}
.py-p{display:none}.py-p.on{display:block}
.py-f{margin:0 0 8px;color:var(--ink2);font-size:.9rem}
.py-r{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:0 0 10px}
.py-r label{display:flex;flex-direction:column;font-size:.8rem;color:var(--ink2);gap:2px}
.py select,.py input[type=number],.py input[type=text]{font:inherit;font-size:.95rem;padding:5px 6px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);max-width:100%}
.py input[type=number],.py input[type=text]{width:7.5em;text-align:right}
.py select{min-width:12em}
.py-n{font-size:.78rem;color:var(--ink2);margin:-4px 0 8px}
.py-k{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:8px 0}
.py-c{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.py-c .l{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink2)}.py-c .v{font-size:2.1rem;font-weight:700;line-height:1.1;margin:2px 0}.py-c .s{font-size:.82rem;color:var(--ink2)}
.py-v{border-radius:10px;padding:10px 14px;margin:8px 0;line-height:1.45}
.py-v.ok{background:#dff3e4;color:#14532d}.py-v.mid{background:#e1ecfa;color:#1e3a5f}.py-v.no{background:#fde7c8;color:#7a3d00}
@media(prefers-color-scheme:dark){.py-v.ok{background:#173b25;color:#bfe9cb}.py-v.mid{background:#1c2f48;color:#c5d9f2}.py-v.no{background:#4a3414;color:#f5d9a8}}
.py-conf{margin-top:12px}.py-conf ul{margin:6px 0 0 18px;padding:0}
"""

JS = r"""
<script>
(function(){
var el=document.getElementById('py-data');if(!el)return;
var D=JSON.parse(el.textContent),R=document.getElementById('py'),$=function(i){return document.getElementById(i);};
var H=function(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');};
var DEF={QB:[20,11],RB:[15,4.3],TEAM:[63,0.35,0.35]};
// ---- formulas (mismas que proyeccion_linemaker.py)
function projQB(c,y){return c*y;}
function projWR(c,y,s){var sh=s>1?s/100:s;return c*y*sh;}
function projRB(a,y){return a*y;}
function projTeam(j,po,pd){return (j*po+j*pd)/2;}
function proj1T(a,b){return (a+b)/2;}
function erf(x){var s=x<0?-1:1;x=Math.abs(x);var t=1/(1+0.3275911*x),y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return s*y;}
function cdf(x,mu,sd){return 0.5*(1+erf((x-mu)/(sd*Math.SQRT2)));}
function probOver(p,l,sd){if(sd<=0)return p>l?1:0;return 1-cdf(l,p,sd);}
function probImpl(m){return m<0?-m/(-m+100):100/(m+100);}
function realHR(a,b){return (a+b)/2;}
function amer(v){v=parseFloat(String(v).replace(/[−–—]/g,'-').replace('+','').trim());return (isNaN(v)||Math.abs(v)<100)?NaN:v;}
function pc(p){return (Math.round(p*1000)/10).toFixed(1)+'%';}
function f1(x){return x==null||isNaN(x)?'—':(Math.round(x*10)/10).toFixed(1);}
function num(id,d){var v=parseFloat($(id).value);return isNaN(v)?d:v;}
function fld(id,l,v,st){return '<label>'+l+'<input type="number" id="'+id+'" step="'+(st||'any')+'" value="'+(v==null?'':v)+'"></label>';}
// ---- selectores
var teams=Object.keys(D.teams).sort();
function selTeams(id,all){return '<label>Equipo<select id="'+id+'">'+(all?'<option value="">Todos</option>':'')+teams.map(function(t){return '<option value="'+t+'">'+H(t+' · '+D.teams[t])+'</option>';}).join('')+'</select></label>';}
function selDef(id){return '<label>Defensa rival<select id="'+id+'">'+teams.map(function(t){return '<option value="'+t+'">'+H(t+' · '+D.teams[t])+'</option>';}).join('')+'</select></label>';}
function plOpts(pos,team){var L=D.pl.filter(function(p){return (pos.indexOf(p[2])>=0)&&(!team||p[3]===team);});
 return L.length?L.map(function(p){return '<option value="'+p[0]+'">'+H(p[1]+' · '+p[2]+' · '+p[3]+' ('+p[4]+' partidos)')+'</option>';}).join(''):'<option value="">Sin jugadores</option>';}
function P(pid){for(var i=0;i<D.pl.length;i++)if(D.pl[i][0]===pid)return D.pl[i];return null;}
function rivalOf(t){var n=D.nxt[t];return n?n[0]:null;}
function nxtTxt(t){var n=D.nxt[t];return n?'Próximo partido de '+t+': '+(n[1]?'vs':'@')+' '+n[0]+' (semana '+n[2]+')':'Sin próximo partido en el calendario: elige tú la defensa rival.';}
// ---- bloque de resultado (proyeccion + linea + momios)
function resBlock(k,name){return '<h4>'+name+'</h4><div class="py-k"><div class="py-c"><div class="l">Proyección</div><div class="v" id="py-'+k+'-pr">—</div><div class="s">'+name+'</div></div></div>'+
 '<div class="py-r">'+fld('py-'+k+'-ln','Línea de tu app',null,0.5)+'<label>Momio Over<input type="text" id="py-'+k+'-mo" inputmode="text" value="-110" autocomplete="off"></label><label>Momio Under<input type="text" id="py-'+k+'-mu" inputmode="text" value="-110" autocomplete="off"></label></div>'+
 '<div id="py-'+k+'-out"></div>';}
function showRes(k,proj,sd,setLine){
 var ln=$('py-'+k+'-ln');if(setLine||ln.value==='')ln.value=Math.round(proj*2)/2;
 $('py-'+k+'-pr').textContent=f1(proj);
 var L=parseFloat(ln.value),mo=amer($('py-'+k+'-mo').value),mu=amer($('py-'+k+'-mu').value),out=$('py-'+k+'-out');
 if(isNaN(L)){out.innerHTML='<div class="py-v mid">Escribe la línea.</div>';return;}
 var po=probOver(proj,L,sd),pu=1-po,over=po>=pu,lado=over?'MÁS DE (over)':'MENOS DE (under)',pl=over?po:pu,m=over?mo:mu;
 var h='<div class="py-v mid"><b>'+lado+' '+L+'</b> → probabilidad estimada <b>'+pc(pl)+'</b> (Over '+pc(po)+' · Under '+pc(pu)+')';
 if(isNaN(m)){h+=' · escribe el momio '+(over?'Over':'Under')+' de tu app para ver la ventaja.</div>';out.innerHTML=h;return;}
 var pi=probImpl(m),v=pl-pi,cls=v>0.05?'ok':(v>0?'mid':'no');
 h+=' · el momio '+(m>0?'+':'−')+Math.abs(m)+' implica <b>'+pc(pi)+'</b> · ventaja <b>'+(v>=0?'+':'')+(Math.round(v*1000)/10).toFixed(1)+' pts</b></div>';
 h+='<div class="py-v '+cls+'">'+(v>0.05?'Hay ventaja según este método.':(v>0?'Ventaja pequeña: apuesta dudosa.':'Sin ventaja: el momio ya descuenta esta probabilidad.'))+'</div>';
 var o2=over?mu:mo;if(!isNaN(o2)){var pi2=probImpl(o2),pl2=over?pu:po,v2=pl2-pi2;h+='<div class="py-n">El otro lado ('+(over?'Under':'Over')+' '+(o2>0?'+':'−')+Math.abs(o2)+'): modelo '+pc(pl2)+' vs momio '+pc(pi2)+' → '+(v2>=0?'+':'')+(Math.round(v2*1000)/10).toFixed(1)+' pts</div>';}
 out.innerHTML=h;}
// ---- paneles
function defv(t,i){var d=D.def[t];return d&&d[i]!=null?d[i]:null;}
function build(){
 $$('qb').innerHTML='<div class="py-f"><b>Yardas de pase = completos por partido × yardas por completo que permite la defensa</b></div><div class="py-r">'+selTeams('py-qb-t',true)+'<label>QB<select id="py-qb-p"></select></label>'+selDef('py-qb-d')+'</div><div class="py-n" id="py-qb-i"></div>'+
  '<div class="py-r">'+fld('py-qb-c','Completos por partido',null)+fld('py-qb-y','Yardas por completo permitidas',null)+'</div>'+resBlock('qb','yardas de pase');
 $$('wr').innerHTML='<div class="py-f"><b>Yardas de recepción = completos del QB × yardas por completo permitidas × target share</b></div><div class="py-r">'+selTeams('py-wr-t',true)+'<label>WR / TE<select id="py-wr-p"></select></label>'+selDef('py-wr-d')+'</div><div class="py-n" id="py-wr-i"></div>'+
  '<div class="py-r">'+fld('py-wr-c','Completos del QB por partido',null)+fld('py-wr-y','Yardas por completo permitidas',null)+fld('py-wr-s','Target share (%)',null)+'</div>'+resBlock('wr','yardas de recepción');
 $$('rb').innerHTML='<div class="py-f"><b>Yardas por tierra = acarreos por partido × yardas por acarreo que permite la defensa</b></div><div class="py-r">'+selTeams('py-rb-t',true)+'<label>RB<select id="py-rb-p"></select></label>'+selDef('py-rb-d')+'</div><div class="py-n" id="py-rb-i"></div>'+
  '<div class="py-r">'+fld('py-rb-a','Acarreos por partido',null)+fld('py-rb-y','Yardas por acarreo permitidas',null,0.1)+'</div>'+resBlock('rb','yardas por tierra');
 $$('tt').innerHTML='<div class="py-f"><b>Puntos = promedio de (jugadas × pts por jugada propios) y (jugadas × pts por jugada que permite el rival)</b></div><div class="py-r">'+selTeams('py-tt-t',false)+selDef('py-tt-d')+'</div><div class="py-n" id="py-tt-i"></div>'+
  '<div class="py-r">'+fld('py-tt-j','Jugadas por partido',null)+fld('py-tt-o','Pts por jugada (ofensiva)',null,0.01)+fld('py-tt-r','Pts por jugada permitidos (rival)',null,0.01)+'</div>'+resBlock('tt','puntos del equipo');
 $$('t1').innerHTML='<div class="py-f"><b>Puntos en 1T = (lo que anota en 1T + lo que permite el rival en 1T) ÷ 2</b></div><div class="py-n">No hay marcador por mitades en la base de datos: escribe los dos promedios tú.</div><div class="py-r">'+fld('py-t1-a','Pts que anota en 1T',11)+fld('py-t1-b','Pts que permite el rival en 1T',11)+'</div>'+resBlock('t1','puntos en 1T');
 $$('hr').innerHTML='<div class="py-f"><b>Probabilidad real = promedio de hit rate de temporada y del enfrentamiento; ventaja = esa probabilidad − la del momio</b></div><div class="py-r">'+fld('py-hr-a','Hit rate temporada (%)',80,1)+fld('py-hr-b','Hit rate vs rival / tipo de defensa (%)',80,1)+'<label>Momio (americano)<input type="text" id="py-hr-m" value="-250" inputmode="text" autocomplete="off"></label></div><div id="py-hr-out"></div>';}
function $$(p){return R.querySelector('.py-p[data-p="'+p+'"]');}
function fill(k){ // rellena los numeros desde los datos al cambiar equipo / jugador / defensa
 var t=$('py-'+k+'-t')?$('py-'+k+'-t').value:'';
 if(k==='qb'||k==='wr'||k==='rb'){var pos=k==='qb'?['QB']:(k==='rb'?['RB']:['WR','TE']);var cur=$('py-'+k+'-p');cur.innerHTML=plOpts(pos,t);}
}
function pick(k,setDef){var p=P($('py-'+k+'-p').value),team=p?p[3]:($('py-'+k+'-t')?$('py-'+k+'-t').value:''),d=$('py-'+k+'-d');
 if(setDef){var rv=rivalOf(team);if(rv)d.value=rv;}
 var inf=$('py-'+k+'-i');if(inf)inf.textContent=(p?p[1]+': '+p[4]+' partidos jugados en '+D.cur+'. ':'')+nxtTxt(team);
 return {p:p,team:team};}
function setv(id,v,dec){if(v!=null&&!isNaN(v))$(id).value=Math.round(v*Math.pow(10,dec))/Math.pow(10,dec);else $(id).value='';}
function loadQB(ch){var s=pick('qb',ch!=='d');var d=$('py-qb-d').value;if(ch!=='d'){setv('py-qb-c',s.p&&s.p[5]!=null?s.p[5]:DEF.QB[0],1);}setv('py-qb-y',defv(d,0)!=null?defv(d,0):DEF.QB[1],2);calcQB(true);}
function loadWR(ch){var s=pick('wr',ch!=='d'),d=$('py-wr-d').value;setv('py-wr-c',s.team&&defv(s.team,5)!=null?defv(s.team,5):20,1);setv('py-wr-y',defv(d,0)!=null?defv(d,0):11,2);setv('py-wr-s',s.p&&s.p[7]!=null?s.p[7]:25,1);calcWR(true);}
function loadRB(ch){var s=pick('rb',ch!=='d'),d=$('py-rb-d').value;setv('py-rb-a',s.p&&s.p[6]!=null?s.p[6]:DEF.RB[0],1);setv('py-rb-y',defv(d,1)!=null?defv(d,1):DEF.RB[1],2);calcRB(true);}
function loadTT(){var t=$('py-tt-t').value,d=$('py-tt-d').value,rv=rivalOf(t);if(rv&&d!==rv)$('py-tt-d').value=rv;d=$('py-tt-d').value;
 $('py-tt-i').textContent=nxtTxt(t)+(D.def[t]?' · '+D.def[t][6]+' partidos en la muestra.':'');
 setv('py-tt-j',defv(t,3)!=null?defv(t,3):DEF.TEAM[0],1);setv('py-tt-o',defv(t,4)!=null?defv(t,4):DEF.TEAM[1],3);setv('py-tt-r',defv(d,2)!=null?defv(d,2):DEF.TEAM[2],3);calcTT(true);}
function calcQB(s){showRes('qb',projQB(num('py-qb-c',20),num('py-qb-y',11)),D.desv.QB,s);}
function calcWR(s){showRes('wr',projWR(num('py-wr-c',20),num('py-wr-y',11),num('py-wr-s',25)),D.desv.WR,s);}
function calcRB(s){showRes('rb',projRB(num('py-rb-a',15),num('py-rb-y',4.3)),D.desv.RB,s);}
function calcTT(s){showRes('tt',projTeam(num('py-tt-j',63),num('py-tt-o',0.35),num('py-tt-r',0.35)),D.desv.TEAM,s);}
function calc1T(s){showRes('t1',proj1T(num('py-t1-a',11),num('py-t1-b',11)),D.desv['1T'],s);}
function calcHR(){var a=num('py-hr-a',80),b=num('py-hr-b',80),m=amer($('py-hr-m').value),o=$('py-hr-out');if(isNaN(m)){o.innerHTML='<div class="py-v mid">Escribe el momio (ej. -250).</div>';return;}
 var real=realHR(a,b)/100,imp=probImpl(m),v=real-imp;o.innerHTML='<div class="py-k"><div class="py-c"><div class="l">Ventaja</div><div class="v">'+(v>=0?'+':'')+(Math.round(v*1000)/10).toFixed(1)+' pts</div><div class="s">Real '+pc(real)+' vs implícita '+pc(imp)+'</div></div></div>';}
// ---- eventos (delegados, solo dentro de #py)
document.addEventListener('change',function(e){var t=e.target;if(!t.closest||!t.closest('#py'))return;var id=t.id||'';
 if(id==='py-qb-t'){fill('qb');loadQB();}else if(id==='py-qb-p'||id==='py-qb-d'){loadQB(id==='py-qb-d'?'d':'p');}
 else if(id==='py-wr-t'){fill('wr');loadWR();}else if(id==='py-wr-p'||id==='py-wr-d'){loadWR(id==='py-wr-d'?'d':'p');}
 else if(id==='py-rb-t'){fill('rb');loadRB();}else if(id==='py-rb-p'||id==='py-rb-d'){loadRB(id==='py-rb-d'?'d':'p');}
 else if(id==='py-tt-t'||id==='py-tt-d'){loadTT();}});
document.addEventListener('input',function(e){var t=e.target;if(!t.closest||!t.closest('#py'))return;var id=t.id||'';
 var m=id.match(/^py-(qb|wr|rb|tt|t1)-/);if(m){var k=m[1],s=/-ln$/.test(id)||/-m[ou]$/.test(id);
  ({qb:calcQB,wr:calcWR,rb:calcRB,tt:calcTT,t1:calc1T})[k](false);}
 else if(/^py-hr-/.test(id))calcHR();});
document.addEventListener('click',function(e){var t=e.target.closest?e.target.closest('#py .py-b'):null;if(!t)return;
 R.querySelectorAll('.py-b').forEach(function(b){b.classList.toggle('on',b===t);});R.querySelectorAll('.py-p').forEach(function(p){p.classList.toggle('on',p.dataset.p===t.dataset.p);});});
build();fill('qb');fill('wr');fill('rb');loadQB();loadWR();loadRB();loadTT();calc1T(true);calcHR();
window.PY={projQB:projQB,projWR:projWR,projRB:projRB,projTeam:projTeam,proj1T:proj1T,probOver:probOver,probImpl:probImpl,realHR:realHR,D:D};
})();
</script>
"""
