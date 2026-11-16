"""Lineas de props tomadas AUTOMATICAMENTE de casas / mercados y comparadas con el modelo.

Fuentes
  * Kalshi (API publica de solo lectura, sin cuenta ni llave): para cada jugador publica una «escalera»
    (p. ej. 40+, 50+, 60+ ... yardas) con precio de compra (bid) y de venta (ask) del contrato «Si».
    El precio es una probabilidad: 0.40 = 40 %. Comprar «Si» cuesta el ask; comprar «No» cuesta 1 - bid.
    Kalshi cobra una comision aprox. 0.07 * precio * (1 - precio) por contrato; se descuenta de la ventaja.
  * DraftKings (y otras casas) SOLO a traves de The Odds API (servicio oficial de cuotas; necesita TU llave
    gratuita en data/odds_api_key.txt). DraftKings no tiene API publica y no se «raspa» su pagina.
    Esta parte esta escrita segun la documentacion pero no pude probarla con datos reales.

Todo se guarda en la tabla `lineas_casas` de la base (una foto por fuente y dia).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

import db
from data import DATA, norm_team
from fuentes_web import nombre_norm

KALSHI_BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
KALSHI_SERIES = {"KXNFLPASSYDS": "pass_yds", "KXNFLPASSCOMP": "pass_cmp", "KXNFLPASSTDS": "pass_td", "KXNFLPASSINT": "pass_int",
                 "KXNFLRSHYDS": "rush_yds", "KXNFLRSHATT": "rush_att", "KXNFLRECYDS": "rec_yds", "KXNFLREC": "rec", "KXNFLTD": "td"}
KALSHI_EQUIPOS = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAC", "JAX", "KC",
                  "LAC", "LAR", "LA", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "WSH"}
MESES = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
COMISION_KALSHI = 0.07
PESO_MODELO = 0.20       # peso del modelo al mezclar con el precio de Kalshi (medido en validacion cruzada; mas peso empeora; ver evaluar_mercado.py)
PESO_MODELO_TIERRA = 0.10  # en acarreos y yardas por tierra el modelo sigue por debajo del precio: menos peso
DISCREPANCIA = 0.10      # diferencia mediana modelo-mercado a partir de la cual se trata como «el mercado sabe algo distinto»
ODDS_API = "https://api.the-odds-api.com/v4"
ODDS_MERCADOS = {"player_pass_yds": "pass_yds", "player_pass_completions": "pass_cmp", "player_pass_tds": "pass_td",
                 "player_pass_interceptions": "pass_int", "player_rush_yds": "rush_yds", "player_rush_attempts": "rush_att",
                 "player_reception_yds": "rec_yds", "player_receptions": "rec", "player_anytime_td": "td"}
COLS = ["capturado", "fuente", "serie", "mercado", "jugador", "equipo", "partido", "fecha_juego", "umbral", "linea",
        "bid", "ask", "last", "volumen", "comision"]


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _get(base_list, ruta, params=None, intentos=3):
    q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    ultimo = None
    for b in base_list:
        for i in range(intentos):
            try:
                req = urllib.request.Request(f"{b}{ruta}" + (f"?{q}" if q else ""),
                                             headers={"Accept": "application/json", "User-Agent": "modelo-nfl-personal/1.0"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                ultimo = e
                time.sleep(1.0 + i)
    raise RuntimeError(f"no pude leer {ruta}: {ultimo}")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _partir_equipos(s: str):
    """'NYJKC' -> ('NYJ','KC'); 'LARWAS' -> ('LAR','WAS'). Devuelve None si no se puede separar."""
    for n in (3, 2):
        a, b = s[:n], s[n:]
        if a in KALSHI_EQUIPOS and b in KALSHI_EQUIPOS:
            return a, b
    return None


def _norm_equipo(c: str) -> str:
    return {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}.get(c, c)


def parsear_kalshi(mercados: list[dict], serie: str, capturado: str) -> pd.DataFrame:
    """Convierte los mercados de una serie de Kalshi en filas (una por escalon de la escalera de cada jugador)."""
    filas = []
    for m in mercados:
        try:
            ev = m["event_ticker"].split("-")[-1]                       # '26NOV08GBNE'
            mm = re.match(r"(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$", ev)
            fecha = f"20{mm.group(1)}-{MESES[mm.group(2)]:02d}-{mm.group(3)}"
            eq = _partir_equipos(mm.group(4))
            if not eq or m.get("floor_strike") is None or m.get("strike_type") != "greater":
                continue
            resto = m["ticker"].split("-")[2]                            # 'GBSWILLIAMS83'
            propio = next((t for t in eq if resto.startswith(t)), None)
            nombre = m["yes_sub_title"].split(":")[0].strip()
            filas.append({"capturado": capturado, "fuente": "kalshi", "serie": serie, "mercado": KALSHI_SERIES[serie], "jugador": nombre,
                          "equipo": _norm_equipo(propio) if propio else "", "partido": "-".join(_norm_equipo(t) for t in eq),
                          "fecha_juego": fecha, "umbral": float(m["floor_strike"]) + 0.5, "linea": float(m["floor_strike"]),
                          "bid": _f(m.get("yes_bid_dollars")), "ask": _f(m.get("yes_ask_dollars")), "last": _f(m.get("last_price_dollars")),
                          "volumen": _f(m.get("volume_fp")), "comision": COMISION_KALSHI})
        except Exception:
            continue
    return pd.DataFrame(filas, columns=COLS)


def descargar_kalshi(log=print) -> pd.DataFrame:
    cap, out = _ahora(), []
    for serie in KALSHI_SERIES:
        cursor, mk = None, []
        for _ in range(20):
            d = _get(KALSHI_BASES, "/markets", {"series_ticker": serie, "status": "open", "limit": 1000, "cursor": cursor})
            mk += d.get("markets", [])
            cursor = d.get("cursor")
            if not cursor:
                break
        out.append(parsear_kalshi(mk, serie, cap))
        time.sleep(0.3)
    df = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLS)
    log(f"  Kalshi: {len(df)} escalones de {df.jugador.nunique()} jugadores en {df.partido.nunique()} partidos")
    return df


# ---------------------------------------------------------------- The Odds API (DraftKings, FanDuel, ...)
def _amer_a_prob(o: float) -> float:
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def parsear_oddsapi(evento: dict, datos: dict, capturado: str) -> pd.DataFrame:
    """Una linea over/under por jugador y casa: ask = prob. implicita del Over, bid = 1 - prob. implicita del Under."""
    filas = []
    home, away = norm_team(pd.Series([evento.get("home_team", "")])).iloc[0], evento.get("away_team", "")
    fecha = str(evento.get("commence_time", ""))[:10]
    for casa in datos.get("bookmakers", []):
        for mk in casa.get("markets", []):
            merc = ODDS_MERCADOS.get(mk.get("key"))
            if not merc:
                continue
            por_jug = {}
            for o in mk.get("outcomes", []):
                por_jug.setdefault((o.get("description"), o.get("point")), {})[str(o.get("name")).lower()] = o.get("price")
            for (jug, pt), pr in por_jug.items():
                if not jug:
                    continue
                ov = pr.get("over", pr.get("yes"))
                un = pr.get("under")
                if ov is None:
                    continue
                ask = _amer_a_prob(float(ov))
                bid = 1 - _amer_a_prob(float(un)) if un is not None else np.nan
                linea = 0.5 if merc == "td" else float(pt)
                filas.append({"capturado": capturado, "fuente": casa.get("key", "casa"), "serie": mk.get("key"), "mercado": merc, "jugador": jug,
                              "equipo": "", "partido": f"{evento.get('away_team', '')}@{evento.get('home_team', '')}", "fecha_juego": fecha,
                              "umbral": linea + 0.5, "linea": linea, "bid": bid, "ask": ask, "last": np.nan, "volumen": np.nan, "comision": 0.0})
    return pd.DataFrame(filas, columns=COLS)


def descargar_oddsapi(llave: str, casas="draftkings", log=print) -> pd.DataFrame:
    cap, out = _ahora(), []
    evs = _get([ODDS_API], "/sports/americanfootball_nfl/events", {"apiKey": llave})
    hoy = dt.datetime.now(dt.timezone.utc)
    for e in evs:
        try:
            if dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) < hoy:
                continue                                                # partido ya empezado
            d = _get([ODDS_API], f"/sports/americanfootball_nfl/events/{e['id']}/odds",
                     {"apiKey": llave, "regions": "us", "markets": ",".join(ODDS_MERCADOS), "oddsFormat": "american", "bookmakers": casas})
            out.append(parsear_oddsapi(e, d, cap))
        except Exception as ex:
            log(f"  [aviso] The Odds API: no pude leer un partido ({ex})")
    df = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLS)
    log(f"  The Odds API ({casas}): {len(df)} lineas de {df.jugador.nunique()} jugadores")
    return df


# ---------------------------------------------------------------- guardado y lectura
def _llave_oddsapi():
    p = DATA / "odds_api_key.txt"
    return p.read_text().strip() if p.exists() and p.read_text().strip() else None


def cargar(refresh: bool = True, log=print, max_horas: float = 0.5) -> pd.DataFrame:
    """Ultima foto de cada fuente (la baja si tiene mas de `max_horas`; sin internet usa la guardada)."""
    fuentes = [("kalshi", lambda: descargar_kalshi(log))]
    llave = _llave_oddsapi()
    if llave:
        fuentes.append(("oddsapi", lambda: descargar_oddsapi(llave, log=log)))
    for nombre, fn in fuentes:
        if refresh and db.horas_desde(f"lineas_{nombre}") > max_horas:
            try:
                df = fn()
                if len(df):
                    db.agregar_foto("lineas_casas", df)
                    db.marcar_descarga(f"lineas_{nombre}", len(df), nombre)
            except Exception as e:
                log(f"  [aviso] no pude actualizar las lineas de {nombre} ({e}); uso la ultima foto guardada")
    if not db.hay("lineas_casas"):
        return pd.DataFrame(columns=COLS)
    d = db.consulta("SELECT * FROM lineas_casas WHERE capturado = (SELECT MAX(capturado) FROM lineas_casas l WHERE l.fuente = lineas_casas.fuente)")
    return d


# ---------------------------------------------------------------- comparacion con el modelo
def _p_modelo(r) -> float:
    """P(el jugador llega al umbral) segun el modelo. Para tocar el promedio reciente se usa el factor de calibracion del mercado."""
    from props import nb_pn
    from scipy.stats import nbinom
    if r.market == "td":
        return float(r.p_td) if r.linea == 0.5 else np.nan             # solo «1+ TD»
    mu = max(r.base + r.s_cal * (r.mu - r.base), 1e-3)
    n, p = nb_pn(mu, r.phi)
    return float(1 - nbinom.cdf(np.floor(r.linea), n, p))


def comparar(P: pd.DataFrame, L: pd.DataFrame, max_spread: float = 0.10) -> pd.DataFrame:
    """Une cada escalon de la casa con la proyeccion del jugador y calcula la ventaja neta (descontada la comision)."""
    if L is None or L.empty or P is None or P.empty:
        return pd.DataFrame()
    P = P.copy().reset_index(drop=True)
    P["k"] = [nombre_norm(n) for n in P["name"]]
    idx = {(k, t, m): i for i, (k, t, m) in enumerate(zip(P.k, P.team, P.market))}
    unico = {(k, m): g.index[0] for (k, m), g in P.groupby(["k", "market"]) if len(g) == 1}
    filas = []
    for r in L.itertuples():
        k = nombre_norm(r.jugador)
        i = idx.get((k, r.equipo, r.mercado)) if r.equipo else None
        if i is None:
            i = unico.get((k, r.mercado))
        if i is None:
            continue
        q = P.loc[i]
        if q.market == "td" and r.linea != 0.5:
            continue
        # el partido debe coincidir (evita confundir jugadores homonimos o semanas distintas)
        if r.partido and "-" in r.partido and not (q.team in r.partido.split("-") and q.opp in r.partido.split("-")):
            continue
        p = _p_modelo(_con_linea(q, r.linea))
        if np.isnan(p):
            continue
        pj = float(q.get("p_juega", 1.0)) if pd.notna(q.get("p_juega", 1.0)) else 1.0
        p = p * pj          # en Kalshi el «Si» pierde si el jugador no juega
        bid, ask, c = r.bid, r.ask, r.comision
        spread = (ask - bid) if not (np.isnan(ask) or np.isnan(bid)) else np.nan
        # comprar «Si» cuesta ask; comprar «No» cuesta 1 - bid
        yes_ok = (not np.isnan(ask)) and 0.02 <= ask <= 0.97 and (np.isnan(spread) or spread <= max_spread)
        no_ok = (not np.isnan(bid)) and 0.03 <= bid <= 0.98 and (np.isnan(spread) or spread <= max_spread)
        mid = (ask + bid) / 2 if not (np.isnan(ask) or np.isnan(bid)) else np.nan
        # la probabilidad «de trabajo» parte del precio del mercado y le da un peso pequeno al modelo
        w = PESO_MODELO_TIERRA if r.mercado in ("rush_yds", "rush_att") else PESO_MODELO
        pm = p if np.isnan(mid) else w * p + (1 - w) * mid
        e_yes = pm - ask - c * ask * (1 - ask) if yes_ok else np.nan
        e_no = bid - pm - c * bid * (1 - bid) if no_ok else np.nan
        e_yes_m = p - ask - c * ask * (1 - ask) if yes_ok else np.nan
        e_no_m = bid - p - c * bid * (1 - bid) if no_ok else np.nan
        mejor = np.nanmax([e_yes, e_no]) if (yes_ok or no_ok) else np.nan
        lado = "SI/OVER" if (yes_ok and (not no_ok or e_yes >= e_no)) else "NO/UNDER"
        filas.append({"fuente": r.fuente, "game_id": q.game_id, "player_id": q.player_id, "jugador": q["name"], "equipo": q.team, "rival": q.opp,
                      "mercado": r.mercado, "label": q.label, "umbral": r.umbral, "linea": r.linea, "bid": bid, "ask": ask,
                      "spread": spread, "comision": c, "p_juega": pj, "p_modelo": p, "p_mezcla": pm, "edge_modelo": np.nanmax([e_yes_m, e_no_m]) if (yes_ok or no_ok) else np.nan, "edge_yes": e_yes, "edge_no": e_no, "edge": mejor, "lado": lado,
                      "mu": q.mu, "capturado": r.capturado, "estado": q.estado, "practica": q.practica})
    V = pd.DataFrame(filas)
    if V.empty:
        return V
    # ¿el mercado ve algo muy distinto al modelo en TODO el jugador (titular, lesion, rol)? -> discrepancia de informacion
    mid = V[["bid", "ask"]].mean(axis=1)
    V["brecha"] = V.p_modelo - mid.fillna(V.ask)
    V["brecha_med"] = V.groupby(["player_id", "mercado"]).brecha.transform("median")
    V["discrepa"] = V.brecha_med.abs() >= DISCREPANCIA
    return V


def _con_linea(q: pd.Series, linea: float):
    q = q.copy()
    q["linea"] = linea
    return q


def _a_americana(costo: float) -> int:
    costo = min(max(float(costo), 0.02), 0.98)
    return int(round(-100 * costo / (1 - costo))) if costo >= 0.5 else int(round(100 * (1 - costo) / costo))


def linea_automatica(V: pd.DataFrame) -> dict:
    """Por jugador y mercado, el escalon cuyo precio queda mas cerca del 50 % (la «linea» de Kalshi) con cuotas
    americanas equivalentes (incluida la comision): {(player_id, mercado): dict(linea, over, under, fuente)}"""
    out = {}
    if V is None or V.empty:
        return out
    d = V[(V.mercado != "td") & V.ask.notna() & V.bid.notna() & (V.spread <= 0.10) & ~V.discrepa].copy()
    d["dist"] = ((d.ask + d.bid) / 2 - 0.5).abs()
    for (pid, m), g in d.sort_values("dist").groupby(["player_id", "mercado"]):
        r = g.iloc[0]
        if r.dist > 0.25:
            continue
        out[(pid, m)] = {"linea": r.linea, "over": _a_americana(r.ask + r.comision * r.ask * (1 - r.ask)),
                         "under": _a_americana((1 - r.bid) + r.comision * r.bid * (1 - r.bid)), "fuente": r.fuente}
    return out


def td_automatico(V: pd.DataFrame) -> dict:
    """{player_id: dict(over=cuota americana incluyendo comision, ask, fuente)} para «anotar 1+ TD»."""
    out = {}
    if V is None or V.empty:
        return out
    for r in V[(V.mercado == "td") & (V.linea == 0.5) & V.ask.notna() & ~V.discrepa].itertuples():
        if 0.02 <= r.ask <= 0.97:
            out[r.player_id] = {"over": _a_americana(r.ask + r.comision * r.ask * (1 - r.ask)), "ask": r.ask, "fuente": r.fuente}
    return out
