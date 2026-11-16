import json, pathlib, sys, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lineas_casas as LC
t = "KXNFLRECYDS-25DEC29LAATL-ATLDSILLS87-30"
iso = lambda s: int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
q = {"start_ts": iso("2025-12-29T20:00:00Z"), "end_ts": iso("2025-12-30T05:00:00Z"), "period_interval": 60}
out = []
for r in (f"/historical/markets/{t}/candlesticks", f"/series/KXNFLRECYDS/markets/{t}/candlesticks"):
    try:
        j = LC._get(LC.KALSHI_BASES[:1], r, q, intentos=2)
        c = j.get("candlesticks", [])
        out.append(f"[OK] {r}: {len(c)} velas; claves: {list(j.keys())}")
        for x in c[:2] + c[-3:]:
            out.append(json.dumps(x)[:600])
    except Exception as e:
        out.append(f"[FALLA] {r}: {e}")
pathlib.Path(__file__).resolve().parent.joinpath("outputs", "kalshi_hist4.txt").write_text("\n".join(out), encoding="utf8")
print("\n".join(out))
