"""Exploracion unica: ¿se pueden bajar de Kalshi los precios historicos (mercados ya liquidados) de props NFL?
Escribe outputs/kalshi_hist_exploracion.txt"""
import json, time, urllib.request, urllib.parse, pathlib, datetime

OUT = pathlib.Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)
BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
L = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    L.append(s)


def get(path, **q):
    err = None
    for b in BASES:
        url = b + path + ("?" + urllib.parse.urlencode(q) if q else "")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (modelo nfl personal)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:
            err = f"{type(e).__name__}: {e} ({url})"
    raise RuntimeError(err)


log("Corrida:", datetime.datetime.now().isoformat(timespec="seconds"))

# 1) corte entre datos «vivos» e historicos
for p in ("/historical/cutoff",):
    try:
        log("[OK]", p, json.dumps(get(p))[:400])
    except Exception as e:
        log("[FALLA]", p, e)

# 2) mercados liquidados de una serie
muestra = None
for serie in ("KXNFLRECYDS", "KXNFLTD", "KXNFLPASSYDS"):
    for ruta, q in (("/markets", dict(series_ticker=serie, status="settled", limit=200)),
                    ("/historical/markets", dict(series_ticker=serie, limit=200))):
        try:
            j = get(ruta, **q)
            ms = j.get("markets", [])
            ev = sorted({m["event_ticker"] for m in ms})
            log(f"[OK] {ruta} {serie}: {len(ms)} mercados, cursor={'si' if j.get('cursor') else 'no'}; eventos: {ev[:3]} ... {ev[-2:]}")
            if ms and muestra is None:
                muestra = ms[0]
                log("  campos:", sorted(muestra.keys()))
                log("  muestra:", json.dumps({k: muestra[k] for k in muestra if k in (
                    "ticker", "event_ticker", "status", "result", "yes_sub_title", "floor_strike", "open_time", "close_time",
                    "expiration_time", "last_price_dollars", "previous_price_dollars", "yes_bid_dollars", "yes_ask_dollars",
                    "volume_fp", "settlement_value_dollars", "expiration_value", "can_close_early")}, ensure_ascii=False))
        except Exception as e:
            log(f"[FALLA] {ruta} {serie}: {e}")

# 3) historial de precios (velas) de un mercado liquidado
if muestra:
    t = muestra["ticker"]
    serie = muestra.get("series_ticker") or t.split("-")[0]
    iso = lambda s: int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    try:
        ini, fin = iso(muestra["open_time"]), iso(muestra["close_time"])
    except Exception:
        ini, fin = int(time.time()) - 86400 * 30, int(time.time())
    for ruta in (f"/series/{serie}/markets/{t}/candlesticks", f"/historical/markets/{t}/candlesticks"):
        try:
            j = get(ruta, start_ts=ini, end_ts=fin, period_interval=60)
            c = j.get("candlesticks", [])
            log(f"[OK] {ruta}: {len(c)} velas")
            if c:
                log("  primera:", json.dumps(c[0])[:500])
                log("  ultima:", json.dumps(c[-1])[:500])
        except Exception as e:
            log(f"[FALLA] {ruta}: {e}")
    # 4) trades historicos
    try:
        j = get("/markets/trades", ticker=t, limit=20)
        tr = j.get("trades", [])
        log(f"[OK] /markets/trades {t}: {len(tr)}", json.dumps(tr[:2])[:400])
    except Exception as e:
        log(f"[FALLA] /markets/trades: {e}")

(OUT / "kalshi_hist_exploracion.txt").write_text("\n".join(L), encoding="utf8")
log("Listo -> outputs/kalshi_hist_exploracion.txt")
