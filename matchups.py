"""Matchups ataque vs defensa: juego aereo y terrestre, yardas permitidas, presion y blitz.

Todo se calcula con la temporada en curso (peso 1) y la anterior (peso 0.5) y se encoge hacia el
promedio de la liga cuando hay pocas jugadas, para que 6 partidos no produzcan conclusiones locas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

K_EPA, K_SPLIT = 60.0, 40.0
PASS_T, RUSH_T = 0.04, 0.04          # EPA/jugada esperada que ya cuenta como ventaja
SUM_COLS = ["db", "epa_sum", "sacks", "pres_vis", "db_bl", "epa_bl", "db_nb", "epa_nb"]


def _shr(s, n, lg, k):
    return (s + k * lg) / (n + k)


def tablas_equipo(mg: pd.DataFrame, cur: int) -> dict:
    """Metricas de presion y blitz por equipo (ataque y defensa) y promedios de la liga."""
    m = mg[mg.season >= cur - 1].copy()
    m["w"] = np.where(m.season == cur, 1.0, 0.5)
    other = m[["game_id", "team", "db"]].rename(columns={"team": "opp", "db": "db_faced"})
    m = m.merge(other, on=["game_id", "opp"], how="left")
    has_pfr = m.pfr_pres_suf.notna() if "pfr_pres_suf" in m else pd.Series(False, index=m.index)
    m["db_pfr"] = np.where(has_pfr, m.db, 0)
    m["db_faced_pfr"] = np.where(has_pfr, m.db_faced.fillna(0), 0)
    for c in SUM_COLS + ["db_pfr", "db_faced_pfr"]:
        m[c + "_w"] = m[c] * m.w
    for c in ("pfr_pres_suf", "pfr_pres_gen"):
        m[c + "_w"] = (m[c].fillna(0) * m.w) if c in m else 0.0
    cols = [c + "_w" for c in SUM_COLS + ["db_pfr", "db_faced_pfr", "pfr_pres_suf", "pfr_pres_gen"]]
    off = m.groupby("team")[cols].sum()
    dfn = m.groupby("opp")[[c + "_w" for c in SUM_COLS]].sum()
    dfn_pfr = m.groupby("team")[["pfr_pres_gen_w", "db_faced_pfr_w"]].sum()   # presiones que genera la defensa de `team`

    L = {"epa": off.epa_sum_w.sum() / off.db_w.sum(),
         "epa_bl": off.epa_bl_w.sum() / max(off.db_bl_w.sum(), 1), "epa_nb": off.epa_nb_w.sum() / max(off.db_nb_w.sum(), 1),
         "blitz": off.db_bl_w.sum() / max(off.db_bl_w.sum() + off.db_nb_w.sum(), 1) * 100,
         "pres": off.pfr_pres_suf_w.sum() / max(off.db_pfr_w.sum(), 1) * 100,
         "sack": off.sacks_w.sum() / off.db_w.sum() * 100}
    ataque, defensa = {}, {}
    for t in off.index:
        o = off.loc[t]
        ataque[t] = {
            "epa": _shr(o.epa_sum_w, o.db_w, L["epa"], K_EPA),
            "epa_bl": _shr(o.epa_bl_w, o.db_bl_w, L["epa_bl"], K_SPLIT), "n_bl": o.db_bl_w,
            "epa_nb": _shr(o.epa_nb_w, o.db_nb_w, L["epa_nb"], K_SPLIT), "n_nb": o.db_nb_w,
            "blitz_faced": _shr(o.db_bl_w, o.db_bl_w + o.db_nb_w, L["blitz"] / 100, 80) * 100,
            "pres": (o.pfr_pres_suf_w / o.db_pfr_w * 100) if o.db_pfr_w > 20 else o.pres_vis_w / o.db_w * 100,
            "sack": o.sacks_w / o.db_w * 100}
    for t in dfn.index:
        d, p = dfn.loc[t], dfn_pfr.loc[t] if t in dfn_pfr.index else None
        defensa[t] = {
            "epa": _shr(d.epa_sum_w, d.db_w, L["epa"], K_EPA),
            "epa_bl": _shr(d.epa_bl_w, d.db_bl_w, L["epa_bl"], K_SPLIT), "n_bl": d.db_bl_w,
            "epa_nb": _shr(d.epa_nb_w, d.db_nb_w, L["epa_nb"], K_SPLIT),
            "blitz": _shr(d.db_bl_w, d.db_bl_w + d.db_nb_w, L["blitz"] / 100, 80) * 100,
            "pres": (p.pfr_pres_gen_w / p.db_faced_pfr_w * 100) if p is not None and p.db_faced_pfr_w > 20 else d.pres_vis_w / d.db_w * 100,
            "sack": d.sacks_w / d.db_w * 100}
    # Promedios de la liga para presion (defensa) por si difiere de la del ataque
    L["pres_gen"] = float(np.mean([v["pres"] for v in defensa.values()]))
    L["pres"] = float(np.mean([v["pres"] for v in ataque.values()]))
    return {"ataque": ataque, "defensa": defensa, "liga": L}


def _rank(vals: dict, t, best_high: bool) -> int:
    s = pd.Series(vals)
    return int(s.rank(ascending=not best_high, method="min")[t])


def ranks_recientes(tg: pd.DataFrame, games: pd.DataFrame, cur: int, ultimos: int = 4, pw: pd.DataFrame | None = None) -> dict:
    """Ranking REAL (1 = mejor) de EPA por jugada de pase/carrera, de ataque y de defensa, esta temporada y en los ultimos
    `ultimos` partidos de cada equipo. No pasa por los ratings del modelo (que tienen memoria larga a proposito)."""
    g = games[["game_id", "season"]].drop_duplicates("game_id")
    t = tg.merge(g, on="game_id", how="left")
    t = t[t.season == cur].copy()
    if t.empty:
        return {}
    t = t.merge(games[["game_id", "gameday"]].drop_duplicates("game_id"), on="game_id", how="left").sort_values(["team", "gameday"])
    t["n"] = t.groupby("team").cumcount(ascending=False)
    out = {}
    for ventana, d in (("t", t), ("u", t[t.n < ultimos])):
        for met in ("pass", "rush"):
            col = f"epa_{met}"
            of = d.groupby("team")[col].mean()                      # EPA que produce su ataque
            de = d.groupby("opp")[col].mean()                       # EPA que permite su defensa (menor = mejor)
            out[f"off_{met}_{ventana}"] = of.rank(ascending=False, method="min").astype(int).to_dict()
            out[f"def_{met}_{ventana}"] = de.rank(ascending=True, method="min").astype(int).to_dict()
    out["_n"] = int(min(ultimos, t.groupby("team").size().min()))
    if pw is not None and len(pw):                                   # yardas por partido del ataque (lo que se ve en las tablas de yardas)
        p = pw[pw.season == cur]
        for met in ("pass", "rush"):
            w = p.groupby(["team", "week"])[f"{met}_yds"].sum().reset_index().sort_values(["team", "week"])
            out[f"yds_{met}_t"] = w.groupby("team")[f"{met}_yds"].mean().rank(ascending=False, method="min").astype(int).to_dict()
            out[f"yds_{met}_u"] = w.groupby("team").tail(ultimos).groupby("team")[f"{met}_yds"].mean().rank(ascending=False, method="min").astype(int).to_dict()
    return out


def rank_tabla(T: dict, state: dict, defs: pd.DataFrame, rec: dict | None = None) -> dict:
    """Rankings 1-32 (1 = mejor) para cada metrica relevante."""
    A, D = T["ataque"], T["defensa"]
    off_pass = {t: v for t, v in state["off"]["pass"].items()}
    off_rush = {t: v for t, v in state["off"]["rush"].items()}
    def_pass = {t: v for t, v in state["dff"]["pass"].items()}
    def_rush = {t: v for t, v in state["dff"]["rush"].items()}
    dd = defs.set_index("team")
    rec = rec or {}
    def _rec(k):
        return lambda t: rec.get(k, {}).get(t)
    return {
        "rec": rec,
        "off_pass": lambda t: _rank(off_pass, t, True), "off_rush": lambda t: _rank(off_rush, t, True),
        "def_pass": lambda t: _rank(def_pass, t, False), "def_rush": lambda t: _rank(def_rush, t, False),
        "yds_pass": lambda t: _rank(dd.pase.to_dict(), t, False), "yds_rush": lambda t: _rank(dd.tierra.to_dict(), t, False),
        "off_pres": lambda t: _rank({k: v["pres"] for k, v in A.items()}, t, False),
        "def_pres": lambda t: _rank({k: v["pres"] for k, v in D.items()}, t, True),
        "off_blitz": lambda t: _rank({k: v["epa_bl"] - v["epa_nb"] for k, v in A.items()}, t, True),
        "def_blitz": lambda t: _rank({k: v["blitz"] for k, v in D.items()}, t, True),
    }


def _reciente(R: dict, key: str, of: str, de: str):
    """Ranking real (sin ratings del modelo) del ataque `of` y la defensa `de`: esta temporada y ultimos partidos."""
    rec = R.get("rec") or {}
    met = "pass" if key == "pass" else "rush"
    vals = {"at": rec.get(f"off_{met}_t", {}).get(of), "au": rec.get(f"off_{met}_u", {}).get(of),
            "dt": rec.get(f"def_{met}_t", {}).get(de), "du": rec.get(f"def_{met}_u", {}).get(de)}
    if not all(v is not None for v in vals.values()):
        return None
    vals["yt"], vals["yu"] = rec.get(f"yds_{met}_t", {}).get(of), rec.get(f"yds_{met}_u", {}).get(of)
    return vals


def _lado(of: str, de: str, state: dict, defs: pd.DataFrame, T: dict, R: dict) -> dict:
    """Lectura del ataque de `of` contra la defensa de `de`."""
    A, D, L = T["ataque"][of], T["defensa"][de], T["liga"]
    dd = defs.set_index("team")
    lg_pass = defs.pase.mean()
    lg_rush = defs.tierra.mean()
    items = []

    # --- juego aereo y terrestre (ratings ajustados por rival del modelo)
    for key, nm, thr, ro, rd in (("pass", "Juego aéreo", PASS_T, R["off_pass"], R["def_pass"]),
                                 ("rush", "Juego terrestre", RUSH_T, R["off_rush"], R["def_rush"])):
        o, d = state["off"][key][of], state["dff"][key][de]
        exp = o + d   # EPA/jugada esperada vs promedio
        v = "fav" if exp >= thr else "dif" if exp <= -thr else "neu"
        items.append({"tema": nm, "v": v, "ataque": f"{of}: ataque #{ro(of)} de 32", "defensa": f"{de}: defensa #{rd(de)} de 32",
                      "ra": ro(of), "rd": rd(de),
                      "reciente": _reciente(R, key, of, de),
                      "nota": ("Ventaja para el ataque" if v == "fav" else "Ventaja para la defensa" if v == "dif" else "Parejo")
                              + f" ({exp:+.2f} EPA/jugada esperada vs un rival promedio)"})
    # --- yardas permitidas por la defensa rival
    for key, nm, lg, rk in (("pase", "Yardas por aire que permite", lg_pass, R["yds_pass"]), ("tierra", "Yardas por tierra que permite", lg_rush, R["yds_rush"])):
        val = dd.loc[de, key]
        rel = val / lg - 1
        v = "fav" if rel >= 0.07 else "dif" if rel <= -0.07 else "neu"
        items.append({"tema": nm, "v": v, "ataque": f"{de} permite {val:.0f} yds por partido", "defensa": f"promedio de la liga: {lg:.0f}",
                      "ra": None, "rd": rk(de),
                      "nota": f"{rel * 100:+.0f}% vs el promedio de la liga ({'permite más' if rel > 0 else 'permite menos'})"})
    # --- presion
    score = (A["pres"] - L["pres"]) + (D["pres"] - L["pres_gen"])
    v = "dif" if score >= 4 else "fav" if score <= -4 else "neu"
    items.append({"tema": "Presión sobre el QB", "v": v,
                  "ataque": f"{of} sufre presión en {A['pres']:.0f}% de sus dropbacks (liga {L['pres']:.0f}%)",
                  "defensa": f"{de} presiona en {D['pres']:.0f}% (liga {L['pres_gen']:.0f}%)", "ra": R["off_pres"](of), "rd": R["def_pres"](de),
                  "nota": "Riesgo: su línea ofensiva sufre y la defensa rival presiona" if v == "dif" else
                          "Cómodo: poca presión recibida y la defensa rival presiona poco" if v == "fav" else "Presión en rangos normales"})
    # --- blitz
    dif_bl = A["epa_bl"] - A["epa_nb"]
    mucho = D["blitz"] >= L["blitz"] + 4
    if mucho and dif_bl <= -0.10:
        v, nota = "dif", "La defensa blitzea mucho y el ataque rinde peor contra el blitz"
    elif mucho and dif_bl >= 0.05:
        v, nota = "fav", "La defensa blitzea mucho, pero este ataque lo castiga"
    elif not mucho and D["blitz"] <= L["blitz"] - 4:
        v, nota = "neu", "La defensa blitzea poco: el blitz casi no entra en juego"
    else:
        v, nota = "neu", "Blitz en rangos normales" + (" · el ataque sufre contra el blitz" if dif_bl <= -0.10 else " · el ataque lo maneja bien" if dif_bl >= 0.05 else "")
    items.append({"tema": "Contra el blitz", "v": v,
                  "ataque": f"{of}: {A['epa_bl']:+.2f} EPA/dropback con blitz vs {A['epa_nb']:+.2f} sin blitz (≈{A['n_bl']:.0f} dropbacks con blitz)",
                  "defensa": f"{de} blitzea en {D['blitz']:.0f}% de los dropbacks (liga {L['blitz']:.0f}%)",
                  "ra": R["off_blitz"](of), "rd": R["def_blitz"](de), "nota": nota})
    return {"ataque": of, "defensa": de, "items": items}


def analizar_partido(home: str, away: str, state, defs, T, R) -> dict:
    return {"home": home, "away": away,
            "lados": [_lado(away, home, state, defs, T, R), _lado(home, away, state, defs, T, R)]}
