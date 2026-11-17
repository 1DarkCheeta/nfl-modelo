"""Pronostico del clima en cada estadio (Open-Meteo: gratis, sin llave) para los partidos pendientes.

Para cada partido se baja el pronostico por hora del estadio y se resume la ventana del juego (desde el kickoff y 3 horas):
temperatura, viento, rafagas, probabilidad y cantidad de lluvia/nieve y el tipo de clima. Cada corrida lo vuelve a bajar,
asi que mientras mas cerca del partido, mas confiable (a mas de ~5 dias es solo una idea).

Que se hace con el:
  * Se muestra en la seccion de puntos, junto a cada partido.
  * Se le da al modelo de totales: ya usaba viento y techo, pero para partidos pendientes el viento llegaba vacio (= 0).
    Ahora recibe el pronostico (con `clima_en_modelo: false` en config.json se desactiva).
  * Si el techo es retractil o no se sabe, se usa el historial de ese estadio (cuantas veces se jugo cerrado).
Cada pronostico se guarda en la tabla `clima_pronostico` (una foto por corrida) para poder medir despues que tan bien acerto.
Si no hay internet, se usa la ultima foto guardada (con aviso) y, si no hay ninguna, el modelo sigue como antes.

Backtest (2013-2026, con el clima REAL de cada juego, que es mejor que cualquier pronostico): agregar temperatura y
viento no mejora la precision del modelo de totales frente a la linea del mercado (el mercado ya los descuenta);
solo con viento >= 15 mph el total real quedo ~1.5 pts bajo la linea (n=417, ~2 errores estandar): sugerente, no probado.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability,precipitation,weather_code"
HORAS_PARTIDO = 3                 # ventana del juego (horas desde el kickoff)
VIENTO_FUERTE = 15.0              # mph
FRIO = 32.0                       # grados F
MAX_DIAS = 15                     # mas alla de esto el pronostico no existe

# (latitud, longitud) del estadio de cada equipo
EQUIPOS = {
    "ARI": (33.5276, -112.2626), "ATL": (33.7554, -84.4009), "BAL": (39.2780, -76.6227), "BUF": (42.7738, -78.7870),
    "CAR": (35.2258, -80.8528), "CHI": (41.8623, -87.6167), "CIN": (39.0955, -84.5161), "CLE": (41.5061, -81.6995),
    "DAL": (32.7473, -97.0945), "DEN": (39.7439, -105.0201), "DET": (42.3400, -83.0456), "GB": (44.5013, -88.0622),
    "HOU": (29.6847, -95.4107), "IND": (39.7601, -86.1639), "JAX": (30.3239, -81.6373), "KC": (39.0489, -94.4839),
    "LV": (36.0909, -115.1833), "LAC": (33.9535, -118.3392), "LA": (33.9535, -118.3392), "MIA": (25.9580, -80.2389),
    "MIN": (44.9735, -93.2575), "NE": (42.0909, -71.2643), "NO": (29.9511, -90.0812), "NYG": (40.8135, -74.0745),
    "NYJ": (40.8135, -74.0745), "PHI": (39.9008, -75.1675), "PIT": (40.4468, -80.0158), "SF": (37.4030, -121.9700),
    "SEA": (47.5952, -122.3316), "TB": (27.9759, -82.5033), "TEN": (36.1665, -86.7713), "WAS": (38.9076, -76.8645),
}
# estadios fuera de la sede habitual (se busca por parte del nombre)
NEUTRALES = {
    "banorte": (19.3029, -99.1505), "azteca": (19.3029, -99.1505), "tottenham": (51.6043, -0.0662), "wembley": (51.5560, -0.2795),
    "allianz": (48.2188, 11.6247), "bayern": (48.2188, 11.6247), "deutsche bank": (50.0686, 8.6455),
    "corinthians": (-23.5453, -46.4742), "bernabeu": (40.4531, -3.6883), "maracana": (-22.9121, -43.2302),
    "stade de france": (48.9245, 2.3601), "melbourne": (-37.8200, 144.9834), "croke": (53.3607, -6.2514),
}

_CLIMA = [  # (codigo WMO minimo, maximo, severidad, texto)
    (0, 0, 0, "despejado"), (1, 2, 1, "poco nublado"), (3, 3, 2, "nublado"), (45, 48, 3, "niebla"),
    (51, 57, 4, "llovizna"), (61, 65, 5, "lluvia"), (66, 67, 6, "lluvia helada"), (80, 82, 5, "chubascos"),
    (71, 77, 7, "nieve"), (85, 86, 7, "chubascos de nieve"), (95, 99, 8, "tormenta"),
]


def _texto_clima(cod: int) -> tuple[int, str]:
    for a, b, sev, tx in _CLIMA:
        if a <= cod <= b:
            return sev, tx
    return 2, "nublado"


def coordenadas(home: str, estadio: str | None, ubicacion: str | None) -> tuple[float, float, bool] | None:
    """(lat, lon, aproximada). Si es sede neutral se busca por el nombre del estadio."""
    nombre = (estadio or "").lower()
    if (ubicacion or "") == "Neutral":
        for k, v in NEUTRALES.items():
            if k in nombre:
                return v[0], v[1], False
        if home in EQUIPOS:                       # sede neutral desconocida: usa la del local (aproximada)
            return EQUIPOS[home][0], EQUIPOS[home][1], True
        return None
    if home in EQUIPOS:
        return EQUIPOS[home][0], EQUIPOS[home][1], False
    for k, v in NEUTRALES.items():
        if k in nombre:
            return v[0], v[1], False
    return None


def kickoff_utc(gameday, gametime) -> pd.Timestamp:
    d = pd.Timestamp(gameday).strftime("%Y-%m-%d")
    t = gametime if isinstance(gametime, str) and ":" in gametime else "13:00"
    return pd.Timestamp(f"{d} {t}").tz_localize("America/New_York", ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")


def techo_historial(games: pd.DataFrame, temporadas: int = 3) -> dict:
    """Por equipo local: proporcion de partidos recientes jugados con techo cerrado (dome/closed)."""
    g = games[games.result.notna() & games.roof.notna() & (games.location != "Neutral")]
    if g.empty:
        return {}
    g = g[g.season >= g.season.max() - temporadas + 1]
    return g.groupby("home_team").roof.apply(lambda s: float(s.isin(["dome", "closed"]).mean())).to_dict()


def clasificar_techo(roof, home: str, hist: dict) -> tuple[bool | None, str]:
    """(interior, texto). interior=None -> retractil, no se sabe si lo cierran."""
    if isinstance(roof, str):
        if roof in ("dome", "closed"):
            return True, "techo cerrado (el clima no afecta)"
        if roof in ("outdoors", "open"):
            return False, "al aire libre" if roof == "outdoors" else "techo abierto"
    p = hist.get(home)
    if p is None:
        return False, "al aire libre"
    if p >= 0.9:
        return True, "techo cerrado (el clima no afecta)"
    if p <= 0.1:
        return False, "al aire libre"
    return None, f"techo retráctil (cerrado en {p * 100:.0f} % de sus juegos recientes; se decide el día del partido)"


# ------------------------------------------------------------------------------------------ descarga
_RED_CAIDA = False        # si la descarga falla (sin internet / bloqueada) no se insiste con los demas estadios


def _descargar(lat: float, lon: float, log=print) -> dict | None:
    global _RED_CAIDA
    if _RED_CAIDA:
        return None
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": HOURLY, "temperature_unit": "fahrenheit",
         "wind_speed_unit": "mph", "precipitation_unit": "inch", "timezone": "UTC", "forecast_days": MAX_DIAS + 1}
    url = URL + "?" + urllib.parse.urlencode(q, safe=",")
    ultimo = None
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "modelo-nfl-personal"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as ex:        # red inestable: reintentar
            ultimo = ex
            time.sleep(1.5 * (intento + 1))
    log(f"  [aviso] no pude bajar el clima ({ultimo}); no insisto con los demás estadios")
    _RED_CAIDA = True
    return None


def ventana(j: dict, kick: pd.Timestamp, horas: int = HORAS_PARTIDO) -> dict | None:
    """Resume el pronostico en la ventana [kickoff, kickoff + horas]."""
    h = (j or {}).get("hourly")
    if not h or not h.get("time"):
        return None
    t = pd.to_datetime(pd.Series(h["time"])).dt.tz_localize("UTC")
    ini = kick.floor("h")
    m = ((t >= ini) & (t <= ini + pd.Timedelta(hours=horas))).values
    if not m.any():
        return None
    col = lambda k: np.array([np.nan if v is None else v for v in h.get(k, [None] * len(t))], float)[m]
    temp, vto, raf, pp, pr, cod = (col("temperature_2m"), col("wind_speed_10m"), col("wind_gusts_10m"),
                                   col("precipitation_probability"), col("precipitation"), col("weather_code"))
    sev, tx = max((_texto_clima(int(c)) for c in cod if not np.isnan(c)), default=(0, "sin dato"))
    f = lambda x, fn: None if np.all(np.isnan(x)) else round(float(fn(x)), 1)
    return {"temp_f": f(temp, np.nanmean), "viento_mph": f(vto, np.nanmean), "rafaga_mph": f(raf, np.nanmax),
            "prob_precip": f(pp, np.nanmax), "precip_in": f(pr, np.nansum), "clima": tx, "severidad": sev}


def pronostico(games: pd.DataFrame, pend: pd.DataFrame, log=print, descargar=None) -> dict:
    """{game_id: info} para los partidos pendientes. `descargar` se puede cambiar para pruebas."""
    descargar = descargar or _descargar
    hist = techo_historial(games)
    ahora = pd.Timestamp.now(tz="UTC")
    cache, out = {}, {}
    for r in pend.itertuples():
        interior, techo_txt = clasificar_techo(getattr(r, "roof", None), r.home_team, hist)
        kick = kickoff_utc(r.gameday, getattr(r, "gametime", None))
        dias = (kick - ahora).total_seconds() / 86400
        info = {"game_id": r.game_id, "interior": interior, "techo": techo_txt, "kickoff_utc": kick.strftime("%Y-%m-%d %H:%M"),
                "dias": round(dias, 1), "estado": "ok", "aproximada": False}
        co = coordenadas(r.home_team, getattr(r, "stadium", None), getattr(r, "location", None))
        if co is None:
            info["estado"] = "sin_estadio"
        elif dias > MAX_DIAS:
            info["estado"] = "muy_lejos"
        else:
            info["aproximada"] = co[2]
            k = (round(co[0], 3), round(co[1], 3))
            if k not in cache:
                cache[k] = descargar(co[0], co[1], log)
            w = ventana(cache[k], kick)
            if w is None:
                info["estado"] = "sin_pronostico"
            else:
                info.update(w)
        out[r.game_id] = info
    return out


# ------------------------------------------------------------------------------------------ base de datos
def guardar(info: dict, log=print) -> None:
    """Una foto por corrida: asi se puede medir despues que tan bien acerto el pronostico."""
    filas = [{**v, "capturado": None, "fuente": "open-meteo"} for v in info.values() if v.get("estado") == "ok"]
    if not filas:
        return
    try:
        import db
        df = pd.DataFrame(filas)
        df["capturado"] = db._ahora()
        for c in ("interior",):
            df[c] = df[c].map({True: 1, False: 0}).astype("Float64")
        db.agregar_foto("clima_pronostico", df)
        db.marcar_descarga("clima_pronostico", len(df), "Open-Meteo")
    except Exception as ex:
        log(f"  [aviso] no pude guardar el pronóstico del clima ({ex})")


def ultimo_guardado(game_ids, horas_max: float = 48.0) -> dict:
    """Ultima foto guardada (si no hay internet): {game_id: info}, con la antiguedad en horas."""
    try:
        import db
        con = db._con()
        try:
            if not db._existe(con, "clima_pronostico"):
                return {}
            d = pd.read_sql("SELECT * FROM clima_pronostico", con)
        finally:
            con.close()
    except Exception:
        return {}
    d = d[d.game_id.isin(list(game_ids))].sort_values("capturado").groupby("game_id").tail(1)
    ahora = pd.Timestamp.now(tz="UTC")
    out = {}
    for r in d.to_dict("records"):
        edad = (ahora - pd.Timestamp(r["capturado"], tz="UTC")).total_seconds() / 3600
        if edad <= horas_max:
            r["interior"] = None if pd.isna(r.get("interior")) else bool(r["interior"])
            r["estado"], r["edad_h"] = "ok", round(edad, 1)
            out[r["game_id"]] = r
    return out


def obtener(games: pd.DataFrame, semanas: int = 2, log=print, descargar=None) -> dict:
    """Pronostico de los partidos pendientes de la semana en curso y la siguiente (con respaldo si falla la descarga)."""
    pend = games[games.result.isna() & (games.season == games.loc[games.result.notna(), "season"].max())]
    if pend.empty:
        return {}
    wk0 = int(pend.week.min())
    pend = pend[pend.week < wk0 + semanas].sort_values(["gameday", "game_id"])
    info = pronostico(games, pend, log, descargar)
    malos = [g for g, v in info.items() if v["estado"] == "sin_pronostico"]
    if malos:
        resp = ultimo_guardado(malos)
        for g, v in resp.items():
            base = info[g]
            info[g] = {**v, "interior": base["interior"], "techo": base["techo"], "dias": base["dias"]}
        log(f"  Clima: {len(malos) - len(resp)} partido(s) sin pronóstico (sin internet o sin dato)" if len(malos) > len(resp) else
            f"  Clima: usé la última foto guardada para {len(resp)} partido(s)")
    guardar({g: v for g, v in info.items() if "edad_h" not in v}, log)
    return info


# ------------------------------------------------------------------------------------------ para el modelo
def preparar_modelo(games: pd.DataFrame, info: dict) -> pd.DataFrame:
    """Rellena techo, temperatura y viento de los partidos pendientes (solo donde la liga aun no tiene dato)."""
    g = games.copy()
    hist = techo_historial(g)
    pend = g.result.isna()
    # techo: si falta, el mas probable segun el historial del estadio
    falta = pend & g.roof.isna()
    for i in g.index[falta]:
        p = hist.get(g.at[i, "home_team"])
        if p is not None:
            g.at[i, "roof"] = "closed" if p >= 0.5 else "outdoors"
    for i in g.index[pend]:
        v = info.get(g.at[i, "game_id"])
        if not v or v.get("estado") != "ok":
            continue
        if pd.isna(g.at[i, "temp"]) and v.get("temp_f") is not None:
            g.at[i, "temp"] = v["temp_f"]
        if pd.isna(g.at[i, "wind"]) and v.get("viento_mph") is not None:
            g.at[i, "wind"] = min(v["viento_mph"], 20.0)   # topa en 20 mph: mas alla casi no hay historial
    return g


# ------------------------------------------------------------------------------------------ presentacion
def etiquetas(v: dict | None) -> tuple[str, str]:
    """(html con el clima, nota corta). Devuelve texto vacio si no hay informacion."""
    if not v:
        return "", ""
    if v.get("estado") not in ("ok",):
        msg = {"muy_lejos": "el pronóstico todavía no existe (faltan más de 15 días)", "sin_estadio": "no tengo las coordenadas de este estadio",
               "sin_pronostico": "no pude obtener el pronóstico"}.get(v.get("estado"), "sin pronóstico")
        return f'<span class="pw pw-n">Clima: {msg}</span>', ""
    chips = []
    if v.get("interior") is True:
        return f'<span class="pw pw-i">🏟 {v["techo"]}</span>', ""
    t, w, r = v.get("temp_f"), v.get("viento_mph"), v.get("rafaga_mph")
    if t is not None:
        chips.append(f'<span class="pw {"pw-a" if t <= FRIO else ""}">🌡 {(t - 32) * 5 / 9:.0f} °C ({t:.0f} °F)</span>')
    if w is not None:
        extra = f" · ráfagas {r:.0f}" if r is not None and r - w >= 6 else ""
        chips.append(f'<span class="pw {"pw-a" if w >= VIENTO_FUERTE else ""}">💨 {w:.0f} mph{extra}</span>')
    pp, pr = v.get("prob_precip"), v.get("precip_in") or 0
    if pp is not None and (pp >= 20 or pr > 0.01):
        chips.append(f'<span class="pw {"pw-a" if pp >= 50 else ""}">💧 {pp:.0f} % de lluvia/nieve{f" · {pr:.2f} in" if pr >= 0.05 else ""}</span>')
    chips.append(f'<span class="pw">{v.get("clima", "")}</span>')
    if v.get("interior") is None:
        chips.append('<span class="pw pw-n">techo retráctil</span>')
    elif v.get("techo") == "techo abierto":
        chips.append('<span class="pw pw-n">techo abierto</span>')
    nota = []
    d = v.get("dias")
    if d is not None and d > 5:
        nota.append(f"faltan {d:.0f} días: el pronóstico todavía puede cambiar mucho")
    if v.get("edad_h") is not None:
        nota.append(f"foto guardada hace {v['edad_h']:.0f} h (no pude actualizarla)")
    if v.get("aproximada"):
        nota.append("ubicación aproximada")
    return "".join(chips), "; ".join(nota)


CSS = """
.pwx{margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.pw{background:var(--no);border-radius:999px;padding:2px 9px;font-size:.78rem;white-space:nowrap}
.pw-a{background:#fde7c8;color:#7a3d00;font-weight:600}.pw-i{background:var(--yes);color:var(--yesink)}.pw-n{color:var(--ink2)}
@media (prefers-color-scheme:dark){.pw-a{background:#4a3315;color:#ffd9a0}}
.pwn{color:var(--ink2);font-size:.78rem;margin:0 0 4px}
"""
