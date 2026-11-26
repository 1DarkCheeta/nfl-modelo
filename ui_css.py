"""Sistema de diseno unico del sitio: tokens (ui/tokens.css) + componentes + remapeo de las variables antiguas.

Dos temas (claro por defecto y oscuro con boton en la cabecera). Ningun color suelto: todo sale de las variables de tokens.css.
reporte.py inserta CSS_TODO al final de <style>, asi que tambien cubre el codigo antiguo (reporte_extra, puntos, por_equipo, ...).
"""
from pathlib import Path

TOKENS = (Path(__file__).resolve().parent / "ui" / "tokens.css").read_text(encoding="utf-8")

import re as _re
_claro, _oscuro = TOKENS.split(':root[data-theme="dark"]')[0], TOKENS.split(':root[data-theme="dark"]')[1].split(":root {")[0]
COL_L = {k: v for k, v in _re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", _claro)}   # tema claro  {'valor': '#0F7A3C', ...}
COL_D = {**COL_L, **{k: v for k, v in _re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", _oscuro)}}   # tema oscuro
COL = COL_L

# Variables que usa el codigo antiguo -> tokens nuevos (asi todo el sitio cambia sin tocar su logica)
LEGACY = """
:root{--card:var(--surface);--ink:var(--text);--ink2:var(--text-2);--line:var(--border-subtle);--blue:var(--accent);--orange:var(--aviso);
--yes:var(--valor-bg);--yesink:var(--valor);--no:var(--surface-3);--tabh:56px}
"""

BASE = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:auto}
body{margin:0;background:var(--bg);color:var(--text);font:400 var(--fs-15)/var(--lh) var(--font);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:1040px;margin:0 auto;padding:0 var(--s4) 72px}
h1{font-size:var(--fs-20);margin:.1em 0;font-weight:700;letter-spacing:-.01em}h2{font-size:var(--fs-20);margin:2em 0 .5em;font-weight:700;letter-spacing:-.01em}h3{margin:0;font-size:var(--fs-17);font-weight:700}
h4{margin:.2em 0;font-size:var(--fs-12);text-transform:uppercase;letter-spacing:.05em;color:var(--text-2)}
p{margin:.3em 0}a{color:var(--accent)}
.num{font-variant-numeric:tabular-nums}
button,select,input,textarea{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--border-strong);outline-offset:2px}
[hidden]{display:none!important}
.sub{color:var(--text-2);margin:0 0 1em;font-size:var(--fs-14)}
.explain{color:var(--text-2);margin:.2em 0 .6em;font-size:var(--fs-14)}
.leyenda{color:var(--text-2);font-size:var(--fs-14);margin:.2em 0 .8em}
.foot{color:var(--text-2);font-size:var(--fs-12);margin-top:2.5em}
dl{margin:0}dt{font-weight:700;margin-top:.7em}dd{margin:.1em 0 0;color:var(--text-2)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3)}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
/* ---- cajas con borde azul platinado (todas) ---- */
.box,.card,.grow,details.exp,details.sec,details.box,.mcard,.pick,.kpi,.allmenu,.pcard,.verdict,.calcbox,.mh,.chart,#sheet,.filters,.pbl,.pcb,.pjuego>.box{
 border:var(--borde-ancho) solid transparent;border-radius:var(--r);
 background:linear-gradient(var(--surface),var(--surface)) padding-box,var(--metal) border-box}
.box,.card{padding:var(--s5);margin:var(--s4) 0;box-shadow:var(--shadow)}
.box.big{border-left-width:5px}.box ul{margin:.4em 0 0;padding-left:1.2em}
.box.hl,.calcbox{background:linear-gradient(var(--surface-2),var(--surface-2)) padding-box,var(--metal) border-box;border-width:2px}
.chart{padding:var(--s2);margin:var(--s2) 0;overflow-x:auto}.chart img{max-width:100%;height:auto;display:block;margin:auto}
@media (forced-colors:active){.box,.card,.grow,.mcard,.pick,.kpi{border-color:CanvasText;background:Canvas}}
.card header{display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}.card header span{color:var(--text-2)}
.fecha{font-size:var(--fs-14)}.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s4);margin-top:var(--s2)}@media(max-width:900px){.cols{grid-template-columns:1fr}}
.card p{font-size:var(--fs-14)}.mini{color:var(--text-2);font-size:var(--fs-12)!important}
.warn{background:var(--aviso-bg);color:var(--aviso);border:1px solid var(--aviso);border-radius:var(--r-sm);padding:6px 10px;font-size:var(--fs-14)!important;margin-top:10px!important}
.badge{display:inline-block;border-radius:var(--r-sm);padding:5px 10px;font-size:var(--fs-14);margin-top:6px;border:1px solid transparent}
.badge.yes{background:var(--valor-bg);color:var(--valor);border-color:var(--valor);font-weight:600}
.badge.no{background:var(--neutral-bg);color:var(--neutral);border-color:var(--border-subtle)}
.badge.warn{background:var(--aviso-bg);color:var(--aviso);border-color:var(--aviso);font-weight:600}
.bar{position:relative;height:12px;background:var(--surface-3);border:1px solid var(--border-subtle);border-radius:6px;margin-top:8px}
.bar b{display:block;height:100%;background:var(--accent);border-radius:6px 0 0 6px}
.tick{position:absolute;top:-4px;width:3px;height:20px;background:var(--text);border-radius:2px}.barlab{display:flex;justify-content:space-between;font-size:var(--fs-12);color:var(--text-2)}
/* ---- componente: tabla de datos ---- */
table{border-collapse:separate;border-spacing:0;width:100%;font-size:var(--fs-14)}
th,td{padding:8px 10px;border-bottom:1px solid var(--border-subtle);text-align:left;vertical-align:top}
thead th,tr:first-child>th{background:var(--surface-2);font-size:var(--fs-12);color:var(--text-2);letter-spacing:.03em}
td.num,th.num,td.n{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:nth-child(even) td{background:var(--surface-2)}
.scroll{overflow:auto;max-width:100%;max-height:75vh;border-radius:var(--r-sm)}
.scroll thead th,.scroll tr:first-child>th{position:sticky;top:0;z-index:2}
.scroll.ov table th:first-child,.scroll.ov table td:first-child{position:sticky;left:0;background:var(--surface);z-index:1;box-shadow:2px 0 3px -2px rgba(0,0,0,.25)}
.scroll.ov thead th:first-child{background:var(--surface-2);z-index:3}
@media(max-width:600px){th,td{padding:7px 8px}.scroll{max-height:70vh}}
/* ---- campos ---- */
input[type=number],input[type=text],input.lin,input.cuo,input.cuu,input.cutd,input.elin,select,textarea{background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--r-sm);padding:6px 10px;min-height:36px}
input::placeholder{color:var(--text-2);opacity:1}
button{cursor:pointer}
/* ---- componente: chip de veredicto ---- */
.vchip{display:inline-flex;align-items:center;gap:var(--s1);min-height:28px;padding:2px 10px;border-radius:var(--r-pill);font-size:var(--fs-12);font-weight:600;line-height:1.25;border:1px solid transparent;white-space:normal}
.vchip.valor{color:var(--valor);background:var(--valor-bg);border-color:var(--valor)}
.vchip.neutral{color:var(--neutral);background:var(--neutral-bg);border-color:var(--border-subtle)}
.vchip.aviso{color:var(--aviso);background:var(--aviso-bg);border-color:var(--aviso)}
.vchip.contra{color:var(--contra);background:var(--contra-bg);border-color:var(--contra)}
.vchip.info{color:var(--info);background:var(--info-bg);border-color:var(--info)}
.vchip.line{color:var(--text);background:var(--surface-3);border-color:var(--border-subtle)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--s3)}
button.vchip{cursor:pointer;min-height:36px;font-family:inherit}
button.vchip[aria-pressed=true]{background:var(--accent);color:var(--on-accent);border-color:var(--border-strong)}
.bd{border-radius:var(--r-pill);padding:2px 9px;font-size:var(--fs-12);white-space:nowrap;background:var(--neutral-bg);color:var(--neutral);border:1px solid var(--border-subtle)}
.bd-v{background:var(--valor-bg);color:var(--valor);border-color:var(--valor);font-weight:600}.bd-w{background:var(--aviso-bg);color:var(--aviso);border-color:var(--aviso);font-weight:600}
.bdi{font-style:normal;font-size:var(--fs-12)}
.gr-bd,.gp-bd{display:flex;gap:5px;flex-wrap:wrap}
/* ---- componente: barra verde/rojo con línea de corte (probabilidad del modelo vs corte del mercado o umbral) ---- */
.pcut{margin-top:var(--s3)}
.pcut-track{position:relative;display:flex;gap:2px;height:10px;margin:6px 0 0}
.pcut-pos,.pcut-neg{display:block;height:100%}
.pcut-pos{background:var(--bar-pos);border-radius:99px 0 0 99px;min-width:2px}.pcut-neg{background:var(--bar-neg);border-radius:0 99px 99px 0;min-width:2px;flex:1 1 auto}
.pcut-pos:only-of-type{border-radius:99px}
.pcut-cut{position:absolute;top:-6px;bottom:-6px;width:2px;margin-left:-1px;background:var(--cut);border-radius:2px;box-shadow:0 0 0 1.5px var(--surface)}
.pcut-lab{display:flex;justify-content:space-between;align-items:baseline;gap:var(--s2);margin-top:var(--s2);font-size:var(--fs-12);color:var(--text-2)}
.pcut-lab .pos{color:var(--valor);font-weight:700;font-size:var(--fs-14)}.pcut-lab .neg{color:var(--contra);font-weight:600;font-size:var(--fs-14)}
.pcut-lab .cut{flex:1;text-align:center;color:var(--text-2)}.pcut-lab .cut b{color:var(--text)}
.pcut-lab .cut.ok b{color:var(--valor)}.pcut-lab .cut.no b{color:var(--contra)}
/* ---- componente: tarjeta (partido o pick): fecha + estado arriba · enfrentamiento y números al centro · barra · pie ---- */
.mcard,.pick{position:relative;display:flex;flex-direction:column;padding:var(--s5);box-shadow:var(--shadow)}
.mcard{margin-top:0}
.gc-top{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--s2);flex-wrap:wrap}
.when{font-size:var(--fs-12);color:var(--text-2);font-weight:600;letter-spacing:.02em}
.gc-mid{margin-top:var(--s4)}
.teams{display:flex;align-items:baseline;gap:var(--s2);font-size:var(--fs-24);font-weight:800;letter-spacing:.01em;margin:0;line-height:1.15}.teams .at{color:var(--text-2);font-weight:500;font-size:var(--fs-17)}
.full{font-size:var(--fs-12);color:var(--text-2);margin-top:2px}
.score{font-size:var(--fs-15);color:var(--text-2);margin-top:var(--s3)}.score b{color:var(--text);font-size:var(--fs-17)}
.gc-nums{display:flex;flex-wrap:wrap;gap:2px var(--s4);margin-top:var(--s1);font-size:var(--fs-14);color:var(--text-2)}.gc-nums b{color:var(--text)}
.gc-foot{display:flex;justify-content:space-between;align-items:center;gap:var(--s2);flex-wrap:wrap;margin-top:var(--s4);padding-top:var(--s3);border-top:1px solid var(--border-subtle)}
.gc-alerts{display:flex;gap:6px;flex-wrap:wrap}
.more{display:inline-flex;align-items:center;min-height:var(--touch);font-size:var(--fs-14);font-weight:600;color:var(--accent);background:none;border:0;padding:0;margin-left:auto}
.mlist{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:var(--s4)}@media(max-width:700px){.mlist{grid-template-columns:1fr}}
.sem-sec{margin:var(--s6) 0 var(--s2)}.sem-sec h3{font-size:var(--fs-17)}.sem-sec .leyenda{margin:2px 0 0}
details.semsig{margin-top:var(--s6)}details.semsig .mcard{opacity:1}
/* ---- chips de estado / alertas ---- */
.vchip{display:inline-flex;align-items:center;gap:var(--s1);min-height:26px;padding:2px 10px;border-radius:var(--r-pill);font-size:var(--fs-12);font-weight:600;line-height:1.25;border:1px solid transparent;white-space:normal}
.vchip.valor{color:var(--valor);background:var(--valor-bg);border-color:var(--valor)}
.vchip.neutral{color:var(--neutral);background:var(--neutral-bg);border-color:var(--border)}
.vchip.aviso{color:var(--aviso);background:var(--aviso-bg);border-color:var(--aviso)}
.vchip.contra{color:var(--contra);background:var(--contra-bg);border-color:var(--contra)}
.vchip.info{color:var(--info);background:var(--info-bg);border-color:var(--info)}
.vchip.line{color:var(--text);background:var(--surface-3);border-color:var(--border-subtle)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--s3)}
button.vchip{cursor:pointer;min-height:36px;font-family:inherit}
button.vchip[aria-pressed=true]{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.bd{border-radius:var(--r-pill);padding:2px 9px;font-size:var(--fs-12);white-space:nowrap;background:var(--neutral-bg);color:var(--neutral);border:1px solid var(--border)}
.bd-v{background:var(--valor-bg);color:var(--valor);border-color:var(--valor);font-weight:600}.bd-w{background:var(--aviso-bg);color:var(--aviso);border-color:var(--aviso);font-weight:600}
.bdi{font-style:normal;font-size:var(--fs-12)}
.gr-bd,.gp-bd{display:flex;gap:5px;flex-wrap:wrap}
/* ---- carrusel de picks ---- */
.carousel{display:flex;gap:var(--s4);overflow-x:auto;scroll-snap-type:x mandatory;padding:4px var(--s4) var(--s3);margin:0 calc(-1 * var(--s4));scrollbar-width:thin}
.pick{flex:0 0 84%;max-width:340px;scroll-snap-align:start;cursor:pointer}
.pk-m{font-size:var(--fs-12);color:var(--text-2);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.pk-lado{font-size:var(--fs-20);font-weight:800;margin-top:var(--s2);line-height:1.2}
.pk-edge{margin-top:var(--s2);color:var(--text)}.pk-edge .num{font-size:var(--fs-32);font-weight:800;line-height:1.1;letter-spacing:-.02em}
.pk-edge.v .num{color:var(--valor)}.pk-edge.a .num{color:var(--aviso)}.pk-u{font-size:var(--fs-14);font-weight:600;color:var(--text-2)}
.pk-det{font-size:var(--fs-14);color:var(--text-2);margin-top:var(--s1)}.pk-det b{color:var(--text)}.pk-g{font-size:var(--fs-12);color:var(--text-2)}
@media(min-width:760px){.pick{flex-basis:320px}}
@media(max-width:700px){.carousel{margin:0 calc(-1 * var(--s3));padding-left:var(--s3);padding-right:var(--s3)}}
/* ---- barra de filtros (una sola línea) ---- */
.fbar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:var(--s2) var(--s3);padding:var(--s3) var(--s4);margin:var(--s4) 0 var(--s2)}
.fbar label{display:grid;gap:2px;flex:1 1 140px;min-width:0;font-size:var(--fs-12);color:var(--text-2);font-weight:600}
.fbar select{min-height:40px;font-size:16px;width:100%}
.fbar .toggle{min-height:40px;padding:0 var(--s3)}
.fbar .limpiar{min-height:40px;padding:0 var(--s3);border-radius:var(--r-pill);background:none;border:0;color:var(--accent);font-weight:600;font-size:var(--fs-14)}
.fbar .fcount{margin:0 0 0 auto;font-size:var(--fs-12);color:var(--text-2)}
.toggle{min-height:var(--touch);padding:0 var(--s4);border-radius:var(--r-pill);background:var(--surface);border:1px solid var(--border-strong);font-weight:600;font-size:var(--fs-14)}
.toggle[aria-pressed="true"]{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.fcount{font-size:var(--fs-14);color:var(--text-2);margin:var(--s3) 0}
/* ---- estado vacio ---- */
.vacio{display:flex;gap:var(--s3);align-items:flex-start;padding:var(--s4);margin:var(--s3) 0;border:1px dashed var(--border);border-radius:var(--r);background:var(--surface);color:var(--text-2);font-size:var(--fs-14)}
.vacio-ic{flex:none;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;color:var(--info);border:1.5px solid var(--info);font-weight:700;font-size:var(--fs-14)}
.vacio b{color:var(--text)}
.cargando{padding:var(--s6) 0;color:var(--text-2);text-align:center}
/* ---- cabecera compacta ---- */
.top{display:flex;align-items:center;gap:var(--s2) var(--s3);flex-wrap:wrap;padding:var(--s5) 0 var(--s2)}
.top .ttl{flex:1 1 220px;min-width:0}
.top .kick{display:block;font-size:var(--fs-12);color:var(--text-2);font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.top h1{margin:2px 0 0;font-size:var(--fs-24);font-weight:800;letter-spacing:-.02em;line-height:1.1}
.hbtns{display:flex;gap:var(--s2)}
.ibtn{width:var(--touch);height:var(--touch);border-radius:50%;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);display:grid;place-items:center;padding:0}
.ibtn svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.ibtn .i-sol{display:none}:root[data-theme="dark"] .ibtn .i-sol{display:block}:root[data-theme="dark"] .ibtn .i-luna{display:none}
.top .sub{flex-basis:100%;margin:0;font-size:var(--fs-12);color:var(--text-2);display:flex;flex-wrap:wrap;gap:2px var(--s3);align-items:center}
.fresh{display:inline-block;font-size:var(--fs-12);color:var(--text-2);white-space:normal}
.fresh.viejo{background:var(--aviso-bg);color:var(--aviso);border:1px solid var(--aviso);border-radius:var(--r-pill);padding:2px 10px;font-weight:600}
.stale{margin-top:var(--s2);font-size:var(--fs-14);color:var(--aviso);background:var(--aviso-bg);border:1px solid var(--aviso);border-radius:var(--r-sm);padding:var(--s2) var(--s3);flex-basis:100%}
/* ---- navegación segmentada (4 secciones) ---- */
.appnav{position:sticky;top:0;z-index:50;background:var(--bg);padding:var(--s2) 0 var(--s3);margin:0}
.seg{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;padding:3px;background:var(--surface-3);border:1px solid var(--border);border-radius:var(--r)}
.navbtn{min-height:44px;border:0;border-radius:11px;background:transparent;color:var(--text-2);font-size:13px;font-weight:600;line-height:1.15;text-align:center;padding:4px 6px;white-space:normal}
.navbtn svg{display:none}
.navbtn[aria-current="page"]{background:var(--surface);color:var(--text);box-shadow:0 0 0 1px var(--border),0 1px 3px rgba(16,24,40,.12)}
@media(min-width:900px){.navbtn{font-size:var(--fs-14);min-height:44px}}
html.js .tab{display:none}html.js .tab.on{display:block}
.subnav{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;padding:6px 0;margin:0 0 8px}.subnav::-webkit-scrollbar{display:none}
.subnav a{flex:0 0 auto;white-space:nowrap;font-size:var(--fs-14);border:1px solid var(--border-strong);background:var(--surface);border-radius:var(--r-pill);padding:8px 14px;color:var(--text);text-decoration:none;min-height:36px;display:inline-flex;align-items:center}
.tab [id]{scroll-margin-top:calc(var(--tabh) + 12px)}
.tabsec{font-size:var(--fs-20);margin:var(--s5) 0 var(--s2)}
/* ---- detalle de partido ---- */
.gsel{position:sticky;top:var(--tabh);z-index:30;background:var(--bg);display:flex;gap:8px;align-items:center;padding:6px 0 8px;border-bottom:1px solid var(--border-subtle);margin:10px 0}
.gsel-in{display:flex;gap:6px;overflow-x:auto;flex:1;scrollbar-width:thin;padding-bottom:2px}
.gchip{flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-start;gap:1px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);border-radius:var(--r-sm);padding:6px 10px;font-size:var(--fs-14);min-width:84px;min-height:var(--touch)}
.gchip small{color:var(--text-2);font-size:var(--fs-12)}.gchip.on{border-color:var(--border-strong);box-shadow:inset 0 0 0 1px var(--border-strong);background:var(--surface-3)}
.gc-i{display:flex;gap:2px;min-height:1em}
.gall{flex:0 0 auto;border:1px solid var(--border-strong);background:var(--surface);border-radius:var(--r-sm);padding:6px 10px;font-size:var(--fs-14);min-height:var(--touch)}.gall.on{background:var(--accent);color:var(--on-accent)}
html.js .gpanel{display:none}html.js .gpanel.on,html.js .gpanels.todos .gpanel{display:block}
.gpanel{margin:8px 0 22px}html.js .gpanels.todos .gpanel{border-top:3px solid var(--border-subtle);padding-top:10px}
.mh{position:relative;overflow:hidden;padding:var(--s5)}
.mh .teams{font-size:var(--fs-24)}
.mh .big{display:flex;align-items:baseline;gap:var(--s3);margin-top:var(--s2);flex-wrap:wrap}.mh .big .num{font-size:var(--fs-24);font-weight:800}.mh .big span{color:var(--text-2);font-size:var(--fs-14)}
.resumen1{margin-top:var(--s2);font-size:var(--fs-15)}
.pillbar,.sseg{position:sticky;top:var(--tabh);z-index:10;background:var(--bg);padding:var(--s2) 0;margin-top:var(--s3);display:flex;gap:var(--s2);overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--border-subtle)}
.pillbar::-webkit-scrollbar,.sseg::-webkit-scrollbar{display:none}
.pill,.sbtn{flex:none;min-height:var(--touch);padding:0 var(--s4);border-radius:var(--r-pill);background:var(--surface);border:1px solid var(--border-strong);font-weight:600;font-size:var(--fs-14);white-space:nowrap}
.pill[aria-selected="true"],.sbtn.on{background:var(--accent);color:var(--on-accent);border-color:var(--border-strong)}
html.js .sp{display:none}html.js .sp.on{display:block}
.gpanel .card>header,.gpanel .pjuego>h3{display:none}.gpanel .pjuego,.gpanel .card{margin-top:var(--s3)}
.verdict{padding:var(--s4);margin-top:var(--s3)}.verdict h3{font-size:var(--fs-17);font-weight:800;margin-top:var(--s2)}
.facts{display:grid;gap:var(--s2);margin-top:var(--s3)}
.fact{background:var(--surface-3);border:1px solid var(--border-subtle);border-radius:var(--r-sm);padding:var(--s2) var(--s3);display:flex;justify-content:space-between;align-items:center;gap:var(--s2)}
.fact small{display:flex;align-items:center;font-size:var(--fs-14);color:var(--text-2)}.fact b{font-size:var(--fs-17)}.fact.edge b{color:var(--aviso)}
.hist{margin-top:var(--s3);font-size:var(--fs-14);color:var(--text-2);padding-top:var(--s3);border-top:1px solid var(--border-subtle)}.hist b{color:var(--text)}
.vlist{display:grid;gap:var(--s3)}
.calc-tit{font-size:var(--fs-14);font-weight:800;color:var(--accent);text-transform:uppercase;letter-spacing:.06em;margin:var(--s2) 0 0}
details.exp,details.sec{padding:8px 12px;margin:8px 0}
details.exp>summary,details.sec>summary{cursor:pointer;font-weight:600;color:var(--text-2);font-size:var(--fs-14);min-height:32px}details.sec>summary{color:var(--text);font-size:var(--fs-15)}
details.exp[open]>summary,details.sec[open]>summary{margin-bottom:8px}
/* ---- "?" tactil y hoja inferior ---- */
.tip{position:relative;display:inline-grid;place-items:center;width:22px;height:22px;margin:0 8px;border-radius:50%;background:transparent;border:1.5px solid var(--info);color:var(--info);font-size:var(--fs-12);font-weight:700;line-height:1;padding:0;vertical-align:middle}
.tip::after{content:"";position:absolute;inset:-11px}
#sheet{position:fixed;left:var(--s3);right:var(--s3);bottom:calc(16px + env(safe-area-inset-bottom));z-index:70;max-width:640px;margin:0 auto;padding:var(--s4);box-shadow:var(--shadow-pop);background:linear-gradient(var(--surface-2),var(--surface-2)) padding-box,var(--metal) border-box}
#sheet p{font-size:var(--fs-15)}#sheet b{display:block;margin-bottom:var(--s1)}
#sheet button{margin-top:var(--s3);min-height:var(--touch);padding:0 var(--s4);border-radius:var(--r-pill);background:var(--accent);color:var(--on-accent);border:0;font-weight:700}
@media(min-width:900px){#sheet{bottom:24px}}
/* ---- KPIs de calidad ---- */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--s3);margin:var(--s3) 0}
.kpi{padding:var(--s4);box-shadow:var(--shadow)}.kpi h3{font-size:var(--fs-12);text-transform:uppercase;letter-spacing:.06em;color:var(--text-2);font-weight:700;display:flex;align-items:center}
.kpi .kv{font-size:var(--fs-32);font-weight:800;line-height:1.15;margin-top:var(--s1)}.kpi .ks{font-size:var(--fs-14);color:var(--text-2)}
.kpi .kv.v{color:var(--valor)}.kpi .kv.a{color:var(--aviso)}.kpi .kv.c{color:var(--contra)}
/* ---- varios ---- */
.arriba{position:fixed;right:14px;bottom:20px;z-index:45;width:44px;height:44px;border-radius:50%;border:1px solid var(--border-strong);background:var(--surface);font-size:var(--fs-17);opacity:0;pointer-events:none;transition:opacity .2s}
.arriba.on{opacity:.95;pointer-events:auto}
.skip{position:absolute;left:-999px;top:0;background:var(--accent);color:var(--on-accent);padding:8px 12px;z-index:100}.skip:focus{left:8px}
@media(max-width:700px){main{padding:var(--s3) var(--s3) 96px}button,.pbtn{min-height:38px}button.tip{min-height:0}.chart svg text.ut{font-size:22px}input[type=number],input[type=text]{font-size:16px;min-height:38px}.pmas,.pmenos,.preset,.creset{min-height:40px;min-width:40px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""

CSS_TODO = TOKENS + LEGACY + BASE

CSS_TODO += """
.estado{max-width:900px;margin:1.5em auto;padding:var(--s3) var(--s4);font-size:var(--fs-14)}
.estado .ok{color:var(--valor)}.estado .mal{color:var(--contra)}
.estado table{min-width:520px}
/* ---- graficas en dos temas: se muestra la imagen del tema activo ---- */
img.th-d{display:none!important}:root[data-theme="dark"] img.th-l{display:none!important}:root[data-theme="dark"] img.th-d{display:block!important}
/* ---- ajustes finos del rediseño ---- */
.pcut-lab.top{margin-top:0}.pcut-lab:not(.top){margin-top:var(--s3)}
.gsep{flex:0 0 auto;align-self:center;font-size:var(--fs-12);font-weight:700;color:var(--text-2);text-transform:uppercase;letter-spacing:.06em;padding:0 var(--s2);border-left:1px solid var(--border-strong);margin-left:var(--s1)}
.met h4{margin:var(--s4) 0 var(--s1)}.met .box{margin:var(--s2) 0}
details.exp>summary,details.sec>summary{cursor:pointer;font-weight:600;color:var(--text);font-size:var(--fs-14);min-height:32px;display:flex;align-items:center}
details.exp,details.sec{padding:var(--s3) var(--s4);margin:var(--s3) 0}
.tab>.tabsec:first-child,.tab>h2:first-child{margin-top:var(--s4)}
.tab{padding-top:var(--s1)}
.subnav{margin:0 0 var(--s2)}
.subnav a{font-size:var(--fs-12);font-weight:600;padding:6px 12px;min-height:32px;background:var(--surface)}
.hoy-row,.pick,.mcard{border-radius:var(--r)}
.hr-nums div{background:var(--surface-2)}
.hr-lado{font-size:var(--fs-20)}
.kpi .kv{letter-spacing:-.02em}
"""
