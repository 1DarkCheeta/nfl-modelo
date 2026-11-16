"""Exploracion de la API PUBLICA de Kalshi (solo lectura, sin login) para ver como publica props de la NFL.
Guarda el resultado en outputs/kalshi_exploracion.txt"""
import json, time, urllib.parse, urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "outputs" / "kalshi_exploracion.txt"
BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
lineas = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lineas.append(s)


def get(ruta, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    ultimo = None
    for b in BASES:
        try:
            req = urllib.request.Request(f"{b}{ruta}" + (f"?{q}" if q else ""), headers={"Accept": "application/json", "User-Agent": "modelo-nfl-personal/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            ultimo = e
    raise RuntimeError(f"no pude leer {ruta}: {ultimo}")


try:
    s = get("/series", category="Sports")
    series = s.get("series", [])
    log("series deportes:", len(series))
    nfl = [x for x in series if any(k in (x.get("ticker", "") + " " + x.get("title", "")).lower() for k in ("nfl", "football"))]
    log("series NFL/football:", len(nfl))
    for x in nfl:
        log("  ", x.get("ticker"), "|", x.get("title"), "|", x.get("frequency"))
    props = [x for x in nfl if any(k in (x.get("ticker", "") + x.get("title", "")).lower() for k in ("yard", "yd", "td", "touchdown", "reception", "rush", "pass", "rec"))]
    log("--- series candidatas a props:", [x["ticker"] for x in props])
    for x in props[:14]:
        time.sleep(0.4)
        m = get("/markets", series_ticker=x["ticker"], status="open", limit=5)
        mk = m.get("markets", [])
        log(f"== {x['ticker']}: {len(mk)} mercados abiertos (muestra)")
        for k in mk[:3]:
            log(json.dumps({c: k.get(c) for c in ("ticker", "event_ticker", "title", "yes_sub_title", "subtitle", "strike_type", "floor_strike", "cap_strike",
                                                   "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "yes_bid", "yes_ask", "last_price", "volume", "open_interest", "close_time", "custom_strike")
                            if k.get(c) is not None}, ensure_ascii=False))
except Exception as e:
    log("ERROR:", e)
SALIDA.parent.mkdir(exist_ok=True)
SALIDA.write_text("\n".join(lineas), encoding="utf-8")
print("Guardado en", SALIDA)
