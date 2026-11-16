"""Segunda exploracion (solo lectura) de series de props NFL de Kalshi. Guarda outputs/kalshi_exploracion2.txt"""
import json, time, urllib.parse, urllib.request
from pathlib import Path
AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "outputs" / "kalshi_exploracion2.txt"
BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
out = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)
def get(ruta, **p):
    q = urllib.parse.urlencode({k: v for k, v in p.items() if v is not None}); err = None
    for b in BASES:
        try:
            req = urllib.request.Request(f"{b}{ruta}?{q}", headers={"Accept": "application/json", "User-Agent": "modelo-nfl-personal/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            err = e
    raise RuntimeError(str(err))
def todos(serie):
    res, cur = [], None
    for _ in range(30):
        d = get("/markets", series_ticker=serie, status="open", limit=1000, cursor=cur)
        res += d.get("markets", []); cur = d.get("cursor")
        if not cur: break
        time.sleep(0.3)
    return res
for s in ["KXNFLANYTD", "KXNFLTD", "KXNFL2TD", "KXNFLFIRSTTD", "KXNFLPASSYDS", "KXNFLPASSCOMP", "KXNFLPASSATT", "KXNFLPASSTDS", "KXNFLRSHYDS", "KXNFLRSHATT", "KXNFLRECYDS", "KXNFLREC", "KXNFLPASSINT"]:
    try:
        mk = todos(s)
        ev = sorted({m["event_ticker"] for m in mk})
        log(f"== {s}: {len(mk)} mercados abiertos, {len(ev)} eventos: {ev[:20]}")
        if mk:
            m = mk[0]
            log(json.dumps({k: m.get(k) for k in ("ticker", "title", "yes_sub_title", "strike_type", "floor_strike", "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "volume_fp", "liquidity_dollars", "rules_primary", "expiration_time", "expected_expiration_time")}, ensure_ascii=False))
            # ejemplo de escalera de un jugador
            p = m["yes_sub_title"].split(":")[0]
            esc = [(x.get("floor_strike"), x.get("yes_bid_dollars"), x.get("yes_ask_dollars")) for x in mk if x["yes_sub_title"].startswith(p + ":") and x["event_ticker"] == m["event_ticker"]]
            log("   escalera", p, sorted(esc, key=lambda t: (t[0] is None, t[0])))
    except Exception as e:
        log("ERROR", s, e)
    time.sleep(0.4)
SALIDA.write_text("\n".join(out), encoding="utf-8"); print("Guardado", SALIDA)
