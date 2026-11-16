"""Lesionados de los 32 equipos segun ESPN (JSON abierto, sin llave), para completar el reporte oficial.

El reporte oficial (nflverse) llega por partes: el miercoles solo trae la practica de unos cuantos jugadores y el
estatus de partido (Out / Doubtful / Questionable) aparece el jueves y el viernes. ESPN actualiza varias veces al dia
con notas de reporteros y lista tambien a los de lista de lesionados (IR), asi que se usa para llenar esos huecos.

Regla de combinacion (igual que Ourlads): lo oficial manda; ESPN solo agrega a quien el reporte oficial aun no marca.
  Out / Injured Reserve / PUP / Suspension -> Out        Doubtful -> Doubtful        Questionable / Day-To-Day -> Questionable
Tabla SQL: `lesiones_espn` (una foto por dia, se acumula el historial).
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

import db
from fuentes_web import nombre_norm

URLS = ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries",
        "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/injuries"]
COLS = ["capturado", "fuente", "equipo", "jugador", "jugador_norm", "posicion", "estado_espn", "estado", "lesion", "detalle",
        "regreso", "fecha", "nota"]
_ESTADO = {"out": "Out", "injured reserve": "Out", "physically unable to perform": "Out", "non football injury": "Out",
           "suspension": "Out", "doubtful": "Doubtful", "questionable": "Questionable", "day-to-day": "Questionable"}
_EQUIPO = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
MAX_HORAS = 1.0


def parsear(j: dict, capturado: str) -> pd.DataFrame:
    filas = []
    for t in j.get("injuries", []):
        for i in t.get("injuries", []):
            try:
                a = i.get("athlete", {})
                tm = a.get("team", {}).get("abbreviation") or ""
                est = i.get("status", "")
                det = i.get("details", {}) or {}
                filas.append({
                    "capturado": capturado, "fuente": "espn", "equipo": _EQUIPO.get(tm, tm),
                    "jugador": a.get("displayName", ""), "jugador_norm": nombre_norm(a.get("displayName", "")),
                    "posicion": (a.get("position", {}) or {}).get("abbreviation", ""),
                    "estado_espn": est, "estado": _ESTADO.get(est.lower(), ""),
                    "lesion": " ".join(x for x in (det.get("type"), det.get("detail")) if x and x != "Not Specified"),
                    "detalle": det.get("location", "") or "", "regreso": det.get("returnDate", "") or "",
                    "fecha": (i.get("date") or "")[:16], "nota": i.get("shortComment", "") or ""})
            except Exception:
                continue
    return pd.DataFrame(filas, columns=COLS)


def descargar(log=print) -> pd.DataFrame:
    ultimo = None
    for u in URLS:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (modelo nfl personal)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read())
            return parsear(j, db._ahora())
        except Exception as e:
            ultimo = e
    raise RuntimeError(ultimo)


def cargar(refresh: bool = True, log=print, max_horas: float = MAX_HORAS) -> pd.DataFrame:
    """Ultima foto de lesionados de ESPN (la baja si tiene mas de `max_horas`; sin internet usa la guardada)."""
    if refresh and db.horas_desde("lesiones_espn") > max_horas:
        try:
            df = descargar(log)
            if len(df):
                db.agregar_foto("lesiones_espn", df)
                db.marcar_descarga("lesiones_espn", len(df), "espn")
                log(f"  Lesionados ESPN: {len(df)} jugadores en {df.equipo.nunique()} equipos")
        except Exception as e:
            log(f"  [aviso] no pude leer los lesionados de ESPN ({e}); uso la ultima foto guardada")
    if not db.hay("lesiones_espn"):
        return pd.DataFrame(columns=COLS)
    return db.consulta("SELECT * FROM lesiones_espn WHERE capturado = (SELECT MAX(capturado) FROM lesiones_espn)")


def agregar_a_reporte(inj: pd.DataFrame, E: pd.DataFrame, pw: pd.DataFrame, cur: int, wk: int) -> pd.DataFrame:
    """Agrega al reporte de lesiones de la semana a quienes ESPN marca y el reporte oficial aun no (lo oficial manda)."""
    if E is None or E.empty:
        return inj
    E = E[E.estado != ""]
    q = pw[pw.season == cur].sort_values("week").drop_duplicates("player_id", keep="last")
    ids = {(r.team, nombre_norm(r.name)): (r.player_id, r.name, r.position) for r in q.itertuples()}
    oficial = set()
    if len(inj):
        w = inj[(inj.season == cur) & (inj.week == wk) & inj.report_status.isin(["Out", "Doubtful", "Questionable"])]
        oficial = set(w.gsis_id)
    filas = []
    for r in E.itertuples():
        hit = ids.get((r.equipo, r.jugador_norm))
        if hit and hit[0] not in oficial:
            txt = f"según ESPN{' · ' + r.lesion if r.lesion else ''}{' · ' + r.fecha[:10] if r.fecha else ''}"
            filas.append({"season": cur, "week": wk, "team": r.equipo, "gsis_id": hit[0], "full_name": hit[1], "position": hit[2],
                          "report_status": r.estado, "report_primary_injury": txt, "practice_status": ""})
    if not filas:
        return inj
    nuevo = pd.DataFrame(filas).drop_duplicates("gsis_id")
    if len(inj):                       # se quita cualquier fila previa del mismo jugador y semana (sin estatus de partido)
        inj = inj[~((inj.season == cur) & (inj.week == wk) & inj.gsis_id.isin(nuevo.gsis_id))]
    return pd.concat([inj, nuevo], ignore_index=True)
