"""Calculos extra de la semana: props de jugadores, perfiles de temporada y matchups.

Usa lo mismo que el resto del proyecto (nflverse): estadisticas por jugador, lesiones, depth charts,
presion/blitz (PFR + FTN) y el play-by-play que usa rbsdm.com.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fuentes_web as FW
import movimientos as MOV
import matchups as mu_mod
import cobertura
import lineas_casas as LC
import lesiones_espn as LE
import sin_historial as SH
import props
import por_equipo as PE
from jugadores_data import FIRST_PLAYER_SEASON, load_depth, load_injuries, load_player_weeks
from matchups_data import load_matchup_games
from data import load_team_games, FIRST_SEASON

SENAL = ("pass_yds", "pass_cmp", "rush_yds", "rush_att", "rec_yds")   # mercados donde el ajuste por contexto mostro senal


def _shrink_por_mercado(ev: dict) -> dict:
    """Factor (0.5-1) que encoge las probabilidades hacia 50% donde el backtest mostro exceso de confianza."""
    out = {}
    for m, r in ev.items():
        c = r["cal"]
        num = sum(n * (p - .5) * (y - .5) for n, p, y in zip(c["n"], c["pred"], c["real"]))
        den = sum(n * (p - .5) ** 2 for n, p in zip(c["n"], c["pred"]))
        out[m] = float(np.clip(num / den, 0.5, 1.0)) if den > 0 else 1.0
    return out


def _razon(x, lg_imp: float) -> str:
    """Factores de contexto que empujan la proyeccion EN LA MISMA DIRECCION que el ajuste (max. 2)."""
    sg = 1 if x.ajuste > 0 else -1
    f = []
    rel = {"pass_yds": x.opp_pass_yds_rel, "pass_cmp": x.opp_pass_yds_rel, "rush_yds": x.opp_rush_yds_rel, "rush_att": x.opp_rush_yds_rel,
           "rec_yds": {"WR": x.opp_rec_yds_wr_rel, "TE": x.opp_rec_yds_te_rel, "RB": x.opp_rec_yds_rb_rel}.get(x.position, 1.0)}[x.market]
    if abs(rel - 1) >= 0.05 and (rel - 1) * sg > 0:
        tipo = {"pass_yds": "por aire", "pass_cmp": "por aire", "rush_yds": "por tierra", "rush_att": "por tierra",
                "rec_yds": {"WR": "a los WR", "TE": "a los TE", "RB": "a los RB por recepción"}.get(x.position, "")}[x.market]
        f.append((abs(rel - 1) * 2, f"la defensa rival permite {(rel - 1) * 100:+.0f}% yardas {tipo} vs la liga"))
    d = x.implied - lg_imp
    if abs(d) >= 1.5 and d * sg > 0:
        f.append((abs(d) / 6, f"se esperan {x.implied:.0f} puntos de su equipo ({'más' if d > 0 else 'menos'} que el promedio)"))
    if x.market in ("rush_yds", "rush_att") and abs(x.spread_fav) >= 3 and x.spread_fav * sg > 0:
        f.append((abs(x.spread_fav) / 10, "equipo " + ("favorito: más acarreos al ir ganando" if x.spread_fav > 0 else "obligado a pasar: menos acarreos")))
    if x.market in ("pass_yds", "pass_cmp") and abs(x.spread_fav) >= 3 and -x.spread_fav * sg > 0:
        f.append((abs(x.spread_fav) / 10, "equipo " + ("que irá abajo en el marcador: más pases" if x.spread_fav < 0 else "favorito: pasará menos al controlar el juego")))
    f.sort(reverse=True)
    return "; ".join(t for _, t in f[:2]) or "su volumen reciente y el rendimiento del equipo (ningún factor del partido domina)"


def _cruce_ourlads(P: pd.DataFrame, excl: pd.DataFrame, ou: pd.DataFrame):
    """Marca cada jugador con su estado en Ourlads (O/D/Q...) y saca de las proyecciones a los que Ourlads da como Out o Doubtful."""
    P["ourlads"] = ""
    if ou is None or ou.empty:
        return P, excl
    est = ou[ou.estado != ""].drop_duplicates(["equipo", "jugador_norm"])
    por_equipo = {(r.equipo, r.jugador_norm): r.estado for r in est.itertuples()}
    unicos = est.groupby("jugador_norm").filter(lambda g: len(g) == 1)
    por_nombre = {r.jugador_norm: r.estado for r in unicos.itertuples()}
    nn = P["name"].map(FW.nombre_norm)
    P["ourlads"] = [por_equipo.get((t, n), por_nombre.get(n, "")) for t, n in zip(P.team, nn)]
    fuera = P[P.ourlads.isin(["O", "D"])]
    if len(fuera):
        nuevo = fuera[["name", "team", "position"]].drop_duplicates().assign(
            estado=fuera.drop_duplicates(["name", "team"]).ourlads.map(FW.ESTADOS).values, lesion="según Ourlads")
        excl = pd.concat([excl, nuevo], ignore_index=True) if len(excl) else nuevo
        P = P[~P.ourlads.isin(["O", "D"])].reset_index(drop=True)
    return P, excl


def _inj_con_ourlads(inj: pd.DataFrame, ou: pd.DataFrame, pw: pd.DataFrame, cur: int, wk: int, vigente: dict | None = None) -> pd.DataFrame:
    """Agrega al reporte de lesiones de la semana a los jugadores que Ourlads marca Out/Doubtful y el reporte oficial aun no."""
    if ou is None or ou.empty:
        return inj
    mal = ou[ou.estado.isin(["O", "D"])]
    if mal.empty:
        return inj
    q = pw[pw.season == cur].sort_values("week").drop_duplicates("player_id", keep="last")
    q = q.assign(team=q.player_id.map(vigente or {}).fillna(q.team))
    ids = {(r.team, FW.nombre_norm(r.name)): (r.player_id, r.name, r.position) for r in q.itertuples()}
    ya = set(inj[(inj.season == cur) & (inj.week == wk) & inj.report_status.isin(["Out", "Doubtful"])].gsis_id) if len(inj) else set()
    filas = []
    for r in mal.itertuples():
        hit = ids.get((r.equipo, r.jugador_norm))
        if hit and hit[0] not in ya:
            filas.append({"season": cur, "week": wk, "team": r.equipo, "gsis_id": hit[0], "full_name": hit[1], "position": hit[2],
                          "report_status": FW.ESTADOS[r.estado], "report_primary_injury": "según Ourlads", "practice_status": ""})
    if not filas:
        return inj
    nuevo = pd.DataFrame(filas)
    if len(inj):   # lo oficial manda: se quita cualquier fila previa del mismo jugador y semana
        inj = inj[~((inj.season == cur) & (inj.week == wk) & inj.gsis_id.isin(nuevo.gsis_id))]
    return pd.concat([inj, nuevo], ignore_index=True)


def _qb_de_casas(L: pd.DataFrame, pw: pd.DataFrame, cur: int) -> set:
    """QB que Kalshi/las casas listan con mercado de yardas de pase (= titular esperado), como ids de jugador."""
    if L is None or L.empty:
        return set()
    from fuentes_web import nombre_norm
    qbs = pw[(pw.position == "QB") & (pw.season >= cur - 1)].drop_duplicates("player_id", keep="last")
    por_nombre = {nombre_norm(n): i for n, i in zip(qbs["name"], qbs.player_id)}
    return {por_nombre[k] for k in {nombre_norm(j) for j in L[L.mercado == "pass_yds"].jugador} if k in por_nombre}


def _qb_titular(ou: pd.DataFrame, depth: pd.DataFrame, pw: pd.DataFrame, cur: int, vigente: dict | None = None) -> set:
    """QB titular por equipo: el primero de Ourlads que no este Out/Doubtful; si no se puede cruzar, el del depth chart de nflverse."""
    nv = ({r.team: r.gsis_id for r in depth[(depth.pos_abb == "QB") & (depth.pos_rank == 1)].itertuples()}
          if len(depth) else {})
    if ou is None or ou.empty:
        return set(nv.values()) or None
    q = pw[(pw.season == cur) & (pw.position == "QB")].sort_values("week").drop_duplicates("player_id", keep="last")
    q = q.assign(team=q.player_id.map(vigente or {}).fillna(q.team))      # un QB traspasado cuenta con su equipo nuevo
    ids = {(r.team, FW.nombre_norm(r.name)): r.player_id for r in q.itertuples()}
    out = set()
    for team, g in ou[ou.posicion == "QB"].sort_values("orden").groupby("equipo"):
        sano = g[~g.estado.isin(["O", "D"])]
        pid = ids.get((team, sano.iloc[0].jugador_norm)) if len(sano) else None
        out.add(pid or nv.get(team))
    out |= {v for t, v in nv.items() if t not in set(ou.equipo)}
    return {x for x in out if x} or None


def perfiles(pw: pd.DataFrame, cur: int, ids) -> pd.DataFrame:
    """Metricas de la temporada en curso por jugador (por partido jugado)."""
    cs = pw[(pw.season == cur) & pw.player_id.isin(ids)].sort_values("week")
    g = cs.groupby("player_id").agg(G=("week", "nunique"), att=("att", "sum"), cmp=("cmp", "sum"), pass_yds=("pass_yds", "sum"),
                                    pass_td=("pass_td", "sum"), pass_int=("pass_int", "sum"), car=("car", "sum"),
                                    rush_yds=("rush_yds", "sum"), tgt=("tgt", "sum"), rec=("rec", "sum"),
                                    rec_yds=("rec_yds", "sum"), tshare=("tshare", "mean")).reset_index()
    l3 = cs.groupby("player_id").tail(3).groupby("player_id")[["pass_yds", "rush_yds", "rec_yds", "tgt", "car"]].mean()
    l3.columns = [f"u3_{c}" for c in l3.columns]
    g = g.merge(l3.reset_index(), on="player_id", how="left")
    G = g.G.clip(lower=1)
    for c in ("att", "cmp", "pass_yds", "pass_td", "pass_int", "car", "rush_yds", "tgt", "rec", "rec_yds"):
        g[c + "_pg"] = g[c] / G
    g["cmp_pct"] = np.where(g.att > 0, g.cmp / g.att.replace(0, np.nan) * 100, np.nan)
    g["ypr"] = np.where(g.rec > 0, g.rec_yds / g.rec.replace(0, np.nan), np.nan)
    g["catch_pct"] = np.where(g.tgt > 0, g.rec / g.tgt.replace(0, np.nan) * 100, np.nan)
    g["ypc"] = np.where(g.car > 0, g.rush_yds / g.car.replace(0, np.nan), np.nan)
    return g


def calcular(r: dict, refresh: bool = True, log=print) -> dict:
    games, cur, wk, res, state = r["games"], r["cur"], r["week"], r["res"], r["state"]
    wg = games[games.game_id.isin(res.game_id)]

    log("Lecturas guardadas de rbsdm y Ourlads ...")
    if refresh:
        for nombre, fn in (("Ourlads", lambda: FW.descargar_ourlads(log, cur)), ("rbsdm", lambda: FW.descargar_rbsdm(log))):
            try:                                # lecturas directas, como maximo 1 vez cada 20 h cada una
                fn()
            except Exception as ex:
                log(f"  [aviso] no pude actualizar {nombre} ({ex}); uso la ultima lectura guardada")
    FW.importar_pendientes(log)
    ou = FW.ourlads_actual(cur)
    rbs = FW.rbsdm_actual(cur)

    log("Jugadores: estadisticas, lesiones y depth charts ...")
    pw = load_player_weeks(range(FIRST_PLAYER_SEASON, cur + 1), refresh_seasons=(cur,) if refresh else ())
    inj = load_injuries(cur, refresh)
    depth = load_depth(cur, refresh)

    try:                                   # ESPN: lesionados al dia de los 32 equipos (completa el reporte oficial, que llega por partes)
        E = LE.cargar(refresh, log)
        inj = LE.agregar_a_reporte(inj, E, pw, cur, wk)
    except Exception as ex:
        log(f"  [aviso] no pude usar los lesionados de ESPN ({ex})")
    try:                                   # traspasos: jugadores cuyo depth chart ya los pone en otro equipo que el de su ultimo partido
        vigente = MOV.equipos_vigentes(pw, depth, cur)
        if vigente:
            log(f"  Traspasos aun sin partido con su nuevo equipo: {len(vigente)} (se proyectan con el equipo nuevo)")
    except Exception as ex:
        log(f"  [aviso] no pude revisar los traspasos ({ex})")
        vigente = {}
    inj = _inj_con_ourlads(inj, ou, pw, cur, wk, vigente)
    log("Modelo de props ...")
    try:                                   # snaps de la temporada actual (variables de rol)
        from jugadores_data import load_snaps
        load_snaps(range(2013, cur + 1), refresh_seasons=(cur,) if refresh else ())
    except Exception as ex:
        log(f"  [aviso] no pude actualizar los snaps ({ex}); uso los guardados")
    X, tf, _ = props.construir_X(games, pw)
    ev = props.cargar_evaluacion(X, log=log)
    prefer = _qb_titular(ou, depth, pw, cur, vigente)
    # lineas y precios de las casas (Kalshi; DraftKings via The Odds API si hay llave): se leen solas
    try:
        L = LC.cargar(refresh, log)
    except Exception as ex:
        log(f"  [aviso] no pude leer las lineas de las casas ({ex}); el reporte sigue sin ellas")
        L = pd.DataFrame()
    ka = _qb_de_casas(L, pw, cur)                        # el mercado sabe quien abre de titular: manda sobre el depth chart
    eq = pw.sort_values(["season", "week"]).drop_duplicates("player_id", keep="last").set_index("player_id").team.to_dict()
    eq.update(vigente)
    equipos_k = {eq.get(i) for i in ka}
    prefer = {i for i in prefer if eq.get(i) not in equipos_k} | ka
    P, excl, tf, pstate = props.proyectar(games, pw, inj, wg, cur, wk, ev, prefer=prefer, depth=depth, draft=SH.load_draft(refresh), vigente=vigente)
    P, excl = _cruce_ourlads(P, excl, ou)
    shr = _shrink_por_mercado(ev)
    P["s_cal"] = P.market.map(shr)
    try:                                    # historial «cubrio la linea» (temporada pasada y actual), local / visita
        cov = cobertura.cargar_cobertura(X, ev, cur, log)
    except Exception as ex:
        log(f"  [aviso] no pude armar el historial de cobertura ({ex})")
        cov = pd.DataFrame(columns=cobertura.COLS)
    cres = cobertura.resumen(cov)
    tasas = cov[cov.cubrio.notna()].groupby(["season", "market"]).cubrio.mean().to_dict() if len(cov) else {}
    P["p_over_adj"] = 0.5 + P.s_cal * (P.p_over_base - 0.5)
    try:
        V = LC.comparar(P, L)
        auto, tdauto = LC.linea_automatica(V), LC.td_automatico(V)
        if len(L):
            log(f"  Lineas de casas: {len(L)} escalones, {len(V)} comparados con el modelo, {len(auto)} jugadores con linea automatica")
    except Exception as ex:
        log(f"  [aviso] no pude leer las lineas de las casas ({ex}); el reporte sigue sin ellas")
        V, auto, tdauto = pd.DataFrame(), {}, {}
    # probabilidad de superar la linea «normal» (touchdowns: la P(anotar) ya viene recalibrada)
    P["p_linea"] = np.where(P.market == "td", P.p_td, 0.5 + P.s_cal * (P.p_over_n - 0.5))
    P["rel"] = P.mu / P.base.clip(lower=1e-6) - 1
    if len(depth):
        rol = depth.assign(rol=depth.pos_abb.replace({"FB": "RB"}) + depth.pos_rank.astype(int).astype(str)).set_index("gsis_id").rol.to_dict()
        P["rol"] = P.player_id.map(rol).fillna("")
    else:
        P["rol"] = ""

    log("Matchups (blitz, presion, yardas permitidas) ...")
    defs = props.tabla_defensas(pstate)
    mg = load_matchup_games([cur - 1, cur], refresh_seasons=(cur,) if refresh else ())
    T = mu_mod.tablas_equipo(mg, cur)
    try:                                   # ranking real (esta temporada / ultimos 4 partidos) para contrastar con los ratings del modelo
        rec = mu_mod.ranks_recientes(load_team_games(range(FIRST_SEASON, cur + 1), refresh_seasons=()), games, cur, pw=pw)
    except Exception as ex:
        log(f"  [aviso] no pude armar el ranking reciente ({ex})")
        rec = {}
    R = mu_mod.rank_tabla(T, state, defs, rec)
    mats = {x.game_id: mu_mod.analizar_partido(x.home_team, x.away_team, state, defs, T, R) for x in res.itertuples()}

    perf = perfiles(pw, cur, P.player_id.unique())
    lg_imp = float(P.drop_duplicates(["game_id", "team"]).implied.mean())

    # Mejores props: donde el contexto (rival, guion del partido) mas mueve la proyeccion frente a la linea "normal"
    # del jugador, y solo en mercados / lados donde el backtest mostro senal (el lado se cumplio >= 52%).
    c = P[(P.n_prior >= 4) & P.market.isin(SENAL) & (P.ajuste.abs() >= 0.08) & (P.base >= 1)].copy()
    c["lado"] = np.where(c.ajuste > 0, "OVER", "UNDER")
    c["evid_p"] = [ev[m]["adj"]["p_over_up"] if a_ > 0 else 1 - ev[m]["adj"]["p_over_dn"] for m, a_ in zip(c.market, c.ajuste)]
    c["evid_n"] = [ev[m]["adj"]["n_up"] if a_ > 0 else ev[m]["adj"]["n_dn"] for m, a_ in zip(c.market, c.ajuste)]
    c["evid_base"] = [ev[m]["adj"]["p_over_all"] if a_ > 0 else 1 - ev[m]["adj"]["p_over_all"] for m, a_ in zip(c.market, c.ajuste)]
    c = c[c.evid_p >= 0.52].copy()
    c["razon"] = [_razon(x, lg_imp) for x in c.itertuples()]
    c = c.reindex(c.ajuste.abs().sort_values(ascending=False).index)
    top = c.groupby("player_id").head(2).groupby("game_id").head(4).head(14).reset_index(drop=True)
    try:                                   # resumen por equipo: QB, anotadores, WR, RB (over / under)
        EQ = PE.construir(P, V, auto, tdauto)
    except Exception as ex:
        log(f"  [aviso] no pude armar el resumen por equipo ({ex})")
        EQ = pd.DataFrame()
    try:                                   # Elo (equipo + QB) desde la temporada pasada
        import elo as EL
        ELO = EL.calcular(games, cur)
    except Exception as ex:
        log(f"  [aviso] no pude calcular el Elo ({ex})")
        ELO = None
    try:                                   # movimientos: quien se movio de equipo esta temporada (foto diaria en la base de datos)
        mov_det, mov_of = MOV.detectar(pw, depth, cur), MOV.cruzar_oficial(pw, depth, cur)
        MOV.guardar(mov_det, log)
    except Exception as ex:
        log(f"  [aviso] no pude armar los movimientos de jugadores ({ex})")
        mov_det, mov_of = pd.DataFrame(), pd.DataFrame()
    return {"mov_det": mov_det, "mov_of": mov_of, "elo": ELO, "equipos": EQ, "todos": sorted(set(games[games.season == cur].home_team) | set(games[games.season == cur].away_team)),
            "P": P, "excl": excl, "perf": perf, "mats": mats, "T": T, "defs": defs, "top": top, "ev": ev,
            "shrink": shr, "semana": wk, "rbs": rbs, "ourlads": ou, "cov": cov, "cres": cres, "tasas": tasas, "cur": cur,
            "lineas": L, "V": V, "auto": auto, "tdauto": tdauto}


def csv_props(P: pd.DataFrame) -> pd.DataFrame:
    """Todas las proyecciones de la semana en una tabla en espanol."""
    t = pd.DataFrame({
        "equipo": P.team, "rival": P.opp, "jugador": P.name, "posicion": P.position, "rol_depth": P.rol.replace("", "fuera del depth chart"),
        "estado_lesion": P.estado.replace("", "sin reporte"), "prob_de_jugar_%": (P.p_juega * 100).round(0), "partidos_previos": P.n_prior.astype(int),
        "estado_ourlads": P.ourlads.map(lambda c: FW.ESTADOS.get(c, "sin marca") if c else "sin marca"), "mercado": P.label,
        "promedio_reciente": P.base.round(1), "proyeccion": P.mu.round(1), "p25": P.p25, "mediana": P.p50, "p75": P.p75,
        "linea_normal_estimada": P.line_n, "ajuste_por_contexto_%": (P.ajuste * 100).round(0),
        "ajuste_por_bajas_de_companeros_%": (P.aj_bajas * 100).round(0),
        "prob_superar_linea_normal_%": (P.p_linea * 100).round(0), "localia": np.where(P.is_home == 1, "local", "visita")})
    return t.sort_values(["equipo", "posicion", "jugador", "mercado"]).reset_index(drop=True)


def csv_td(P: pd.DataFrame, cres: dict | None = None, cur: int | None = None) -> pd.DataFrame:
    """Probabilidad de anotar (al menos 1 TD por tierra o recepcion) de cada jugador, por partido, de mayor a menor."""
    t = P[P.market == "td"].copy()
    cres = cres or {}
    def hist(pid, season):
        h = cres.get((pid, "td"), {}).get(season)
        return h
    cols = {}
    for etiqueta, season in (("pasada", (cur or 0) - 1), ("actual", cur or 0)):
        cols[f"anoto_temp_{etiqueta}"] = [f"{h[0]}/{h[1]}" if (h := hist(p, season)) else "" for p in t.player_id]
        cols[f"anoto_local_{etiqueta}"] = [f"{h[2]}/{h[3]}" if (h := hist(p, season)) else "" for p in t.player_id]
        cols[f"anoto_visita_{etiqueta}"] = [f"{h[4]}/{h[5]}" if (h := hist(p, season)) else "" for p in t.player_id]
    out = pd.DataFrame({"equipo": t.team, "rival": t.opp, "localia": np.where(t.is_home == 1, "local", "visita"),
                        "jugador": t.name, "posicion": t.position, "rol_depth": t.rol.replace("", "fuera del depth chart"),
                        "estado_lesion": t.estado.replace("", "sin reporte"),
                        "prob_anotar_%": (t.p_td * 100).round(1), "cuota_justa_americana": t.p_td.map(cuota_justa),
                        "tds_por_partido_reciente": t.base.round(2), **cols})
    return out.sort_values(["equipo", "prob_anotar_%"], ascending=[True, False]).reset_index(drop=True)


def cuota_justa(p: float) -> int:
    """Cuota americana sin comision que corresponde a una probabilidad p."""
    p = min(max(float(p), 0.01), 0.99)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def csv_valor_casas(V: pd.DataFrame) -> pd.DataFrame:
    """Cada escalon de Kalshi / casa frente al modelo, de mayor a menor ventaja neta (ya descontada la comision)."""
    if V is None or V.empty:
        return pd.DataFrame()
    t = V[V.edge.notna()].sort_values(["discrepa", "edge"], ascending=[True, False])
    return pd.DataFrame({"fuente": t.fuente, "equipo": t.equipo, "rival": t.rival, "jugador": t.jugador, "mercado": t.label, "umbral": t.umbral,
                         "precio_si_compra": t.ask, "precio_si_venta": t.bid, "modelo_prob_%": (t.p_modelo * 100).round(1),
                         "mezcla_prob_%": (t.p_mezcla * 100).round(1), "mejor_lado": t.lado, "ventaja_neta_pts": (t.edge * 100).round(1),
                         "ventaja_solo_modelo_pts": (t.edge_modelo * 100).round(1),
                         "discrepancia_de_informacion": np.where(t.discrepa, "SI: el mercado ve algo distinto (titular/lesion/rol)", ""),
                         "estado_lesion": t.estado.replace("", "sin reporte"), "capturado_utc": t.capturado}).reset_index(drop=True)
