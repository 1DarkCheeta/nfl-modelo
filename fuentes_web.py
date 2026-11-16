"""Datos de rbsdm.com y ourlads.com que se leen con el navegador (no se pueden bajar desde un script).

Esas dos paginas no ofrecen API y no se pueden consultar desde IDLE, asi que Claude las lee en el navegador de la
app y guarda cada lectura como un archivo JSON en la carpeta `fuentes_web/`. Aqui se importan a la base SQL:

  ourlads_depth    depth chart de Ourlads (QB/RB/WR/TE/FB) con el estado de disponibilidad (O, Q, D...)
  rbsdm_equipos    EPA/jugada, tasa de exito y EPA por pase de cada equipo (tabla "Team Tiers" de rbsdm)

Cada lectura queda guardada con su fecha (`capturado`), asi que se acumula el historial. Para actualizar: pide a
Claude "actualiza Ourlads y rbsdm", copia los JSON nuevos a `fuentes_web/` y vuelve a correr semana_nfl.py.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

import db
from data import norm_team

CARPETA = Path(__file__).parent / "fuentes_web"
CARPETA.mkdir(exist_ok=True)

OURLADS_TEAM = {"ARZ": "ARI", "RAM": "LA"}                       # codigos propios de Ourlads
POS_OURLADS = {"LWR": "WR", "RWR": "WR", "SWR": "WR", "WR": "WR", "TE": "TE", "QB": "QB", "RB": "RB", "FB": "RB"}
ESTADOS = {"O": "Out", "D": "Doubtful", "Q": "Questionable", "GTD": "Questionable", "P": "Probable", "IA": "Inactive"}
_STATUS = {"O", "Q", "D", "GTD", "IA", "DNP", "FP", "LP", "ILL", "NFI", "NIR", "PUP", "P"}
_SUFIJO = {"jr", "sr", "ii", "iii", "iv", "v"}


def nombre_norm(s: str) -> str:
    """'Brown, A.J.' o 'A.J. Brown' -> 'aj brown' (para cruzar nombres entre fuentes)."""
    s = str(s)
    if "," in s:
        ap, no = s.split(",", 1)
        s = f"{no.strip()} {ap.strip()}"
    s = re.sub(r"[^a-z ]", "", s.lower().replace("-", " ").replace(".", ""))
    return " ".join(t for t in s.split() if t not in _SUFIJO)


def _celda(txt: str):
    """'Wilson, Garrett 22/1 Q' -> (nombre, origen, estado). El origen es el codigo de draft/fichaje (22/1, T/Phi...)."""
    t = txt.split()
    estado = ""
    if t and t[-1] in _STATUS and len(t) >= 2 and (("/" in t[-2]) or re.match(r"^(CF|SF)\d{2}$", t[-2])):
        estado = t.pop()
    origen = ""
    if t and (("/" in t[-1]) or re.match(r"^(CF|SF)\d{2}$", t[-1])):
        origen = t.pop()
    return " ".join(t), origen, estado


def parsear_ourlads(d: dict) -> pd.DataFrame:
    filas = []
    for code, (upd, rows) in d["depth"].items():
        equipo = norm_team(pd.Series([OURLADS_TEAM.get(code, code)])).iloc[0]
        for r in rows:
            pos_raw, *cel = r.split("|")
            for orden, c in enumerate([x for x in cel if x.strip()], start=1):
                nombre, origen, estado = _celda(c)
                filas.append({"capturado": d["capturado"], "season": d["temporada"], "equipo": equipo,
                              "posicion_ourlads": pos_raw, "posicion": POS_OURLADS[pos_raw], "orden": orden,
                              "jugador": nombre, "jugador_norm": nombre_norm(nombre), "origen": origen,
                              "estado": estado, "actualizado_ourlads": upd})
    return pd.DataFrame(filas)


def parsear_rbsdm(d: dict) -> pd.DataFrame:
    h = d["h"]
    t = pd.DataFrame(d["rows"], columns=h)
    pct = lambda s: s.str.rstrip("%").astype(float) / 100
    out = pd.DataFrame({
        "capturado": d["capturado"], "season": d["temporada"], "semanas": d["semanas"], "filtro": d["filtro"],
        "equipo": norm_team(t["Team"]),
        "off_epa": t["Off EPA/play"].astype(float), "def_epa": t["Def EPA/play"].astype(float),
        "off_sr": pct(t["Off SR"]), "def_sr": pct(t["Def SR"]),
        "off_pase_epa": t["Off Pass EPA"].astype(float), "def_pase_epa": t["Def Pass EPA"].astype(float)})
    return out


def parsear_rbsdm_api(d: dict) -> dict:
    """Lecturas de la API de rbsdm.com -> {tabla_sql: DataFrame} (una fila por equipo, o por QB)."""
    T = d["tablas"]
    base = {"capturado": d["capturado"], "season": d["temporada"], "semanas": d["semanas"]}

    def df(filas):
        t = pd.DataFrame(filas)
        t.insert(0, "equipo", norm_team(t.pop("team_abbr")))
        for k, v in reversed(list(base.items())):
            t.insert(0, k, v)
        return t

    def une(a, b, sufijos=("", "")):
        return df(a).merge(df(b).drop(columns=list(base)), on="equipo", how="outer", suffixes=sufijos)

    return {"rbsdm_team_tiers": df(T["team_tiers"]), "rbsdm_quarterbacks": df(T["quarterbacks"]),
            "rbsdm_pase_neutral": df(T["neutral_pass"]), "rbsdm_cuarto_down": df(T["fourth_down"]),
            "rbsdm_suerte": une(T["luck_off"], T["luck_def"]),
            "rbsdm_series": une(T["series_off"], T["series_def"], ("_ataque", "_defensa"))}


def _guardar(tabla: str, df: pd.DataFrame, archivo: str) -> None:
    con = db._con()
    try:
        cap = df.capturado.iloc[0]
        if db._existe(con, tabla):
            con.execute(f"DELETE FROM {tabla} WHERE capturado = ?", (cap,))
        df.to_sql(tabla, con, if_exists="append", index=False)
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabla}_cap ON {tabla}(capturado)")
        con.execute("INSERT OR REPLACE INTO descargas VALUES (?,?,?,?,?)",
                    (tabla, int(df.season.iloc[0]), len(df), f"navegador: {archivo}", db._ahora()))
        con.commit()
    finally:
        con.close()


def importar_pendientes(log=print) -> dict:
    """Importa a la base los JSON de `fuentes_web/` que aun no estan (cada archivo se importa una sola vez)."""
    hechos = {}
    for p in sorted(CARPETA.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            fuente = d.get("fuente")
            if fuente == "rbsdm_api":
                tablas = parsear_rbsdm_api(d)
            elif fuente == "ourlads":
                tablas = {"ourlads_depth": parsear_ourlads(d)}
            elif fuente == "rbsdm":
                tablas = {"rbsdm_equipos": parsear_rbsdm(d)}
            else:
                continue
            primera = next(iter(tablas))
            con = db._con()
            try:
                ya = db._existe(con, primera) and con.execute(
                    f"SELECT 1 FROM {primera} WHERE capturado = ? LIMIT 1", (d["capturado"],)).fetchone()
            finally:
                con.close()
            if ya:
                continue
            for nombre, df in tablas.items():
                _guardar(nombre, df, p.name)
                hechos[nombre] = len(df)
                log(f"  {p.name}: {len(df)} filas -> {nombre}")
        except Exception as e:                      # un archivo malo no debe detener todo
            log(f"  [aviso] no pude importar {p.name}: {e}")
    return hechos


def _ultima(tabla: str, season: int) -> pd.DataFrame:
    if not db.hay(tabla):
        return pd.DataFrame()
    con = db._con()
    try:
        return pd.read_sql(f"SELECT * FROM {tabla} WHERE season = ? AND capturado = "
                           f"(SELECT MAX(capturado) FROM {tabla} WHERE season = ?)", con, params=(season, season))
    finally:
        con.close()


def ourlads_actual(season: int) -> pd.DataFrame:
    return _ultima("ourlads_depth", season)


def rbsdm_actual(season: int) -> pd.DataFrame:
    """Ultima lectura de rbsdm por equipo, con el ranking (1 = mejor) en cada columna.
    Usa la API (rbsdm_team_tiers, sin redondear) y, si no hay, la tabla leida del navegador (rbsdm_equipos)."""
    t = _ultima("rbsdm_team_tiers", season)
    if len(t):
        t = t.rename(columns={"off_suc": "off_sr", "def_suc": "def_sr", "off_pass_epa": "off_pase_epa", "def_pass_epa": "def_pase_epa"})
    else:
        t = _ultima("rbsdm_equipos", season)
    if t.empty:
        return t
    for c, mayor_es_mejor in (("off_epa", True), ("def_epa", False), ("off_sr", True), ("def_sr", False),
                              ("off_pase_epa", True), ("def_pase_epa", False)):
        t[f"r_{c}"] = t[c].rank(ascending=not mayor_es_mejor, method="min").astype(int)
    return t.set_index("equipo")


# ---------------------------------------------------------------- descarga directa de Ourlads (desde tu PC)
OURLADS_CODIGOS = ["ARZ", "ATL", "BLT", "BUF", "CAR", "CHI", "CIN", "CLV", "DAL", "DEN", "DET", "GB", "HST", "IND", "JAX", "KC",
                   "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "RAM", "SEA", "SF", "TB", "TEN", "WAS"]
OURLADS_URL = "https://www.ourlads.com/nfldepthcharts/depthchart/{}"
_CODIGOS_URL = {"BLT": "BAL", "CLV": "CLE", "HST": "HOU"}     # la pagina usa BAL/CLE/HOU (verificado en su menu)


class _TablaDepth(HTMLParser):
    """Lee la primera tabla 'table-bordered' de Ourlads (la ofensiva): una fila por posicion."""

    def __init__(self):
        super().__init__()
        self.en_tabla, self.listo, self.fila, self.celda, self.filas = False, False, None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and not self.listo and "table-bordered" in (dict(attrs).get("class") or ""):
            self.en_tabla = True
        elif self.en_tabla and tag == "tr":
            self.fila = []
        elif self.en_tabla and self.fila is not None and tag in ("td", "th"):
            self.celda = []

    def handle_data(self, data):
        if self.celda is not None:
            self.celda.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.celda is not None and self.fila is not None:
            self.fila.append(re.sub(r"\s+", " ", "".join(self.celda)).strip())
            self.celda = None
        elif tag == "tr" and self.fila is not None:
            if self.fila and self.fila[0] != "Pos":
                self.filas.append(self.fila)
            self.fila = None
        elif tag == "table" and self.en_tabla:
            self.en_tabla, self.listo = False, True


def parsear_html_ourlads(html_txt: str):
    """HTML de la pagina de un equipo -> (fecha de actualizacion, filas 'POS|jugador1|jugador2|...')."""
    p = _TablaDepth()
    p.feed(html_txt)
    filas = ["|".join([f[0]] + [c for i, c in enumerate(f) if i >= 2 and i % 2 == 0]) for f in p.filas]
    texto = re.sub(r"<[^>]+>", " ", html_txt)
    m = re.search(r"Updated:\s*([0-9/]+\s+[0-9:]+\s*[AP]M\s*ET)", texto)
    return (m.group(1) if m else ""), filas


def _bajar(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "nfl_model/1.0 (uso personal, 1 lectura por semana)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def descargar_ourlads(log=print, temporada: int | None = None, pausa: float = 1.5, bajar=_bajar, forzar: bool = False) -> bool:
    """Lee los 32 depth charts de Ourlads directamente (como lo haria tu navegador), con una pausa entre paginas,
    y los guarda en fuentes_web/ + base de datos. Como maximo una vez cada 20 horas. Si el sitio no responde
    (o bloquea las descargas automaticas) no pasa nada: se usa la ultima lectura guardada."""
    if not forzar and db.hay("ourlads_depth") and db.horas_desde("ourlads_depth", temporada if temporada else dt.date.today().year) < 20:
        return False
    depth, fallos = {}, 0
    for cod in OURLADS_CODIGOS:
        try:
            upd, filas = parsear_html_ourlads(bajar(OURLADS_URL.format(_CODIGOS_URL.get(cod, cod))))
            if not filas:
                raise ValueError("pagina sin tabla")
            depth[cod] = [upd, [f for f in filas if f.split("|")[0] in POS_OURLADS]]
        except Exception as e:
            fallos += 1
            log(f"  [aviso] Ourlads {cod}: {e.__class__.__name__}")
            if fallos >= 3 and not depth:      # el sitio no responde: no insistir
                log("  [aviso] Ourlads no respondio; uso la ultima lectura guardada.")
                return False
        time.sleep(pausa)
    if len(depth) < 28:
        log(f"  [aviso] solo se leyeron {len(depth)} equipos de Ourlads; no se actualiza.")
        return False
    hoy = dt.date.today().isoformat()
    cur = temporada or dt.date.today().year
    (CARPETA / f"ourlads_{hoy}.json").write_text(json.dumps(
        {"fuente": "ourlads", "capturado": hoy, "temporada": cur, "depth": depth}, ensure_ascii=False), encoding="utf-8")
    importar_pendientes(log)
    return True


# ---------------------------------------------------------------- descarga directa de la API de rbsdm.com
RBSDM = "https://rbsdm.com/api"
_UA = {"User-Agent": "nfl_model/1.0 (uso personal, 1 lectura por semana)", "Content-Type": "application/json"}


def _post(endpoint: str, cuerpo: dict | None = None):
    req = urllib.request.Request(f"{RBSDM}/{endpoint}", data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                 headers=_UA, method="GET" if cuerpo is None else "POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def descargar_rbsdm(log=print, pausa: float = 1.2, post=_post, forzar: bool = False) -> bool:
    """Pide a rbsdm.com las mismas consultas que hace su pagina (equipos, QB, pase neutral, 4th down, suerte, series)
    para la temporada y semanas mas recientes, y las guarda en fuentes_web/ + base de datos. Como maximo una vez cada
    20 horas. Si el sitio no responde, se usa la ultima lectura guardada."""
    if not forzar and db.hay("rbsdm_team_tiers") and db.horas_desde("rbsdm_team_tiers", dt.date.today().year) < 20:
        return False
    try:
        meta = post("meta")
        temp = int(meta["max_season"])
        sem = int(next(x["max_week"] for x in meta["season_week_bounds"] if x["season"] == temp))
    except Exception as e:
        log(f"  [aviso] rbsdm no respondio ({e.__class__.__name__}); uso la ultima lectura guardada.")
        return False

    def cuerpo(smin, **extra):
        return {"season_min": smin, "season_max": temp, "week_min": 1, "week_max": sem, "weeks_post_start": "None",
                "weeks_post_end": "None", "downs": [1, 2, 3, 4], "quarters": [1, 2, 3, 4, 5], "wp_filter": 0,
                "exclude_turnovers": False, "team_abbr": "SEA", "qb_min_plays": min(sem * 16, 320), "qb_active_only": False,
                "fourth_wp_min": 20, "fourth_wp_max": 100, "fourth_go_boost_min": 1, **extra}

    pedidos = {"tt": ("team-tiers", cuerpo(temp)), "qb": ("quarterbacks", cuerpo(temp)),
               "np": ("neutral-pass-frequency", cuerpo(temp - 1, wp_filter=20)), "f4": ("fourth-down-summary", cuerpo(temp)),
               "lk": ("luck-summary", cuerpo(temp)), "ss": ("series-success", cuerpo(temp))}
    R = {}
    try:
        for k, (ep, b) in pedidos.items():
            R[k] = post(ep, b)
            time.sleep(pausa)
    except Exception as e:
        log(f"  [aviso] rbsdm fallo en una consulta ({e.__class__.__name__}); no se actualiza.")
        return False
    quita = lambda rows: [{c: v for c, v in r.items() if "logo" not in c and "color" not in c} for r in rows]
    tablas = {"team_tiers": quita(R["tt"]["rows"]), "quarterbacks": quita(R["qb"]["rows"]),
              "neutral_pass": quita(R["np"]["team_summary"]), "fourth_down": quita(R["f4"]["summary_rows"]),
              "luck_off": quita(R["lk"]["offense_rows"]), "luck_def": quita(R["lk"]["defense_rows"]),
              "series_off": quita(R["ss"]["offense_rows"]), "series_def": quita(R["ss"]["defense_rows"])}
    hoy = dt.date.today().isoformat()
    (CARPETA / f"rbsdm_api_{hoy}.json").write_text(json.dumps(
        {"fuente": "rbsdm_api", "capturado": hoy, "temporada": temp, "semanas": f"1-{sem}",
         "filtro": f"temporada {temp}, semanas 1-{sem}, todas las downs y cuartos", "tablas": tablas},
        ensure_ascii=False), encoding="utf-8")
    importar_pendientes(log)
    return True
