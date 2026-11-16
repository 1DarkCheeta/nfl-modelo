"""Exploracion unica: que fuentes de lesiones se pueden leer desde esta computadora. Escribe outputs/lesiones_exploracion.txt"""
import json, re, urllib.request, pathlib, datetime

OUT = pathlib.Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)
lineas = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lineas.append(s)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (modelo nfl personal)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


log("Corrida:", datetime.datetime.now().isoformat(timespec="seconds"))

# 1) ESPN JSON (la que usa su propia pagina)
for u in ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries",
          "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/injuries"]:
    try:
        st, b = get(u)
        j = json.loads(b)
        eq = j.get("injuries", [])
        n = sum(len(e.get("injuries", [])) for e in eq)
        log(f"[OK] {u}  status={st} bytes={len(b)} equipos={len(eq)} lesionados={n}")
        if eq and eq[0].get("injuries"):
            log("  claves equipo:", list(eq[0].keys()))
            log("  muestra:", json.dumps(eq[0]["injuries"][0], ensure_ascii=False)[:900])
        fechas = sorted({i.get("date", "")[:10] for e in eq for i in e.get("injuries", [])})
        log("  fechas (min/max):", fechas[:1], fechas[-1:])
        (OUT / "lesiones_espn_muestra.json").write_text(json.dumps(j, ensure_ascii=False)[:400000], encoding="utf8")
        break
    except Exception as e:
        log(f"[FALLA] {u}  {type(e).__name__}: {e}")

# 2) ESPN HTML por si el JSON no sirve
try:
    st, b = get("https://www.espn.com/nfl/injuries")
    t = b.decode("utf8", "ignore")
    log(f"[OK] espn.com/nfl/injuries status={st} bytes={len(b)} menciona 'Questionable'={t.count('Questionable')}")
except Exception as e:
    log(f"[FALLA] espn html {type(e).__name__}: {e}")

# 3) NFL.com
for u in ["https://www.nfl.com/injuries/", "https://www.nfl.com/injuries/league/2026/reg9"]:
    try:
        st, b = get(u)
        t = b.decode("utf8", "ignore")
        log(f"[OK] {u} status={st} bytes={len(b)} 'Questionable'={t.count('Questionable')} 'Doubtful'={t.count('Doubtful')}")
    except Exception as e:
        log(f"[FALLA] {u} {type(e).__name__}: {e}")

# 4) nflverse (lo que ya usa el modelo): cuantas filas de la semana mas reciente
try:
    import io, pandas as pd
    st, b = get("https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv")
    d = pd.read_csv(io.BytesIO(b))
    ult = d.week.max()
    x = d[d.week == ult]
    log(f"[OK] nflverse injuries_2026: semana mas reciente={ult} filas={len(x)}  report_status:",
        x.report_status.value_counts(dropna=False).to_dict())
    if "date_modified" in d.columns:
        log("  ultima modificacion:", d.date_modified.max())
except Exception as e:
    log(f"[FALLA] nflverse {type(e).__name__}: {e}")

(OUT / "lesiones_exploracion.txt").write_text("\n".join(lineas), encoding="utf8")
log("Listo -> outputs/lesiones_exploracion.txt")
