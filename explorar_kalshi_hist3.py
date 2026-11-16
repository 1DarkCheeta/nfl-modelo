import json, pathlib, sys, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lineas_casas as LC
out, cur, x = [], None, []
for p in range(20):
    q = {"series_ticker": "KXNFLRECYDS", "limit": 1000}
    if cur:
        q["cursor"] = cur
    j = LC._get(LC.KALSHI_BASES, "/historical/markets", q)
    x += [m for m in j["markets"] if m["event_ticker"].startswith("KXNFLRECYDS-25")]
    cur = j.get("cursor")
    if x or not cur:
        break
out.append(f"paginas {p + 1}, mercados de 2025 en ellas: {len(x)}")
if x:
    m = x[0]
    out.append(json.dumps({k: m.get(k) for k in ("ticker", "event_ticker", "strike_type", "floor_strike", "cap_strike", "result", "status", "yes_sub_title", "open_time", "close_time", "volume_fp", "market_type")}))
    out.append(str(collections.Counter((m.get("strike_type"), m.get("result"), m.get("status")) for m in x)))
pathlib.Path(__file__).resolve().parent.joinpath("outputs", "kalshi_hist3.txt").write_text("\n".join(out), encoding="utf8")
print("\n".join(out))
