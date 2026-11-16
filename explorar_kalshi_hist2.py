"""Exploracion unica (2): ¿cuanto historial de props hay en Kalshi y desde cuando se puede operar cada mercado?
Escribe outputs/kalshi_hist_exploracion2.txt"""
import json, time, urllib.request, urllib.parse, pathlib, datetime, collections, re
import statistics as st

OUT = pathlib.Path(__file__).parent / "outputs"
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
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    raise RuntimeError(err)


def iso(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def todos(ruta, serie, tope=40, **extra):
    out, cur = [], None
    for _ in range(tope):
        q = dict(series_ticker=serie, limit=1000, **extra)
        if cur:
            q["cursor"] = cur
        j = get(ruta, **q)
        out += j.get("markets", [])
        cur = j.get("cursor")
        if not cur:
            break
    return out


def resumen(nombre, ms):
    log(f"== {nombre}: {len(ms)} mercados")
    por_mes = collections.Counter(re.sub(r"^[A-Z]+-(\d\d[A-Z]{3}).*", r"\1", m["event_ticker"]) for m in ms)
    log("  por mes de evento:", dict(sorted(por_mes.items())))
    con_vol = [m for m in ms if float(m.get("volume_fp") or 0) > 0]
    log(f"  con volumen > 0: {len(con_vol)}")
    dur = []
    for m in con_vol:
        try:
            dur.append((iso(m["close_time"]) - iso(m["open_time"])).total_seconds() / 3600)
        except Exception:
            pass
    if dur:
        dur.sort()
        log(f"  horas entre apertura y cierre: mediana {st.median(dur):.1f}, p10 {dur[len(dur)//10]:.1f}, p90 {dur[9*len(dur)//10]:.1f}, "
            f"con >=24 h: {sum(d >= 24 for d in dur)} de {len(dur)}")
    return con_vol


try:
    ms_h = todos("/historical/markets", "KXNFLRECYDS")
    cv = resumen("historical KXNFLRECYDS", ms_h)
except Exception as e:
    log("[FALLA] historical:", e)
    ms_h, cv = [], []
try:
    ms_r = todos("/markets", "KXNFLRECYDS", status="settled")
    cv2 = resumen("settled (recientes) KXNFLRECYDS", ms_r)
except Exception as e:
    log("[FALLA] settled:", e)
    ms_r, cv2 = [], []

# velas de 6 mercados «tipicos» (con volumen y apertura temprana) para ver desde cuando hay precio antes del partido
muestras = []
for ms in (cv, cv2):
    tempranos = [m for m in ms if (iso(m["close_time"]) - iso(m["open_time"])).total_seconds() >= 24 * 3600]
    muestras += tempranos[:3] + tempranos[len(tempranos) // 2:len(tempranos) // 2 + 1] if tempranos else []
for m in muestras[:8]:
    t = m["ticker"]
    serie = t.split("-")[0]
    a, b = int(iso(m["open_time"]).timestamp()), int(iso(m["close_time"]).timestamp())
    try:
        j = get(f"/series/{serie}/markets/{t}/candlesticks", start_ts=a, end_ts=b, period_interval=60)
        c = j.get("candlesticks", [])
        con_p = [x for x in c if x.get("yes_bid", {}).get("close_dollars") and x.get("yes_ask", {}).get("close_dollars")]
        log(f"{t} abre {m['open_time']} cierra {m['close_time']} vol={m.get('volume_fp')} resultado={m.get('result')} velas={len(c)} con bid/ask={len(con_p)}")
        if con_p:
            f, u = con_p[0], con_p[-1]
            log("   primera:", datetime.datetime.fromtimestamp(f["end_period_ts"], datetime.timezone.utc).isoformat(), f["yes_bid"]["close_dollars"], f["yes_ask"]["close_dollars"])
            log("   ultima :", datetime.datetime.fromtimestamp(u["end_period_ts"], datetime.timezone.utc).isoformat(), u["yes_bid"]["close_dollars"], u["yes_ask"]["close_dollars"])
    except Exception as e:
        log(f"[FALLA] velas {t}: {e}")
    time.sleep(0.3)

(OUT / "kalshi_hist_exploracion2.txt").write_text("\n".join(L), encoding="utf8")
log("Listo -> outputs/kalshi_hist_exploracion2.txt")
