"""Historial de «¿cubrio la linea?» por jugador y partido (temporada pasada y la actual), separado local / visita.

IMPORTANTE - de donde sale la linea: las casas de apuestas no publican gratis sus lineas historicas de props.
Por eso, para cada jugador-partido se reconstruye una LINEA «NORMAL» con informacion previa al partido
(modelo que solo ve el historial del jugador y que se entreno con temporadas anteriores; nunca con el propio
partido): linea = piso(proyeccion «normal») + 0.5. Es la linea que se esperaria sin mirar rival ni clima.
«Cubrio» = supero esa linea (OVER). En el mercado de touchdowns la linea es siempre 0.5 (anotar), asi que ahi
el resultado es exacto, no una aproximacion.
Si tienes lineas reales (de tu casa de apuestas), ponlas en data/lineas_props.csv y se usan en lugar de la normal:
  temporada,semana,jugador,mercado,linea        (mercado: pass_yds, pass_cmp, rush_yds, rush_att, rec_yds, rec, tgt, ...)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import db
import props
from data import DATA
from fuentes_web import nombre_norm

COLS = ["season", "week", "game_id", "gameday", "player_id", "name", "position", "team", "opp", "is_home", "market",
        "linea", "valor", "cubrio", "p_over", "mu", "mu_n", "fuente_linea"]


def predecir_temporadas(X: pd.DataFrame, ev: dict, temporadas, log=print) -> pd.DataFrame:
    """Prediccion fuera de muestra de cada jugador-partido jugado: modelos entrenados SOLO con temporadas anteriores."""
    out = []
    for m, spec in props.MARKETS.items():
        d = props._rows(X, spec)
        d = d[d.played == 1]
        y, lam = spec["y"], ev[m]["lam"]
        for s in temporadas:
            tr, te = d[d.season < s], d[d.season == s]
            if te.empty:
                continue
            base = te["e_" + y].to_numpy()
            mu = np.clip(base + lam * (props.make_model().fit(tr[props.FEATS], tr[y].clip(lower=0)).predict(te[props.FEATS]) - base), 1e-3, None)
            mun = np.clip(base + lam * (props.make_model().fit(tr[props.FEATS_N], tr[y].clip(lower=0)).predict(te[props.FEATS_N]) - base), 1e-3, None)
            linea = np.full(len(te), 0.5) if m == "td" else np.floor(mun) + 0.5
            p = props.p_over(mu, ev[m]["phi"], linea)
            if m == "td":
                p = props.calibrar_td(p, ev["td"]["td"]["platt"])
            val = te[y].clip(lower=0).to_numpy()
            out.append(pd.DataFrame({
                "season": te.season.to_numpy(), "week": te.week.to_numpy(), "game_id": te.game_id.to_numpy(),
                "gameday": te.gameday.astype(str).str[:10].to_numpy(), "player_id": te.player_id.to_numpy(),
                "name": te["name"].to_numpy(), "position": te.position.to_numpy(), "team": te.team.to_numpy(),
                "opp": te.opp.to_numpy(), "is_home": te.is_home.astype(int).to_numpy(), "market": m, "linea": linea,
                "valor": val, "cubrio": (val > linea).astype(float), "p_over": np.round(p, 4), "mu": np.round(mu, 3),
                "mu_n": np.round(mun, 3), "fuente_linea": "normal"}))
        log(f"    {spec['label']} listo")
    return pd.concat(out, ignore_index=True)[COLS] if out else pd.DataFrame(columns=COLS)


def aplicar_lineas_reales(cov: pd.DataFrame, log=print) -> pd.DataFrame:
    """Si existe data/lineas_props.csv, esas lineas reemplazan a la «normal» donde coincidan (jugador, temporada, semana, mercado)."""
    ruta = DATA / "lineas_props.csv"
    if cov.empty or not ruta.exists():
        return cov
    try:
        L = pd.read_csv(ruta)
        L.columns = [c.strip().lower() for c in L.columns]
        L["k"] = [f"{nombre_norm(j)}|{int(t)}|{int(w)}|{str(m).strip()}" for j, t, w, m in
                  zip(L.jugador, L.temporada, L.semana, L.mercado)]
        L = L.drop_duplicates("k", keep="last").set_index("k").linea
        k = [f"{nombre_norm(n)}|{int(s)}|{int(w)}|{m}" for n, s, w, m in zip(cov["name"], cov.season, cov.week, cov.market)]
        lin = pd.Series(k, index=cov.index).map(L)
        ok = lin.notna()
        cov = cov.copy()
        cov.loc[ok, "linea"] = lin[ok]
        v = cov.loc[ok, "valor"]
        cov.loc[ok, "cubrio"] = np.where(v > lin[ok], 1.0, np.where(v < lin[ok], 0.0, np.nan))
        cov.loc[ok, "fuente_linea"] = "real"
        log(f"  Lineas reales de data/lineas_props.csv aplicadas a {int(ok.sum())} jugador-partidos")
    except Exception as e:
        log(f"  [aviso] no pude leer data/lineas_props.csv ({e}); uso la linea normal")
    return cov


def cargar_cobertura(X: pd.DataFrame, ev: dict, cur: int, log=print) -> pd.DataFrame:
    """Historial (temporada pasada + actual) guardado en la tabla `props_cobertura`.
    La temporada pasada se calcula una sola vez; la actual se recalcula cuando hay partidos nuevos."""
    jug = X[X.played == 1]
    semanas = {s: int(jug.loc[jug.season == s, "week"].max()) for s in (cur - 1, cur) if (jug.season == s).any()}
    hechas = {}
    if db.hay("props_cobertura"):
        t = db.leer("props_cobertura", [cur - 1, cur], ordenar=None)
        hechas = t.groupby("season").week.max().to_dict() if len(t) else {}
    faltan = [s for s, w in semanas.items() if hechas.get(s, -1) < w or (s == cur - 1 and "td" not in
              set(db.consulta(f"SELECT DISTINCT market FROM props_cobertura WHERE season = {s}").market))]
    if faltan:
        log(f"Historial de «cubrio la linea» ({', '.join(map(str, faltan))}) ...")
        for s in faltan:
            cov = predecir_temporadas(X, ev, [s], log)
            db.reemplazar("props_cobertura", cov.drop(columns="season"), s, fuente="modelo (linea normal, fuera de muestra)")
    if not db.hay("props_cobertura"):
        return pd.DataFrame(columns=COLS)
    return aplicar_lineas_reales(db.leer("props_cobertura", [cur - 1, cur], ordenar="season, week"), log)


def resumen(cov: pd.DataFrame) -> dict:
    """{(player_id, market): {season: (cubrio_total, n_total, cubrio_local, n_local, cubrio_visita, n_visita)}}"""
    c = cov[cov.cubrio.notna()]
    if c.empty:
        return {}
    k = ["player_id", "market", "season"]
    tot = c.groupby(k).cubrio.agg(["sum", "count"])
    loc = c[c.is_home == 1].groupby(k).cubrio.agg(["sum", "count"]).reindex(tot.index).fillna(0)
    vis = c[c.is_home == 0].groupby(k).cubrio.agg(["sum", "count"]).reindex(tot.index).fillna(0)
    out = {}
    for (pid, m, s), t, a, b in zip(tot.index, tot.itertuples(index=False), loc.itertuples(index=False), vis.itertuples(index=False)):
        out.setdefault((pid, m), {})[int(s)] = (int(t[0]), int(t[1]), int(a[0]), int(a[1]), int(b[0]), int(b[1]))
    return out
