"""Mejoras de la pagina (solo presentacion; ningun calculo del modelo cambia):

  1. «Qué apostar hoy»: las elecciones con ventaja real de hoy, con cuota decimal y tamano sugerido (Kelly 1/4, tope 1 unidad).
  2. Aviso de «hay una version nueva» (compara la hora de generacion de esta pagina con la publicada).
  3. «Mis apuestas»: registro de tus apuestas reales (se guardan SOLO en tu navegador), ROI, unidades y curva de banca,
     comparado con lo que dice el modelo. Califica solo cuando ya hay marcador final.
  4. (las alertas al celular viven en avisos.py y en el workflow)
  5. Tarjeta compartible (PNG) con las elecciones de la semana para TikTok / YouTube.

Todo se arma aqui y web.py lo engancha. Los numeros (probabilidad, cuota, ventaja) vienen de predict/reporte tal cual.
"""
from __future__ import annotations
from barras import barra

import html
import json

import numpy as np
import pandas as pd

from odds_fmt import a_dec, fd

TOPE_U = 1.0        # tamano maximo sugerido (1 unidad = 1 % de la banca)
FRAC_KELLY = 0.25   # se apuesta solo un cuarto de lo que sugiere Kelly (las probabilidades del modelo tienen error)


def _esc(x) -> str:
    return html.escape(str(x), quote=True)


def tamano_u(p: float, cuota_dec: float) -> float:
    """Tamano sugerido en unidades: 1/4 de Kelly, redondeado a 0.25 u, minimo 0.25 y tope 1 unidad (1 u = 1 % de la banca)."""
    if not (np.isfinite(p) and np.isfinite(cuota_dec)) or cuota_dec <= 1 or not 0 < p < 1:
        return 0.0
    f = (p * cuota_dec - 1) / (cuota_dec - 1)
    if f <= 0:
        return 0.0
    u = min(f * FRAC_KELLY * 100, TOPE_U)
    return max(round(u / 0.25) * 0.25, 0.25)


def _u_txt(u: float) -> str:
    return f"{u:g} u" if u else "—"


# ------------------------------------------------------------------------------------------ 1. Qué apostar hoy
def _valores(js_, c, mercados):
    """[(partido, mercado)] con ventaja >= umbral, ordenado por hora de inicio y luego por ventaja."""
    me = c["me"]
    L = []
    for d in js_:
        for m in mercados(d["x"]):
            if m["edge"] >= me:
                L.append((d, m))
    L.sort(key=lambda t: ((t[0]["ko"] is None), t[0]["ko"] if t[0]["ko"] is not None else 0, -t[1]["edge"]))
    return L


def _datos_apuesta(d: dict, m: dict) -> dict:
    """Datos estructurados de una elección (para registrarla en «Mis apuestas» y calificarla sola)."""
    x = d["x"]
    k = m["k"]
    if k == "sp":
        side, line = ("home" if bool(x.sp_es_a) else "away"), float(x.spread_line)
    elif k == "to":
        side, line = ("over" if bool(x.to_es_a) else "under"), float(x.total_line)
    else:
        side, line = ("home" if bool(x.ml_es_a) else "away"), None
    cd = float(a_dec(m["cuota"]))
    return {"gid": d["id"], "mk": k, "side": side, "line": line, "lab": m["lab"], "part": f'{d["away"]} @ {d["home"]}',
            "t": m["t"], "odds": round(cd, 2) if np.isfinite(cd) else None, "p": round(float(m["p"]), 4),
            "u": tamano_u(float(m["p"]), cd)}


def boton_registrar(d: dict, m: dict) -> str:
    a = _datos_apuesta(d, m)
    attrs = " ".join(f'data-{k}="{_esc("" if v is None else v)}"' for k, v in a.items())
    return f'<button type="button" class="chip ma-reg" {attrs}>Registrar en Mis apuestas</button>'


def _ct(m) -> str:
    return "La cuota (" + fd(m["cuota"]) + ") exige"


def hoy_html(js_, c, mercados, cuando, veredicto_chip, vchip, tip) -> str:
    L = _valores(js_, c, mercados)
    pie = ('<p class="leyenda">«Tamaño sugerido»: un cuarto de lo que sugiere el criterio de Kelly, con tope de 1 unidad; '
           '1 unidad = 1 % de tu banca.' + tip("tamano") + ' Es una guía para no apostar de más, no una garantía. '
           'Lo que no aparece aquí (sin ventaja) está en «Los partidos de la semana».</p>')
    if not L:
        return ('<section class="hoy" id="hoy" aria-labelledby="hoy-t"><h2 id="hoy-t" class="tabsec">Qué apostar hoy</h2>'
                '<div class="vacio"><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Hoy no hay elecciones con ventaja real.</b> '
                'Es lo más habitual: el mercado de la NFL es muy eficiente, y no apostar también es una decisión.</div></div></section>')
    filas = []
    for d, m in L:
        cl, tx, _ = veredicto_chip(m["k"], c.get("hv"))
        a = _datos_apuesta(d, m)
        ko = d["ko"].isoformat() if d["ko"] is not None else ""
        filas.append(
            f'<article class="hoy-row box" data-ko="{ko}" data-gid="{_esc(d["id"])}" data-mk="{m["k"]}">'
            f'<div class="gc-top"><span class="hr-when when">{_esc(cuando(d["ko"]))}</span>{vchip("valor" if cl == "valor" else "aviso", tx)}</div>'
            f'<div class="gc-mid"><div class="hr-mk pk-m">{_esc(m["t"])} · {_esc(d["away"])} @ {_esc(d["home"])}</div>'
            f'<div class="hr-lado">{_esc(m["rot"])}</div></div>'
            f'<div class="hr-nums"><div><small>Cuota</small><b>{_esc(fd(m["cuota"]))}</b></div>'
            f'<div><small>Ventaja{tip("ventaja")}</small><b>{m["edge"] * 100:+.1f} pts</b></div>'
            f'<div><small>Tamaño sugerido{tip("tamano")}</small><b>{_esc(_u_txt(a["u"]))}</b></div></div>'
            f'{barra(m["p"] * 100, m["imp"] * 100, m["pos"], m["neg"], _ct(m), diff=m["edge"] * 100)}'
            f'<div class="gc-foot"><div class="hr-btns"><button type="button" class="chip" data-go="{_esc(d["id"])}" data-tab="apuestas">Ver partido</button>{boton_registrar(d, m)}</div></div></article>')
    return ('<section class="hoy" id="hoy" aria-labelledby="hoy-t"><h2 id="hoy-t" class="tabsec">Qué apostar hoy</h2>'
            '<p class="hoy-sub" id="hoy-sub" aria-live="polite"></p>'
            f'<div id="hoy-lista">{"".join(filas)}</div>'
            '<div class="vacio" id="hoy-vacio" hidden><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Ya no quedan elecciones con ventaja por jugar.</b> '
            'Vuelve cuando se actualice la página (en días de partido, cada pocas horas).</div></div>' + pie + '</section>')


# ------------------------------------------------------------------------------------------ 3. Mis apuestas
def resultados_json(games: pd.DataFrame, cur: int) -> str:
    """{id_partido: [puntos_local, puntos_visita]} de los partidos ya jugados de esta temporada (para calificar tus apuestas solas)."""
    g = games[(games.season == cur) & games.home_score.notna() & games.away_score.notna()]
    out = {r.game_id: [int(r.home_score), int(r.away_score)] for r in g.itertuples(index=False)}
    return json.dumps(out, separators=(",", ":")).replace("</", "<\\/")


def modelo_historial(c: dict) -> dict:
    """ROI y acierto del modelo en sus «posibles valores» (pruebas fuera de muestra), sumando spread, total y ganador."""
    ev = c.get("ev_all") or {}
    n = acu = roi = 0.0
    for mk in ("spread", "total", "ganador"):
        v = (ev.get(mk) or {}).get("valor") or {}
        k = v.get("n", 0) or 0
        if k:
            n += k
            acu += k * v["acierto"]
            roi += k * v["roi"]
    return {"n": int(n), "acierto": (acu / n if n else None), "roi": (roi / n if n else None)}


def mis_apuestas_html(c: dict) -> str:
    mh = modelo_historial(c)
    at = f'data-mod-n="{mh["n"]}" data-mod-roi="{"" if mh["roi"] is None else round(mh["roi"], 4)}" data-mod-ac="{"" if mh["acierto"] is None else round(mh["acierto"], 4)}"'
    return ('<h2 id="mis-apuestas" class="tabsec">Mis apuestas</h2>'
            '<p class="explain keep">Registra aquí tus apuestas reales y mira tu ROI, tus unidades y tu curva de banca frente a lo que dice el modelo. '
            '<b>Se guardan solo en este navegador</b> (no se envían a ningún servidor); para pasarlas de tu celular a tu laptop usa Exportar e Importar.</p>'
            f'<div id="ma-host" {at}><div class="cargando" role="status">Cargando tus apuestas…</div></div>')


# ------------------------------------------------------------------------------------------ 5. Tarjeta compartible
def tarjeta_html(js_, c, mercados, nm) -> str:
    me = c["me"]
    games = []
    for d in js_:
        x = d["x"]
        if x is None:
            continue
        pl = float(x.p_gana_local)
        if pl != pl:
            continue
        home = pl >= 0.5
        vals = [{"t": m["t"], "lab": m["rot_c"], "cuota": fd(m["cuota"]), "edge": round(m["edge"] * 100, 1),
                 "u": tamano_u(float(m["p"]), float(a_dec(m["cuota"])))} for m in mercados(x) if m["edge"] >= me]
        games.append({"a": d["away"], "h": d["home"], "eq": d["home"] if home else d["away"], "p": round((pl if home else 1 - pl) * 100),
                      "vals": vals})
    data = {"semana": int(c["wk"]), "temp": int(c["cur"]), "juegos": games}
    dj = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if not games:
        return ""
    return ('<details class="exp" id="tarjeta"><summary>Crear una tarjeta para compartir (TikTok, YouTube, Instagram)</summary>'
            '<p class="leyenda">Genera una imagen con las elecciones del modelo de esta semana. Se dibuja en tu dispositivo; no se sube a ningún lado.</p>'
            '<div class="tj-ctl"><label>Formato<select id="tj-fmt"><option value="v">Vertical 9:16 (TikTok, Reels, Shorts)</option>'
            '<option value="c">Cuadrada 1:1 (Instagram, publicación)</option><option value="h">Horizontal 16:9 (YouTube, miniatura)</option></select></label>'
            '<label>Contenido<select id="tj-mod"><option value="todas">Elección del ganador de cada partido + posibles valores</option>'
            '<option value="valor">Solo los posibles valores</option></select></label></div>'
            '<canvas id="tj-cv" width="1080" height="1920" role="img" aria-label="Vista previa de la tarjeta para compartir"></canvas>'
            '<div class="tj-btns"><button type="button" class="chip" id="tj-dl">Descargar imagen (PNG)</button>'
            '<button type="button" class="chip" id="tj-sh" hidden>Compartir…</button></div>'
            f'<script type="application/json" id="tj-data">{dj}</script></details>')


# ------------------------------------------------------------------------------------------ elementos fijos de la pagina
def banner_nueva() -> str:
    return ('<div class="stale nueva" id="nueva" hidden role="status">Hay una versión nueva de esta página. '
            '<button type="button" class="chip" id="nueva-btn">Actualizar</button></div>')


FORM_HTML = """<div id="ma-form" class="box" role="dialog" aria-modal="true" aria-labelledby="ma-ft" hidden>
<form id="ma-f" novalidate><b id="ma-ft">Registrar apuesta</b>
<label>Apuesta<input id="maf-lab" type="text" maxlength="80" autocomplete="off" placeholder="Ej.: KC -15.5, Más de 46.5, DET gana"></label>
<label>Partido (opcional)<input id="maf-part" type="text" maxlength="60" autocomplete="off" placeholder="Ej.: TB @ DET"></label>
<label>Mercado<select id="maf-mk"><option value="sp">Spread</option><option value="to">Total (Más de / Menos de)</option><option value="ml">Ganador</option><option value="otro">Otro (prop, combinada…)</option></select></label>
<label>Cuota decimal<input id="maf-odds" type="text" inputmode="decimal" autocomplete="off" placeholder="1.91"></label>
<label>Unidades apostadas (1 u = 1 % de tu banca)<input id="maf-u" type="text" inputmode="decimal" autocomplete="off" placeholder="0.5"></label>
<label>Resultado<select id="maf-r"><option value="auto">Automático (cuando haya marcador final)</option><option value="gana">Ganada</option><option value="pierde">Perdida</option><option value="push">Push (se devuelve)</option></select></label>
<p class="ma-err" id="maf-err" role="alert" hidden></p>
<div class="ma-fb"><button type="submit" class="ma-ok">Guardar</button><button type="button" id="maf-x" class="ma-no">Cancelar</button></div></form></div>
<div id="ma-toast" class="box" role="status" aria-live="polite" hidden></div>"""


CSS_EXTRA = """
.hoy{margin:var(--s3) 0}
.hoy-sub{color:var(--text-2);font-size:var(--fs-14);margin:0 0 var(--s3)}
.hoy-row{padding:var(--s4);margin:var(--s3) 0;box-shadow:var(--shadow)}
.hoy-row[hidden]{display:none}
.hr-top{display:flex;justify-content:space-between;gap:var(--s3);flex-wrap:wrap;font-size:var(--fs-12);color:var(--text-2)}
.hr-lado{font-size:var(--fs-24);font-weight:800;margin:var(--s2) 0}
.hr-nums{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s2);margin:var(--s2) 0}
.hr-nums div{background:var(--surface-3);border:1px solid var(--border-subtle);border-radius:var(--r-sm);padding:var(--s2) var(--s3)}
.hr-nums small{display:flex;flex-wrap:wrap;align-items:center;gap:4px;color:var(--text-2);font-size:var(--fs-12)}
.hr-nums b{font-size:var(--fs-20)}
.hr-det{font-size:var(--fs-14);margin:var(--s2) 0}
.hr-btns{display:flex;gap:var(--s2);flex-wrap:wrap;margin-top:var(--s3)}
button.chip{min-height:var(--touch);padding:0 var(--s4);border-radius:var(--r-pill);background:var(--surface-3);border:1px solid var(--border-strong);color:var(--text);font-weight:600;font-size:var(--fs-14);font-family:inherit;cursor:pointer}
button.chip:hover{border-color:var(--border-strong)}
.nueva button.chip{margin-left:var(--s2)}
@media(max-width:420px){.hr-nums{grid-template-columns:1fr 1fr 1fr}.hr-nums b{font-size:var(--fs-17)}}
.tj-ctl{display:grid;gap:var(--s3);grid-template-columns:minmax(0,1fr);margin:var(--s3) 0}
@media(min-width:760px){.tj-ctl{grid-template-columns:1fr 1fr}}
.tj-ctl label,#ma-f label{display:grid;gap:var(--s1);font-size:var(--fs-14);color:var(--text-2);min-width:0}
.tj-ctl select,#ma-f select,#ma-f input[type=text]{width:100%;max-width:100%;min-width:0;text-overflow:ellipsis}
.tj-ctl select,#ma-f select,#ma-f input[type=text],.ma-b0 input{min-height:var(--touch);font-size:16px;background:var(--surface-3);color:var(--text);border:1px solid var(--border-strong);border-radius:var(--r-sm);padding:0 var(--s3);font-family:inherit}
#tj-cv{width:100%;max-width:420px;height:auto;display:block;margin:var(--s3) auto;border:1px solid var(--border);border-radius:var(--r-sm);background:#000}
.tj-btns{display:flex;gap:var(--s2);flex-wrap:wrap;justify-content:center}
.ma-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:var(--s2);margin:var(--s3) 0}
.ma-kpis div{background:var(--surface-3);border:1px solid var(--border-subtle);border-radius:var(--r-sm);padding:var(--s2) var(--s3)}
.ma-kpis small{display:block;color:var(--text-2);font-size:var(--fs-12)}.ma-kpis b{font-size:var(--fs-20)}
.ma-kpis .neg b{color:var(--contra)}.ma-kpis .pos b{color:var(--valor)}
.ma-cmp{font-size:var(--fs-14);margin:var(--s2) 0}
.ma-cmp td,.ma-cmp th{padding:var(--s2) var(--s3);text-align:left;border-bottom:1px solid var(--border-subtle)}
.ma-acts{display:flex;gap:var(--s2);flex-wrap:wrap;margin:var(--s3) 0}
.ma-b0{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;font-size:var(--fs-14);color:var(--text-2)}
.ma-b0 input{width:90px}
ul.ma-list{list-style:none;padding:0;margin:var(--s3) 0;display:grid;gap:var(--s3)}
li.ma-bet{padding:var(--s3) var(--s4)}
.ma-bet .ma-l{font-weight:700;font-size:var(--fs-17)}.ma-bet small{color:var(--text-2);display:block}
.ma-bet .ma-row{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center;margin-top:var(--s2);font-size:var(--fs-14)}
.ma-bet select{min-height:var(--touch);font-size:16px;background:var(--surface-3);color:var(--text);border:1px solid var(--border-strong);border-radius:var(--r-sm);padding:0 var(--s2);font-family:inherit}
.ma-chart{margin:var(--s3) 0}
#ma-form{position:fixed;left:var(--s3);right:var(--s3);bottom:var(--s3);top:auto;z-index:90;max-width:520px;margin:0 auto;padding:var(--s4);box-shadow:var(--shadow-pop);max-height:92vh;overflow:auto}
#ma-form form{display:grid;gap:var(--s3)}
#ma-form[hidden],#ma-toast[hidden]{display:none}
.ma-fb{display:flex;gap:var(--s2)}
.ma-ok,.ma-no{min-height:var(--touch);padding:0 var(--s5);border-radius:var(--r-pill);font-weight:700;font-family:inherit;cursor:pointer;border:1px solid var(--border-strong)}
.ma-ok{background:var(--accent);color:var(--on-accent);border:0}.ma-no{background:var(--surface-3);color:var(--text)}
.ma-err{color:var(--contra);font-size:var(--fs-14);margin:0}
#ma-toast{position:fixed;left:var(--s3);right:var(--s3);bottom:calc(16px + env(safe-area-inset-bottom));z-index:95;max-width:520px;margin:0 auto;padding:var(--s3) var(--s4);box-shadow:var(--shadow-pop);font-size:var(--fs-14)}
@media(min-width:900px){#ma-toast{bottom:24px}}
"""

JS_EXTRA = r"""
<script>
(function(){
var $=function(s,r){return (r||document).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};
var TZ='America/Mexico_City';
function ymd(ts){return new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(ts));}
function etiqueta(ts){return new Intl.DateTimeFormat('es-MX',{timeZone:TZ,weekday:'short',day:'numeric',month:'short'}).format(new Date(ts)).replace(/\./g,'');}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function f2(x){return (Math.round(x*100)/100).toFixed(2);}
function sg(x,d){var s=x>0?'+':(x<0?'−':'');return s+Math.abs(x).toFixed(d==null?2:d);}

/* ---------- 1. Que apostar hoy: solo lo que aun no empieza; si hoy no hay, la proxima jornada ---------- */
function hoy(){var L=$('#hoy-lista');if(!L)return;var rows=$$('.hoy-row',L),now=Date.now(),td=ymd(now);
 var kk=function(r){var k=Date.parse(r.dataset.ko);return isNaN(k)?null:k;};
 var up=rows.filter(function(r){var k=kk(r);return k===null||k>now;});
 var hoyR=up.filter(function(r){var k=kk(r);return k!==null&&ymd(k)===td;});
 var show=[],msg='';
 if(hoyR.length){show=hoyR;msg='Elecciones con ventaja para hoy ('+hoyR.length+'). Los partidos que ya empezaron no aparecen.';}
 else if(up.length){var key=function(r){var k=kk(r);return k===null?'9999':ymd(k);};var ds=up.map(key).sort()[0];show=up.filter(function(r){return key(r)===ds;});
  var k0=kk(show[0]);msg='Hoy no hay elecciones con ventaja por jugar. Próxima jornada con elecciones: '+(k0===null?'por definir':etiqueta(k0))+' ('+show.length+').';}
 rows.forEach(function(r){r.hidden=show.indexOf(r)<0;});
 var s=$('#hoy-sub');if(s)s.textContent=msg;var v=$('#hoy-vacio');if(v)v.hidden=show.length>0;}

/* ---------- 2. aviso de version nueva ---------- */
var GEN=($('#fresh')||{dataset:{}}).dataset.gen,ultV=0;
function version(){if(!GEN||!/^https?:$/.test(location.protocol)||/\/archivo\//.test(location.pathname))return;var t0=Date.now();if(t0-ultV<60000)return;ultV=t0;
 fetch(location.pathname+'?_v='+t0,{cache:'no-store'}).then(function(r){return r.ok?r.text():'';}).then(function(t){var m=t.match(/id="fresh"[^>]*data-gen="([^"]+)"/);if(!m)return;
  var a=Date.parse(m[1]),b=Date.parse(GEN);if(!isNaN(a)&&!isNaN(b)&&a>b){var n=$('#nueva');if(n)n.hidden=false;}}).catch(function(){});}

/* ---------- 3. Mis apuestas (todo en localStorage; nada sale del navegador) ---------- */
var KEY='nflmodelo.misapuestas.v1',MEM=null,RES={};
try{RES=JSON.parse(($('#ma-res')||{}).textContent||'{}');}catch(e){RES={};}
function cargar(){if(MEM)return MEM;var o=null;try{o=JSON.parse(localStorage.getItem(KEY)||'null');}catch(e){o=null;}
 if(!o||!Array.isArray(o.bets))o={b0:100,bets:[]};if(!(o.b0>0))o.b0=100;MEM=o;return MEM;}
function guardar(){try{localStorage.setItem(KEY,JSON.stringify(MEM));}catch(e){}}
function pCuota(s){s=String(s==null?'':s).trim().replace(',','.');if(!/^\d+(\.\d+)?$/.test(s))return NaN;var v=parseFloat(s);return(v>1&&v<=100)?v:NaN;}
function pU(s){s=String(s==null?'':s).trim().replace(',','.');if(!/^\d+(\.\d+)?$/.test(s))return NaN;var v=parseFloat(s);return(v>0&&v<=1000)?v:NaN;}
function resultado(b){if(b.r==='gana')return 'g';if(b.r==='pierde')return 'p';if(b.r==='push')return 'e';
 var R=RES[b.gid];if(!R||!b.side||b.mk==='otro')return null;var hs=R[0],as=R[1];
 if(b.mk==='ml'){if(hs===as)return 'e';return((b.side==='home')===(hs>as))?'g':'p';}
 if(b.mk==='sp'){var m=hs-as;if(m===b.line)return 'e';return((b.side==='home')===(m>b.line))?'g':'p';}
 if(b.mk==='to'){var t=hs+as;if(t===b.line)return 'e';return((b.side==='over')===(t>b.line))?'g':'p';}
 return null;}
function ganancia(b,r){return r==='g'?b.u*(b.odds-1):(r==='p'?-b.u:0);}
function resumen(bets){var o={n:bets.length,pend:0,g:0,p:0,e:0,staked:0,net:0,enjuego:0};
 bets.forEach(function(b){var r=resultado(b);if(r===null){o.pend++;o.enjuego+=b.u;return;}o[r]++;if(r!=='e')o.staked+=b.u;else o.staked+=0;o.net+=ganancia(b,r);});
 var liq=o.g+o.p;o.acierto=liq?o.g/liq:null;o.roi=o.staked>0?o.net/o.staked:null;return o;}
function subset(bets,fn){return bets.filter(fn);}
function fmtRoi(o){return o.roi===null?'—':sg(o.roi*100,1)+' %';}
function curva(c,b0){var pts=[b0],cur=b0;c.forEach(function(b){var r=resultado(b);if(r===null)return;cur+=ganancia(b,r);pts.push(cur);});
 if(pts.length<2)return '<p class="explain">La curva de banca aparece cuando tengas al menos una apuesta calificada.</p>';
 var W=640,H=230,pl=56,pr=14,pt=14,pb=30,mn=Math.min.apply(null,pts),mx=Math.max.apply(null,pts);if(mx-mn<1){mx+=.5;mn-=.5;}
 var X=function(i){return pl+(W-pl-pr)*i/(pts.length-1);},Y=function(v){return pt+(H-pt-pb)*(1-(v-mn)/(mx-mn));};
 var d=pts.map(function(v,i){return (i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1);}).join(' ');
 var y0=Y(b0);
 return '<div class="chart ma-chart"><svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Curva de tu banca en unidades, de '+f2(pts[0])+' a '+f2(pts[pts.length-1])+'">'
  +'<line x1="'+pl+'" x2="'+(W-pr)+'" y1="'+y0.toFixed(1)+'" y2="'+y0.toFixed(1)+'" style="stroke:var(--text-2)" stroke-dasharray="5 4" stroke-width="1.5"/>'
  +'<path d="'+d+'" fill="none" style="stroke:var(--accent)" stroke-width="3" stroke-linejoin="round"/>'
  +pts.map(function(v,i){return '<circle cx="'+X(i).toFixed(1)+'" cy="'+Y(v).toFixed(1)+'" r="3.5" style="fill:var(--accent)"/>';}).join('')
  +'<text class="ut" x="'+(pl-6)+'" y="'+(Y(mx)+4).toFixed(1)+'" text-anchor="end" style="fill:var(--text-2)" font-size="12">'+mx.toFixed(1)+'</text>'
  +'<text class="ut" x="'+(pl-6)+'" y="'+(Y(mn)+4).toFixed(1)+'" text-anchor="end" style="fill:var(--text-2)" font-size="12">'+mn.toFixed(1)+'</text>'
  +'<text class="ut" x="'+(W-pr)+'" y="'+(H-8)+'" text-anchor="end" style="fill:var(--text-2)" font-size="12">apuesta n.º</text>'
  +'<text class="ut" x="'+pl+'" y="'+(H-8)+'" style="fill:var(--text-2)" font-size="12">inicio: '+f2(b0)+' u</text></svg></div>';}
function render(){var h=$('#ma-host');if(!h)return;var D=cargar(),bets=D.bets,S=resumen(bets);
 var banca=D.b0+S.net,kp=function(t,v,cls){return '<div'+(cls?' class="'+cls+'"':'')+'><small>'+t+'</small><b>'+v+'</b></div>';};
 var k=kp('Apuestas',S.n+(S.pend?' ('+S.pend+' en juego)':''))+kp('Acierto',S.acierto===null?'—':(S.acierto*100).toFixed(0)+' %')
  +kp('Unidades netas',sg(S.net)+' u',S.net<0?'neg':(S.net>0?'pos':''))+kp('ROI',fmtRoi(S),S.roi!==null&&S.roi<0?'neg':(S.roi>0?'pos':''))
  +kp('Banca ahora',f2(banca)+' u');
 var m=bets.filter(function(b){return b.p!=null;}),o=bets.filter(function(b){return b.p==null;}),Sm=resumen(m),So=resumen(o);
 var mn=parseFloat(h.dataset.modN),mr=parseFloat(h.dataset.modRoi),ma=parseFloat(h.dataset.modAc);
 var cmp='<table class="ma-cmp"><caption class="ks" style="text-align:left">Tú frente al modelo</caption><thead><tr><th>Qué</th><th>Apuestas</th><th>ROI</th></tr></thead><tbody>'
  +'<tr><td>Tus apuestas con elecciones del modelo</td><td>'+Sm.n+'</td><td>'+fmtRoi(Sm)+'</td></tr>'
  +'<tr><td>Tus apuestas por tu cuenta</td><td>'+So.n+'</td><td>'+fmtRoi(So)+'</td></tr>'
  +'<tr><td>El modelo en sus «posibles valores» (pruebas pasadas; spread, total y ganador juntos)</td><td>'+(isNaN(mn)?'—':mn)+'</td><td>'+(isNaN(mr)?'—':sg(mr*100,1)+' %')+'</td></tr></tbody></table>';
 var aviso=(S.g+S.p)<30?'<p class="explain keep">Con menos de 30 apuestas calificadas, el ROI es sobre todo azar: no saques conclusiones todavía.</p>':'';
 var ls=bets.slice().reverse().map(function(b){var r=resultado(b),est;
  if(r==='g')est='<span class="vchip valor">✔ Ganada '+sg(ganancia(b,r))+' u</span>';else if(r==='p')est='<span class="vchip contra">✖ Perdida '+sg(ganancia(b,r))+' u</span>';
  else if(r==='e')est='<span class="vchip neutral">— Push (devuelta)</span>';else est='<span class="vchip info">ⓘ Pendiente</span>';
  var mkn={sp:'Spread',to:'Total (Más de / Menos de)',ml:'Ganador',otro:'Otro'}[b.mk]||'';
  var sel='<label>Resultado <select data-ma-r="'+esc(b.id)+'"><option value="auto"'+(!b.r||b.r==='auto'?' selected':'')+'>Automático</option><option value="gana"'+(b.r==='gana'?' selected':'')+'>Ganada</option><option value="pierde"'+(b.r==='pierde'?' selected':'')+'>Perdida</option><option value="push"'+(b.r==='push'?' selected':'')+'>Push</option></select></label>';
  return '<li class="ma-bet box"><div class="ma-l">'+esc(b.lab)+'</div><small>'+esc((b.part?b.part+' · ':'')+mkn+' · '+(b.t?String(b.t).slice(0,10):''))+(b.p!=null?' · modelo '+Math.round(b.p*100)+' %':'')+'</small>'
   +'<div class="ma-row"><span>Cuota <b>'+f2(b.odds)+'</b> · <b>'+b.u+' u</b></span>'+est+'</div><div class="ma-row">'+sel+'<button type="button" class="chip" data-ma-del="'+esc(b.id)+'">Quitar</button></div></li>';}).join('');
 h.innerHTML='<div class="ma-kpis">'+k+'</div>'+aviso+cmp+curva(bets,D.b0)
  +'<div class="ma-b0"><label for="ma-b0">Banca inicial (en unidades)</label><input id="ma-b0" type="text" inputmode="decimal" value="'+esc(D.b0)+'"><span>1 unidad = 1 % de tu banca; si empiezas con 100 u, es lo habitual.</span></div>'
  +'<div class="ma-acts"><button type="button" class="chip" id="ma-add">Agregar apuesta</button><button type="button" class="chip" id="ma-exp">Exportar (JSON)</button>'
  +'<button type="button" class="chip" id="ma-imp">Importar</button><button type="button" class="chip" id="ma-clr">Borrar todo</button><input type="file" id="ma-file" accept="application/json,.json" aria-label="Importar apuestas desde un archivo JSON" hidden></div>'
  +(bets.length?'<ul class="ma-list">'+ls+'</ul>':'<div class="vacio"><span class="vacio-ic" aria-hidden="true">ⓘ</span><div><b>Todavía no has registrado apuestas.</b> Usa «Registrar en Mis apuestas» en una elección de «Qué apostar hoy» o «Agregar apuesta».</div></div>');}
function toast(t,ver){var e=$('#ma-toast');if(!e)return;e.innerHTML=esc(t)+(ver?' · <a href="#mis-apuestas">Ver Mis apuestas</a>':'');e.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(function(){e.hidden=true;},6000);}
function abrir(p){var f=$('#ma-form');if(!f)return;var tt=$('#ma-toast');if(tt)tt.hidden=true;p=p||{};f._p=p;$('#maf-lab').value=p.lab||'';$('#maf-part').value=p.part||'';$('#maf-mk').value=p.mk||'sp';
 $('#maf-odds').value=p.odds?f2(p.odds):'';$('#maf-u').value=p.u?String(p.u):'';$('#maf-r').value='auto';var er=$('#maf-err');er.hidden=true;er.textContent='';
 $('#ma-ft').textContent=p.lab?'Registrar esta apuesta':'Agregar apuesta';f.hidden=false;f._ant=document.activeElement;($('#maf-lab')).focus();}
function cerrarForm(){var f=$('#ma-form');if(!f)return;f.hidden=true;if(f._ant&&f._ant.focus)try{f._ant.focus();}catch(e){}}
function guardarForm(){var f=$('#ma-form'),p=f._p||{},er=$('#maf-err'),lab=$('#maf-lab').value.trim(),odds=pCuota($('#maf-odds').value),u=pU($('#maf-u').value);
 var msg=!lab?'Escribe qué apostaste (por ejemplo: KC -15.5).':isNaN(odds)?'La cuota debe ser decimal, entre 1.01 y 100 (por ejemplo 1.91).':isNaN(u)?'Las unidades deben ser un número mayor que 0 (por ejemplo 0.5).':'';
 if(msg){er.textContent=msg;er.hidden=false;return;}
 var mk=$('#maf-mk').value,estruct=(p.gid&&mk===p.mk);
 var b={id:'b'+Date.now().toString(36)+Math.random().toString(36).slice(2,6),t:new Date().toISOString(),lab:lab,part:$('#maf-part').value.trim(),mk:mk,
  odds:odds,u:u,r:$('#maf-r').value,gid:estruct?p.gid:null,side:estruct?p.side:null,line:estruct&&p.line!==''&&p.line!=null?parseFloat(p.line):null,p:estruct&&p.p!==''&&p.p!=null?parseFloat(p.p):null};
 var D=cargar();D.bets.push(b);guardar();cerrarForm();render();toast('Apuesta guardada en este dispositivo.',true);}
document.addEventListener('click',function(e){var t=e.target;if(!t.closest)return;
 var rg=t.closest('.ma-reg');if(rg){var d=rg.dataset;abrir({gid:d.gid,mk:d.mk,side:d.side,line:d.line===''?null:d.line,lab:d.lab,part:d.part,odds:parseFloat(d.odds),p:d.p,u:parseFloat(d.u)});return;}
 if(t.closest('#ma-add')){abrir({});return;}
 if(t.closest('#maf-x')){cerrarForm();return;}
 if(t.closest('#nueva-btn')){location.reload();return;}
 var dl=t.closest('[data-ma-del]');if(dl){if(dl.dataset.armado){var D=cargar();D.bets=D.bets.filter(function(b){return b.id!==dl.dataset.maDel;});guardar();render();}
  else{dl.dataset.armado='1';dl.textContent='Confirmar: quitar';setTimeout(function(){if(dl.isConnected){delete dl.dataset.armado;dl.textContent='Quitar';}},3500);}return;}
 if(t.closest('#ma-clr')){var c=t.closest('#ma-clr');if(c.dataset.armado){var D2=cargar();D2.bets=[];guardar();render();}else{c.dataset.armado='1';c.textContent='Confirmar: borrar todo';setTimeout(function(){if(c.isConnected){delete c.dataset.armado;c.textContent='Borrar todo';}},3500);}return;}
 if(t.closest('#ma-exp')){var blob=new Blob([JSON.stringify(cargar(),null,1)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='mis_apuestas_nfl.json';document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},500);return;}
 if(t.closest('#ma-imp')){var fi=$('#ma-file');if(fi)fi.click();return;}});
document.addEventListener('submit',function(e){if(e.target&&e.target.id==='ma-f'){e.preventDefault();guardarForm();}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var f=$('#ma-form');if(f&&!f.hidden)cerrarForm();}});
document.addEventListener('change',function(e){var t=e.target;
 if(t.matches&&t.matches('[data-ma-r]')){var D=cargar();D.bets.forEach(function(b){if(b.id===t.dataset.maR)b.r=t.value;});guardar();render();return;}
 if(t.id==='ma-b0'){var v=pU(t.value);if(!isNaN(v)){cargar().b0=v;guardar();}render();return;}
 if(t.id==='ma-file'&&t.files&&t.files[0]){var rd=new FileReader();rd.onload=function(){try{var o=JSON.parse(rd.result),L=Array.isArray(o)?o:o.bets,D=cargar(),n=0,ids={};D.bets.forEach(function(b){ids[b.id]=1;});
  (L||[]).forEach(function(b){if(b&&b.id&&!ids[b.id]&&b.lab&&b.odds>1&&b.u>0){D.bets.push({id:String(b.id),t:b.t||'',lab:String(b.lab).slice(0,80),part:String(b.part||'').slice(0,60),mk:b.mk||'otro',odds:+b.odds,u:+b.u,r:b.r||'auto',gid:b.gid||null,side:b.side||null,line:b.line==null?null:+b.line,p:b.p==null?null:+b.p});ids[b.id]=1;n++;}});
  if(o&&o.b0>0&&!Array.isArray(o))D.b0=+o.b0;guardar();render();toast('Importadas '+n+' apuestas.',false);}catch(x){toast('No pude leer ese archivo.',false);}};rd.readAsText(t.files[0]);t.value='';}});

/* ---------- 5. tarjeta compartible (canvas) ---------- */
var TJ=null,FMT={v:[1080,1920],c:[1080,1080],h:[1920,1080]};
function rr(g,x,y,w,h,r){g.beginPath();g.moveTo(x+r,y);g.arcTo(x+w,y,x+w,y+h,r);g.arcTo(x+w,y+h,x,y+h,r);g.arcTo(x,y+h,x,y,r);g.arcTo(x,y,x+w,y,r);g.closePath();}
function fit(g,txt,max,font,size){var s=size;do{g.font=font.replace('%',s);if(g.measureText(txt).width<=max)break;s-=2;}while(s>14);return s;}
function dibujar(){var cv=$('#tj-cv');if(!cv)return;if(!TJ){try{TJ=JSON.parse($('#tj-data').textContent);}catch(e){return;}}
 var fm=$('#tj-fmt').value,mod=$('#tj-mod').value,W=FMT[fm][0],H=FMT[fm][1];cv.width=W;cv.height=H;var g=cv.getContext('2d');
 var SANS='system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif';
 g.fillStyle='#000';g.fillRect(0,0,W,H);
 var gr=g.createLinearGradient(0,0,W,H);gr.addColorStop(0,'#D5E0F0');gr.addColorStop(.4,'#8AA0BF');gr.addColorStop(.7,'#5F7799');gr.addColorStop(1,'#B9C8DE');
 g.strokeStyle=gr;g.lineWidth=6;rr(g,18,18,W-36,H-36,36);g.stroke();
 var M=Math.round(W*.065),y=M+30,hz=fm==='h';
 g.fillStyle='#F3F6FB';g.textBaseline='alphabetic';g.font='800 '+(hz?64:76)+'px '+SANS;g.fillText('NFL · SEMANA '+TJ.semana,M,y+(hz?40:56));
 g.fillStyle='#A9B5C7';g.font='600 '+(hz?30:34)+'px '+SANS;
 g.fillText(mod==='valor'?'Posibles valores del modelo':'Elección del modelo: ganador de cada partido',M,y+(hz?92:118));
 var top=y+(hz?130:160),foot=H-M-(hz?58:96),vals=[];TJ.juegos.forEach(function(j){j.vals.forEach(function(v){vals.push({j:j,v:v});});});
 var area=foot-top;
 function pie(){g.fillStyle='#A9B5C7';g.font='500 '+(hz?22:26)+'px '+SANS;g.fillText('Modelo estadístico: no es garantía ni asesoría financiera.',M,H-M-(hz?28:52));
  g.fillStyle='#C3D1E6';g.font='700 '+(hz?24:28)+'px '+SANS;g.fillText('Los Picketones · 1darkcheeta.github.io/nfl-modelo',M,H-M-(hz?0:14));}
 function bloqueValor(x0,yy,w,hmax){var n=vals.length;if(!n){g.fillStyle='#A9B5C7';g.font='600 30px '+SANS;g.fillText('Esta semana ningún partido supera el umbral de valor.',x0,yy+40);return yy+60;}
  var rh=Math.min(150,Math.floor(hmax/n)),pad=Math.max(8,Math.round(rh*.07));
  vals.slice(0,Math.max(1,Math.floor(hmax/rh))).forEach(function(o,i){var y0=yy+i*rh;g.fillStyle='#0E131B';rr(g,x0,y0,w,rh-pad,18);g.fill();g.strokeStyle='#5F7799';g.lineWidth=2;rr(g,x0,y0,w,rh-pad,18);g.stroke();
   var s1=fit(g,o.v.lab,w*.52,'800 %px '+SANS,Math.round(rh*.36));g.fillStyle='#F3F6FB';g.fillText(o.v.lab,x0+22,y0+(rh-pad)*.48);
   g.fillStyle='#A9B5C7';g.font='500 '+Math.max(18,Math.round(rh*.2))+'px '+SANS;g.fillText(o.v.t+' · '+o.j.a+' @ '+o.j.h,x0+22,y0+(rh-pad)*.82);
   g.textAlign='right';g.fillStyle='#3DDC84';g.font='800 '+Math.round(rh*.34)+'px '+SANS;g.fillText('cuota '+o.v.cuota,x0+w-22,y0+(rh-pad)*.48);
   g.fillStyle='#C3D1E6';g.font='600 '+Math.max(18,Math.round(rh*.2))+'px '+SANS;g.fillText('ventaja '+(o.v.edge>0?'+':'')+o.v.edge.toFixed(1)+' pts'+(o.v.u?' · '+o.v.u+' u':''),x0+w-22,y0+(rh-pad)*.82);g.textAlign='left';});
  return yy+Math.min(n,Math.floor(hmax/rh))*rh;}
 if(mod==='valor'){bloqueValor(M,top,W-2*M,area);}
 else{var gs=TJ.juegos,cols=hz?2:1,per=Math.ceil(gs.length/cols),cw=(W-2*M-(cols-1)*30)/cols,ah=area;
  var vh=(!hz&&vals.length)?Math.min(vals.length,3)*0+0:0;
  var rh=Math.min(hz?84:118,Math.floor(ah/Math.max(per,1)));
  gs.forEach(function(j,i){var c=Math.floor(i/per),r=i%per,x0=M+c*(cw+30),y0=top+r*rh;var tv=j.vals.length>0;
   g.fillStyle='#0E131B';rr(g,x0,y0,cw,rh-10,16);g.fill();g.strokeStyle=tv?'#3DDC84':'#5F7799';g.lineWidth=tv?3:2;rr(g,x0,y0,cw,rh-10,16);g.stroke();
   g.fillStyle='#A9B5C7';g.font='600 '+Math.max(16,Math.round(rh*.2))+'px '+SANS;g.fillText(j.a+' @ '+j.h,x0+18,y0+(rh-10)*.4);
   g.fillStyle='#F3F6FB';fit(g,'Gana '+j.eq+' · '+j.p+' %',cw-36-(tv?150:0),'800 %px '+SANS,Math.round(rh*.3));g.fillText('Gana '+j.eq+' · '+j.p+' %',x0+18,y0+(rh-10)*.8);
   if(tv){var vt='✔ valor: '+j.vals[0].lab+(j.vals.length>1?' +'+(j.vals.length-1):'');g.textAlign='right';g.fillStyle='#3DDC84';fit(g,vt,cw*.5,'800 %px '+SANS,Math.max(16,Math.round(rh*.19)));g.fillText(vt,x0+cw-18,y0+(rh-10)*.4);g.textAlign='left';}});}
 pie();}
function iniTj(){var d=$('#tarjeta');if(!d||d._ini)return;d._ini=1;
 var rd=function(){dibujar();};d.addEventListener('toggle',function(){if(d.open)rd();});$('#tj-fmt').addEventListener('change',rd);$('#tj-mod').addEventListener('change',rd);
 function nombre(){return 'nfl_semana'+(TJ?TJ.semana:'')+'_'+$('#tj-mod').value+'_'+$('#tj-fmt').value+'.png';}
 function blob(cb){$('#tj-cv').toBlob(cb,'image/png');}
 $('#tj-dl').addEventListener('click',function(){dibujar();blob(function(b){var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=nombre();document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},500);});});
 var sh=$('#tj-sh');if(sh&&navigator.share&&navigator.canShare){sh.hidden=false;sh.addEventListener('click',function(){dibujar();blob(function(b){var f=new File([b],nombre(),{type:'image/png'});if(navigator.canShare({files:[f]}))navigator.share({files:[f],title:'NFL semana '+(TJ?TJ.semana:'')}).catch(function(){});});});}}

/* ---------- arranque ---------- */
function ini(){hoy();iniTj();render();version();setInterval(hoy,60000);setInterval(version,300000);
 document.addEventListener('visibilitychange',function(){if(!document.hidden){hoy();version();}});}
window.__fr=window.__fr||[];window.__fr.push(function(host){if(host.querySelector&&host.querySelector('#ma-host'))render();});
window.__MA={render:render,abrir:abrir,resultado:resultado,resumen:resumen,pCuota:pCuota,dibujar:dibujar};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ini);else ini();
})();
</script>
"""
