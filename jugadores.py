"""Explorador de jugadores: los 32 equipos, cualquier QB / RB / WR / TE, semana a semana contra una linea (Hit Rate).

Es la version estatica (HTML + JavaScript, sin servidor) del dashboard «NFL Props Tracker» de Streamlit, integrada a la pagina del modelo.
Reglas identicas a las del dashboard (metrics.py):
  - Over cubre si real > linea; Under cubre si real < linea; Push (igual) no cuenta; «No jugo» y «Sin linea» no cuentan.
  - Hit Rate = cubrio / (cubrio + no cubrio).
  - Local / Visitante sale del calendario (equipo designado como local).
Todo se calcula en el navegador con datos embebidos (`construir`); la linea es editable y por defecto es la «normal» del modelo
(o el promedio de la temporada si el jugador no tiene proyeccion).
Este modulo solo arma datos y HTML; no cambia ningun calculo del modelo.
"""
from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd

# (clave, etiqueta, unidad, columna en player_weeks). Los 7 primeros son los del dashboard; el resto, los que ya usa el modelo.
MERCADOS = [
    ("pass_yds", "Yardas de pase", "Yardas"), ("pass_td", "TDs de pase", "TDs"), ("rush_yds", "Yardas por tierra", "Yardas"),
    ("rush_att", "Acarreos", "Acarreos"), ("rec", "Recepciones", "Recepciones"), ("rec_yds", "Yardas por recepción", "Yardas"),
    ("td", "TD en cualquier momento", "TDs"), ("pass_cmp", "Pases completos", "Pases"), ("pass_int", "Intercepciones lanzadas", "INT"),
    ("tgt", "Objetivos (targets)", "Targets"), ("pass_att", "Intentos de pase", "Pases"), ("rush_td", "TDs por tierra", "TDs"),
    ("rec_td", "TDs por recepción", "TDs"), ("rush_rec_yds", "Yardas por tierra + recepción", "Yardas"),
]
# estadisticas que tienen sentido por posicion (el selector de «Estadística» solo muestra estas)
MKPOS = {
    "QB": ["pass_yds", "pass_att", "pass_cmp", "pass_td", "pass_int", "rush_yds", "rush_att", "td"],
    "RB": ["rush_yds", "rush_att", "rec", "rec_yds", "rush_rec_yds", "tgt", "td", "rush_td", "rec_td"],
    "WR": ["rec_yds", "rec", "tgt", "td", "rec_td", "rush_yds", "rush_att"],
    "TE": ["rec_yds", "rec", "tgt", "td", "rec_td"],
}
DEFECTO = {"QB": "pass_yds", "RB": "rush_yds", "WR": "rec_yds", "TE": "rec_yds"}
POS = ("QB", "RB", "WR", "TE")
TITULARES = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
ESTADO_ES = {"Questionable": "Cuestionable", "Doubtful": "Dudoso", "Out": "Fuera"}


def _valores(pw: pd.DataFrame) -> pd.DataFrame:
    d = pw.copy()
    d["pass_cmp"], d["rush_att"], d["pass_att"] = d["cmp"], d["car"], d["att"]
    d["rush_rec_yds"] = d["rush_yds"].fillna(0) + d["rec_yds"].fillna(0)
    d["td"] = d["rush_td"].fillna(0) + d["rec_td"].fillna(0)
    return d


def _num(x):
    return None if pd.isna(x) else (int(x) if float(x).is_integer() else round(float(x), 2))


def construir(r: dict, extras: dict, nm=lambda t: t) -> dict | None:
    """Datos embebidos para el explorador. Devuelve None si falta algo esencial."""
    pw, games, depth, P = extras.get("pw"), r.get("games"), extras.get("depth"), extras.get("P")
    if pw is None or len(pw) == 0 or games is None or len(games) == 0:
        return None
    cur = int(extras.get("cur") or r["cur"])
    vig = extras.get("vigente") or {}
    auto = extras.get("auto") or {}
    g = games[games.get("game_type", "REG") == "REG"] if "game_type" in games else games
    g = g[g.season.isin([cur - 1, cur])]
    pw = _valores(pw[pw.season.isin([cur - 1, cur]) & pw.position.isin(POS)])
    if "season_type" in pw:
        pw = pw[pw.season_type.fillna("REG") == "REG"]
    seasons = sorted(set(int(s) for s in pw.season.unique()) & {cur - 1, cur})
    if not seasons:
        return None

    # --- calendario: (temporada, equipo) -> semana: rival, sede, marcador, total y linea de total
    oponentes, juegos = {}, {}
    for x in g.itertuples():
        final = pd.notna(x.home_score) and pd.notna(x.away_score)
        tot = _num(x.home_score + x.away_score) if final else None
        lin = _num(x.total_line) if "total_line" in g and pd.notna(x.total_line) else None
        for team, opp, ha, ts, os_ in ((x.home_team, x.away_team, 1, x.home_score, x.away_score), (x.away_team, x.home_team, 0, x.away_score, x.home_score)):
            oponentes[(int(x.season), int(x.week), team)] = (opp, ha)
            juegos.setdefault(str(int(x.season)), {}).setdefault(team, []).append(
                [int(x.week), opp, ha, _num(ts) if final else None, _num(os_) if final else None, tot, lin])
    for s in juegos.values():
        for t in s:
            s[t].sort()

    # --- estadisticas por jugador y semana
    cols = [k for k, _, _ in MERCADOS]
    semanal, ult_team = {}, {}
    pw = pw.sort_values(["season", "week"])
    for x in pw.itertuples(index=False):
        opp, ha = oponentes.get((int(x.season), int(x.week), x.team), ("", -1))
        fila = [int(x.week), x.team, opp, ha] + [_num(getattr(x, c)) for c in cols]
        semanal.setdefault(x.player_id, {}).setdefault(str(int(x.season)), []).append(fila)
        ult_team[x.player_id] = x.team
    nombres = pw.drop_duplicates("player_id", keep="last").set_index("player_id")[["name", "position"]]

    # --- depth chart actual: equipo vigente, rol (titular / banca) y jugadores sin estadisticas
    dep = pd.DataFrame(columns=["team", "gsis_id", "player_name", "pos_abb", "pos_rank"])
    if depth is not None and len(depth):
        dep = depth[depth.dt == depth.dt.max()] if "dt" in depth else depth
        dep = dep[dep.pos_abb.isin(POS)].dropna(subset=["gsis_id"]).sort_values("pos_rank").drop_duplicates("gsis_id")
    dep_i = dep.set_index("gsis_id") if len(dep) else dep

    # --- lesiones / estado (proyecciones del modelo + lista de bajas)
    est = {}
    if P is not None and len(P):
        for x in P.drop_duplicates("player_id").itertuples():
            if getattr(x, "estado", ""):
                est[x.player_id] = (x.estado, str(getattr(x, "lesion", "") or ""))
    ex = extras.get("excl")
    por_nombre = {}
    if ex is not None and len(ex):
        try:
            from fuentes_web import nombre_norm
        except Exception:
            nombre_norm = lambda s: str(s).lower()
        por_nombre = {(e.team, nombre_norm(e.name)): (e.estado, str(e.lesion or "")) for e in ex.itertuples()}
        mapa = {(t, nombre_norm(n)): pid for pid, t, n in zip(pw.player_id, pw.team, pw.name)}
        for k, v in por_nombre.items():
            if k in mapa:
                est[mapa[k]] = v

    # --- lista de jugadores
    ids = set(semanal) | set(dep_i.index if len(dep_i) else [])
    jug = []
    for pid in ids:
        if pid in nombres.index:
            nombre, pos = nombres.at[pid, "name"], nombres.at[pid, "position"]
        else:
            nombre, pos = dep_i.at[pid, "player_name"], dep_i.at[pid, "pos_abb"]
        team = vig.get(pid) or (dep_i.at[pid, "team"] if pid in dep_i.index else ult_team.get(pid, ""))
        rol, tit = "", 0
        if pid in dep_i.index:
            rk = int(dep_i.at[pid, "pos_rank"])
            rol = f"{pos}{rk}"
            tit = int(rk <= TITULARES.get(pos, 0))
        e, les = est.get(pid, ("", ""))
        jug.append([pid, nombre, pos, team, rol, tit, ESTADO_ES.get(e, e), les, 1 if pid in semanal else 0])
    jug.sort(key=lambda j: (j[3], POS.index(j[2]) if j[2] in POS else 9, -j[5], j[4] or "zz", j[1]))

    # --- proyeccion del modelo para el proximo partido (y linea de Kalshi si existe)
    pr = {}
    if P is not None and len(P):
        for x in P.itertuples():
            k = auto.get((x.player_id, x.market))
            if x.market == "td":
                v = [None, None, None, None, int(x.week), x.opp, int(x.is_home), None, None, None, None, None, round(float(x.p_td), 4)]
            else:
                v = [round(float(x.mu), 3), round(float(x.phi), 4), round(float(x.s_cal), 3), _num(x.line_n), int(x.week), x.opp, int(x.is_home),
                     _num(x.p25), _num(x.p75), _num(k["linea"]) if k else None, int(k["over"]) if k else None, int(k["under"]) if k else None, None]
            pr.setdefault(x.player_id, {})[x.market] = v

    equipos = sorted({t for s in juegos.values() for t in s})
    ult = {s: int(pw[pw.season == s].week.max()) for s in seasons}
    return {"cur": cur, "seasons": seasons, "ult": ult, "mk": [list(m) for m in MERCADOS], "def": DEFECTO, "mp": MKPOS,
            "teams": {t: nm(t) for t in equipos}, "pl": jug, "w": semanal, "g": juegos, "pr": pr}


def _json(d) -> str:
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def html_jugadores(d: dict | None) -> str:
    if not d:
        return ""
    return f"""<h2 id="explorador">LINEA AC</h2>
<p class="explain"><b>LINEA AC</b> = ¿cubrió la línea? Elige en orden: <b>temporada → equipo → posición → jugador → estadística</b> (yardas de pase, intentos de pase,
pases completos, TDs, intercepciones, acarreos, yardas por tierra, recepciones, yardas por recepción, targets…; la lista cambia según la posición) y mira semana a semana si
<b>cubrió la línea</b>: Hit Rate, récord, gráfica con la línea encima y filtro de local o visitante. La línea parte de la «normal» del modelo (o del promedio de la temporada si
el jugador no tiene proyección); <b>escribe la tuya</b> y todo se recalcula. «Más de» cubre si el resultado real supera la línea; «Menos de», si queda por debajo; un empate (push) no cuenta.
Hit Rate = cubrió ÷ (cubrió + no cubrió).</p>
<div class="jx" id="jx">
<div class="jx-ctl">
<label>Temporada<select id="jx-sea"></select></label>
<label>Equipo<select id="jx-team"></select></label>
<label>Posición<select id="jx-pos"></select></label>
<label class="jx-w">Jugador <small id="jx-n"></small><select id="jx-pl"></select></label>
<label>Estadística<select id="jx-mk"></select></label>
</div>
<div class="jx-ctl">
<span class="jx-g">Apuesta <label><input type="radio" name="jx-lado" value="over" checked> Más de</label> <label><input type="radio" name="jx-lado" value="under"> Menos de</label></span>
<span class="jx-g">Sede <label><input type="radio" name="jx-sede" value="" checked> Ambos</label> <label><input type="radio" name="jx-sede" value="1"> Local</label> <label><input type="radio" name="jx-sede" value="0"> Visitante</label></span>
<label>Línea a evaluar <input id="jx-line" type="number" step="0.5" min="0" style="width:6em"></label>
<span class="jx-g" id="jx-src"></span>
</div>
<div id="jx-out"></div>
<script type="application/json" id="jx-data">{_json(d)}</script>
</div>"""


CSS = """
.jx{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:8px 0}
.jx-ctl{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;margin:0 0 10px}
.jx-ctl label,.jx-g{display:flex;flex-direction:column;font-size:.8rem;color:var(--ink2);gap:2px}
.jx-g{flex-direction:row;align-items:center;gap:8px;flex-wrap:wrap}.jx-g label{flex-direction:row;align-items:center;gap:3px}
.jx select,.jx input[type=number]{font:inherit;font-size:.95rem;padding:5px 6px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);max-width:100%}
.jx-w{flex:1 1 280px}.jx-w select{width:100%}
.jx-t{font-size:1.5rem;font-weight:700;margin:6px 0 0}.jx-s{color:var(--ink2);margin:0 0 8px}
.jx-warn{background:var(--aviso-bg);color:var(--aviso);border:1px solid var(--aviso);border-radius:8px;padding:8px 12px;margin:6px 0}
.jx-k{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:8px 0}
.jx-c{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.jx-c .l{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink2)}
.jx-c .v{font-size:2.3rem;font-weight:700;line-height:1.1;margin:2px 0}.jx-c .v small{font-size:1rem;font-weight:500;color:var(--ink2)}
.jx-c .s{font-size:.82rem;color:var(--ink2)}.jx-c.sm .v{font-size:1.5rem}
.jx-g3{color:var(--valor)}.jx-r3{color:var(--contra)}.jx-a3{color:var(--aviso)}.jx-m3{color:var(--ink2)}
.jx-chart{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--bg);margin:8px 0;padding:6px}
.jx-chart svg{display:block;min-width:100%}
.jx-chips{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px}
.jx-chip{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:6px 10px;min-width:92px}
.jx-chip .w{font-size:.7rem;color:var(--ink2)}.jx-chip .v{font-weight:600;white-space:nowrap}.jx-chip .v small{color:var(--ink2);font-weight:400}.jx-chip .o{font-size:.75rem;font-weight:700}
.jx h4{margin:14px 0 4px}.jx table{border-collapse:collapse;width:100%;font-size:.85rem}.jx th,.jx td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:center}
.jx-prox{background:var(--bg);border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:10px;padding:10px 14px;margin:8px 0}
"""

JS = r"""
<script>
(function(){
var el=document.getElementById('jx-data');if(!el)return;
var D=JSON.parse(el.textContent),MK={},MKL=D.mk.map(function(m){MK[m[0]]=m;return m[0];}),PL={};
D.pl.forEach(function(p){PL[p[0]]=p;});
var $=function(i){return document.getElementById(i);},H=function(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');};
var OUT=$('jx-out'),st={line:null,own:false};
function opt(v,t,sel){return '<option value="'+H(v)+'"'+(sel?' selected':'')+'>'+H(t)+'</option>';}
function nbCdf(k,mu,phi){if(k<0)return 0;var n=1/phi,p=n/(n+mu),pmf=Math.exp(n*Math.log(p)),c=pmf;for(var i=0;i<k;i++){pmf=pmf*(i+n)/(i+1)*(1-p);c+=pmf;}return Math.min(c,1);}
function fmt(v){return v==null||isNaN(v)?'—':(Math.abs(v-Math.round(v))<1e-9?String(Math.round(v)):v.toFixed(1));}
function tn(t){return D.teams[t]?t+' · '+D.teams[t]:t;}
// ---- cálculo (mismas reglas que metrics.py del dashboard)
function grade(rows,lado){var o=lado==='over'?'under':'over';rows.forEach(function(r){
 r.res=!r.played?'No jugó':(r.line==null?'Sin línea':(r.actual>r.line?'over':(r.actual<r.line?'under':'Push')));
 r.out=r.res==='No jugó'||r.res==='Sin línea'||r.res==='Push'?r.res:(r.res===lado?'Cubrió':'No cubrió');});return rows;}
function summ(rows){var h=0,m=0,p=0,pl=[],sc=[];rows.forEach(function(r){if(r.out==='Cubrió')h++;else if(r.out==='No cubrió')m++;else if(r.out==='Push')p++;if(r.played)pl.push(r);if(r.out==='Cubrió'||r.out==='No cubrió'||r.out==='Push')sc.push(r);});
 var av=function(a,f){return a.length?a.reduce(function(s,x){return s+f(x);},0)/a.length:null;};
 return {hits:h,misses:m,pushes:p,games:h+m+p,played:pl.length,hr:(h+m)?h/(h+m):null,avgA:av(pl,function(x){return x.actual;}),avgL:av(sc,function(x){return x.line;}),avgM:av(sc,function(x){return x.actual-x.line;})};}
function sede(rows,s){return s===''?rows:rows.filter(function(r){return String(r.ha)===s;});}
// ---- semanas del jugador: las que jugó + las de su equipo en que no jugó (sin descansos ni partidos futuros)
function frame(pid,sea,mk){
 var W=(D.w[pid]||{})[sea]||[],i=MKL.indexOf(mk),by={},G=(D.g[sea]||{});W.forEach(function(r){by[r[0]]=r;});
 var maxw=0;Object.keys(G).forEach(function(t){G[t].forEach(function(x){if(x[3]!=null&&x[0]>maxw)maxw=x[0];});});
 var played=W.map(function(r){return r[0];}),rows=[];
 played.forEach(function(x){if(x>maxw)maxw=x;});
 for(var w=1;w<=maxw;w++){
  if(by[w]){var r=by[w];rows.push({week:w,opp:r[2],ha:r[3],played:true,actual:r[4+i]});continue;}
  if(!played.length)continue;
  var near=played.filter(function(x){return x<w;}).pop();if(near==null)near=played.filter(function(x){return x>w;})[0];
  var team=by[near][1],gm=(G[team]||[]).filter(function(x){return x[0]===w&&x[3]!=null;})[0];
  if(gm)rows.push({week:w,opp:gm[1],ha:gm[2],played:false,actual:null});}
 return rows;}
function defLine(rows,mk,pid){var p=(D.pr[pid]||{})[mk];
 if(p){if(mk==='td')return {v:0.5,src:'modelo'};if(p[3]!=null)return {v:p[3],src:'modelo'};}
 var pl=rows.filter(function(r){return r.played;}),a=pl.length?pl.reduce(function(s,r){return s+r.actual;},0)/pl.length:null;
 return {v:a==null?0.5:Math.max(0.5,Math.round(a*2)/2),src:'promedio'};}
// ---- dibujo
function TC(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function chart(rows,unit,lname){
 if(!rows.length)return '';var n=rows.length,bw=44,W=Math.max(420,n*bw+60),Hh=260,top=24,bot=44,ph=Hh-top-bot;
 var mx=0;rows.forEach(function(r){if(r.played&&r.actual>mx)mx=r.actual;if(r.line!=null&&r.line>mx)mx=r.line;});mx=mx<=0?1:mx*1.15;
 var col={'Cubrió':TC('--valor'),'No cubrió':TC('--contra'),'Push':TC('--text-2'),'Sin línea':TC('--info'),'No jugó':TC('--text-2')},s='<svg viewBox="0 0 '+W+' '+Hh+'" width="'+W+'" height="'+Hh+'" role="img" aria-label="Estadística por semana">';
 for(var g=0;g<=4;g++){var y=top+ph-ph*g/4;s+='<line x1="40" x2="'+(W-6)+'" y1="'+y+'" y2="'+y+'" stroke="currentColor" opacity=".12"/><text x="36" y="'+(y+4)+'" text-anchor="end" font-size="12" fill="currentColor" opacity=".6">'+fmt(mx*g/4)+'</text>';}
 var pts=[];rows.forEach(function(r,k){var x=48+k*bw,cx=x+bw*0.325;
  if(r.played){var h=ph*r.actual/mx;s+='<rect x="'+x+'" y="'+(top+ph-h)+'" width="'+bw*0.65+'" height="'+Math.max(h,1)+'" rx="3" fill="'+col[r.out]+'"/><text x="'+cx+'" y="'+(top+ph-h-4)+'" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">'+fmt(r.actual)+'</text>';}
  else s+='<text x="'+cx+'" y="'+(top+ph-6)+'" text-anchor="middle" font-size="12" fill="currentColor" opacity=".55">no jugó</text>';
  if(r.line!=null)pts.push([cx,top+ph-ph*r.line/mx]);
  s+='<text x="'+cx+'" y="'+(Hh-26)+'" text-anchor="middle" font-size="12" fill="currentColor">S'+r.week+'</text><text x="'+cx+'" y="'+(Hh-13)+'" text-anchor="middle" font-size="12" fill="currentColor" opacity=".7">'+(r.ha===0?'@':'vs')+' '+H(r.opp||'—')+'</text>';});
 if(pts.length){s+='<polyline fill="none" stroke="'+TC('--aviso')+'" stroke-width="2" stroke-dasharray="4 3" points="'+pts.map(function(p){return p[0]+','+p[1];}).join(' ')+'"/>';pts.forEach(function(p){s+='<path d="M'+p[0]+' '+(p[1]-6)+' l6 6 l-6 6 l-6 -6z" fill="'+TC('--aviso')+'"/>';});}
 return '<div class="jx-chart">'+s+'</svg></div><div class="jx-s">Barras: '+H(unit)+' reales de cada semana (verde = cubrió, rojo = no cubrió, gris = push). Línea punteada: '+H(lname)+'.</div>';}
function chips(rows,extra){var cl={'Cubrió':[TC('--valor'),'✓ Cubrió'],'No cubrió':[TC('--contra'),'✗ No cubrió'],'Push':[TC('--text-2'),'= Push'],'Sin línea':[TC('--info'),'sin línea'],'No jugó':[TC('--text-2'),'no jugó']};
 return '<div class="jx-chips">'+rows.map(function(r){var c=cl[r.out]||[TC('--text-2'),r.out],t=c[1];if(extra&&(r.res==='over'||r.res==='under'))t+=' · '+(r.res==='over'?'Más de':'Menos de');
  return '<div class="jx-chip" style="border-color:'+c[0]+'"><div class="w">S'+r.week+' · '+(r.ha===0?'@':'vs')+' '+H(r.opp||'')+'</div><div class="v">'+(r.played?fmt(r.actual):'—')+(r.line!=null?' <small>/ '+fmt(r.line)+'</small>':'')+'</div><div class="o" style="color:'+c[0]+'">'+t+'</div></div>';}).join('')+'</div>';}
function hrc(h){return h==null?'jx-m3':(h>=0.6?'jx-g3':(h<=0.4?'jx-r3':'jx-a3'));}
function hrt(h){return h==null?'—':Math.round(h*100)+'%';}
function card(l,v,s,sm){return '<div class="jx-c'+(sm?' sm':'')+'"><div class="l">'+l+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>';}
// ---- selectores
function fillSeasons(){$('jx-sea').innerHTML=D.seasons.slice().reverse().map(function(s,i){return opt(s,s,i===0);}).join('');}
function fillTeams(){var t=Object.keys(D.teams).sort();$('jx-team').innerHTML=opt('','Todos los equipos ('+t.length+')',true)+t.map(function(x){return opt(x,tn(x));}).join('');}
function fillPos(){$('jx-pos').innerHTML=opt('','Todas',true)+['QB','RB','WR','TE'].map(function(p){return opt(p,p);}).join('');}
function plLabel(p,showTeam){var a=[p[1],p[2]];if(showTeam)a.push(p[3]||'—');a.push(p[5]?'Titular '+p[4]:(p[4]?'Banca ('+p[4]+')':'sin depth chart'));if(p[6])a.push('🩹 '+p[6]);return a.join(' · ');}
function fillPlayers(keep){var t=$('jx-team').value,ps=$('jx-pos').value,L=D.pl.filter(function(p){return (!t||p[3]===t)&&(!ps||p[2]===ps);});
 if(!t)L=L.slice().sort(function(a,b){return a[1]<b[1]?-1:1;});
 $('jx-n').textContent='('+L.length+' disponible'+(L.length===1?'':'s')+')';
 $('jx-pl').innerHTML=L.length?L.map(function(p){return opt(p[0],plLabel(p,!t),p[0]===keep);}).join(''):opt('','Sin jugadores con esos filtros');}
function fillMk(){var p=PL[$('jx-pl').value],cur=$('jx-mk').value,ok=p&&D.mp[p[2]]?D.mp[p[2]]:MKL;$('jx-mk').innerHTML=ok.map(function(k){return opt(k,MK[k][1],false);}).join('');
 $('jx-mk').value=(cur&&p&&$('jx-mk').dataset.pid===p[0])?cur:((p&&D.def[p[2]])||'pass_yds');$('jx-mk').dataset.pid=p?p[0]:'';}
function sedeV(){var r=document.querySelector('input[name=jx-sede]:checked');return r?r.value:'';}
function ladoV(){var r=document.querySelector('input[name=jx-lado]:checked');return r?r.value:'over';}
// ---- render
function render(resetLine){
 var pid=$('jx-pl').value,p=PL[pid];if(!p){OUT.innerHTML='<div class="jx-s">No hay jugadores con esos filtros.</div>';return;}
 var sea=$('jx-sea').value,mk=$('jx-mk').value,m=MK[mk],lado=ladoV(),sd=sedeV();
 var rows=frame(pid,sea,mk),pr=(D.pr[pid]||{})[mk];
 var head='<div class="jx-t">'+H(p[1])+'</div><div class="jx-s">'+[p[2],tn(p[3]||'—'),p[5]?'Titular '+p[4]:(p[4]?'Banca ('+p[4]+')':'sin depth chart'),m[1],'Temporada '+sea].join(' · ')+'</div>';
 if(p[6])head+='<div class="jx-warn">🩹 '+H(p[6])+(p[7]?' ('+H(p[7])+')':'')+(pr?'':' · el modelo no lo proyecta para el próximo partido')+'</div>';
 if(!rows.some(function(r){return r.played;})){OUT.innerHTML=head+'<div class="jx-s">Este jugador todavía no tiene estadísticas en esta temporada (reserva, equipo de práctica o aún no ha jugado).</div>'+tot(p,sea,lado,sd);return;}
 var dl=defLine(rows,mk,pid);if(resetLine||st.line==null){st.line=dl.v;st.src=dl.src;$('jx-line').value=dl.v;}
 var L=parseFloat($('jx-line').value);if(isNaN(L))L=null;
 rows.forEach(function(r){r.line=L;});var all=grade(rows,lado),vis=sede(all,sd),S=summ(vis);
 var srcs='<button class="pbtn" data-jx="prom">usar promedio</button>';if(pr&&mk!=='td'&&pr[3]!=null)srcs='<button class="pbtn" data-jx="modelo">usar línea del modelo ('+fmt(pr[3])+')</button> '+srcs;if(pr&&pr[9]!=null)srcs+=' <button class="pbtn" data-jx="kalshi">usar línea de Kalshi ('+fmt(pr[9])+')</button>';
 $('jx-src').innerHTML=srcs;
 var sTxt=sd===''?'':' · como '+(sd==='1'?'local':'visitante');
 var h=head;
 if(p[2]==='RB'){var cf=frame(pid,sea,'rush_att').filter(function(r){return r.played;}),cs=sede(cf,sd),av=function(a){return a.length?fmt(a.reduce(function(s,r){return s+r.actual;},0)/a.length):'—';},l3=cs.slice(-3);
  h+='<h4>🏃 Acarreos por partido</h4><div class="jx-k">'+card('Acarreos por partido',av(cs),cs.length+' partidos'+sTxt,1)+card('Últimos 3 partidos',av(l3),'acarreos por partido',1)+card('Como local',av(cf.filter(function(r){return r.ha===1;})),'acarreos por partido',1)+card('Como visitante',av(cf.filter(function(r){return r.ha===0;})),'acarreos por partido',1)+'</div>';}
 h+='<div class="jx-k">'+card('Hit Rate','<span class="'+hrc(S.hr)+'">'+hrt(S.hr)+'</span>',(lado==='over'?'Más de':'Menos de')+sTxt+' · '+S.games+' partidos con línea ('+(st.src==='propia'?'línea propia':'línea del '+st.src)+')')
  +card('Récord','<span class="jx-g3">'+S.hits+'</span> – <span class="jx-r3">'+S.misses+'</span>',S.hits+(S.hits===1?' vez cubrió':' veces cubrió')+' · '+S.misses+' no cubrió'+(S.pushes?' · '+S.pushes+' push':''))
  +(S.avgL!=null?card('Promedio real vs línea',fmt(S.avgA)+' <small>vs '+fmt(S.avgL)+'</small>','Margen medio '+(S.avgM>=0?'+':'')+S.avgM.toFixed(1)):card('Promedio real',fmt(S.avgA),S.played+' partidos jugados'))+'</div>';
 var kk='';[['Como local','1'],['Como visitante','0']].forEach(function(x){var s=summ(sede(all,x[1]));kk+=card(x[0]+' · Hit Rate','<span class="'+hrc(s.hr)+'">'+hrt(s.hr)+'</span>',s.hits+'–'+s.misses+' · '+s.games+' con línea'+(s.avgL!=null?' · prom. real '+fmt(s.avgA)+' vs línea '+fmt(s.avgL):''),1);});
 h+='<div class="jx-k">'+kk+'</div>';
 if(!vis.some(function(r){return r.played;}))h+='<div class="jx-s">Este jugador no tiene partidos jugados como '+(sd==='1'?'local':'visitante')+' en esta temporada. Prueba con otra sede.</div>';
 else h+=chart(vis,m[2],st.src==='propia'?'línea propia':'línea a cubrir')+'<h4>¿Cubrió la línea?</h4>'+chips(vis,false);
 h+=prox(p,pid,mk,pr,L,lado);
 var miss=vis.filter(function(r){return r.out==='No jugó';}).map(function(r){return 'S'+r.week;});if(miss.length)h+='<div class="jx-s">No jugó o sin estadísticas (no cuenta para el Hit Rate): '+miss.join(', ')+'</div>';
 h+='<details class="sec"><summary>Detalle semana a semana</summary><div class="scroll"><table><tr><th>Semana</th><th>Rival</th><th>Sede</th><th>Línea</th><th>Real</th><th>Real − línea</th><th>Resultado</th></tr>'+vis.map(function(r){return '<tr><td>'+r.week+'</td><td>'+H(r.opp||'')+'</td><td>'+(r.ha===1?'Local':(r.ha===0?'Visitante':''))+'</td><td>'+fmt(r.line)+'</td><td>'+(r.played?fmt(r.actual):'—')+'</td><td>'+(r.played&&r.line!=null?((r.actual-r.line>=0?'+':'')+(r.actual-r.line).toFixed(1)):'')+'</td><td>'+r.out+'</td></tr>';}).join('')+'</table></div></details>';
 h+=tot(p,sea,lado,sd);
 OUT.innerHTML=h;}
function prox(p,pid,mk,pr,L,lado){
 if(!pr)return '';var wk=pr[4],opp=pr[5],ha=pr[6],po=null,txt;
 if(mk==='td'){po=pr[12];txt='el modelo da <b>'+Math.round(po*100)+'%</b> de que anote al menos un TD (por tierra o recepción).';}
 else{var mu=pr[0],phi=pr[1],s=pr[2];txt='el modelo espera <b>'+fmt(mu)+'</b> (rango típico '+fmt(pr[7])+'–'+fmt(pr[8])+')';
  if(L!=null){var pu=nbCdf(Math.ceil(L)-1,mu,phi),pv=1-nbCdf(Math.floor(L),mu,phi);po=pv/(pv+pu);po=0.5+s*(po-0.5);
   txt+='; con tu línea de <b>'+fmt(L)+'</b>: Más de <b>'+Math.round(po*100)+'%</b> · Menos de <b>'+Math.round((1-po)*100)+'%</b>.';}}
 if(pr[9]!=null)txt+=' Kalshi: línea '+fmt(pr[9])+(pr[10]!=null?' (Más de '+(pr[10]>0?'+':'')+pr[10]+' · Menos de '+(pr[11]>0?'+':'')+pr[11]+')':'')+'.';
 return '<div class="jx-prox"><b>Próximo partido (semana '+wk+', '+(ha===1?'vs':'@')+' '+H(opp)+'):</b> '+txt+'</div>';}
// ---- puntos totales del partido (equipo del jugador)
function tot(p,sea,lado,sd){var t=p[3],G=((D.g[sea]||{})[t]||[]);if(!t||!G.length)return '';
 var fin=G.filter(function(x){return x[3]!=null;}).map(function(x){return {week:x[0],opp:x[1],ha:x[2],played:true,actual:x[5],line:x[6],ts:x[3],os:x[4]};});
 var all=grade(fin,lado),vis=sede(all,sd),S=summ(vis),sTxt=sd===''?'':' · como '+(sd==='1'?'local':'visitante');
 var h='<h4>🎯 Puntos totales del partido · '+(lado==='over'?'Más de':'Menos de')+' · '+H(tn(t))+'</h4><div class="jx-s">En cada juego del equipo: ¿el marcador combinado de los dos equipos se fue '+(lado==='over'?'por encima (Más de)':'por debajo (Menos de)')+' de la línea de puntos totales? Usa el mismo filtro de apuesta y de sede.</div>';
 h+='<div class="jx-k">'+card('Hit Rate · totales','<span class="'+hrc(S.hr)+'">'+hrt(S.hr)+'</span>',(lado==='over'?'Más de':'Menos de')+sTxt+' · '+S.games+' juegos con línea',1)
  +card('Récord','<span class="jx-g3">'+S.hits+'</span> – <span class="jx-r3">'+S.misses+'</span>',(S.avgL!=null?'prom. '+fmt(S.avgA)+' pts vs línea '+fmt(S.avgL):'sin partidos con línea')+(S.pushes?' · '+S.pushes+' push':''),1);
 [['Como local','1'],['Como visitante','0']].forEach(function(x){var s=summ(sede(all,x[1]));h+=card(x[0]+' · Hit Rate','<span class="'+hrc(s.hr)+'">'+hrt(s.hr)+'</span>',s.hits+'–'+s.misses+' · '+s.games+' con línea',1);});
 h+='</div>';
 if(!vis.length)h+='<div class="jx-s">'+H(tn(t))+' no tiene partidos terminados'+(sd===''?'':' como '+(sd==='1'?'local':'visitante'))+' en esta temporada.</div>';
 else h+=chart(vis,'Puntos totales','línea de totales')+'<h4>¿Cubrió el total?</h4>'+chips(vis,true);
 var nx=G.filter(function(x){return x[3]==null&&x[6]!=null;})[0];if(nx)h+='<div class="jx-prox"><b>Próximo partido (semana '+nx[0]+', '+(nx[2]===1?'vs':'@')+' '+H(nx[1])+'):</b> línea de puntos totales <b>'+fmt(nx[6])+'</b></div>';
 return h;}
// ---- eventos (delegados: no estorban a los demás cálculos de la página)
function onSel(ev){var t=ev.target;if(!t.closest||!t.closest('#jx'))return;
 var id=t.id,nm=t.name;
 if(id==='jx-team'||id==='jx-pos'){fillPlayers();fillMk();st.line=null;render(true);}
 else if(id==='jx-pl'||id==='jx-mk'||id==='jx-sea'){if(id==='jx-pl')fillMk();st.line=null;render(true);}
 else if(nm==='jx-lado'||nm==='jx-sede'){render(false);}
 else if(id==='jx-line'){st.src='propia';st.line=parseFloat(t.value);render(false);}}
document.addEventListener('change',onSel);
document.addEventListener('input',function(ev){if(ev.target&&ev.target.id==='jx-line'){onSel(ev);}});
document.addEventListener('click',function(ev){var b=ev.target.closest&&ev.target.closest('button[data-jx]');if(!b||!b.closest('#jx'))return;
 var pid=$('jx-pl').value,mk=$('jx-mk').value,pr=(D.pr[pid]||{})[mk],k=b.dataset.jx,v=null;
 if(k==='modelo'&&pr&&pr[3]!=null){v=pr[3];st.src='modelo';}
 else if(k==='kalshi'&&pr&&pr[9]!=null){v=pr[9];st.src='propia';}
 else if(k==='prom'){var rr=frame(pid,$('jx-sea').value,mk).filter(function(r){return r.played;});var a=rr.length?rr.reduce(function(s,r){return s+r.actual;},0)/rr.length:0.5;v=Math.max(0.5,Math.round(a*2)/2);st.src='promedio';}
 if(v!=null){$('jx-line').value=v;st.line=v;render(false);}});
fillSeasons();fillTeams();fillPos();fillPlayers();fillMk();st.line=null;render(true);
window.JX={render:render,frame:frame,grade:grade,summ:summ,D:D};
})();
</script>
"""
