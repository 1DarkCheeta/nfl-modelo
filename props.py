"""Props de jugadores (QB / RB / WR / TE): proyeccion + distribucion de probabilidad.

Para cada jugador y mercado (yardas, recepciones, acarreos, targets, intercepciones...):
  1. Variables PRE-partido: promedio movil ponderado de su uso y rendimiento (con lo jugado hasta
     ese momento, mezclado con el promedio de su posicion cuando hay pocos partidos), yardas que
     permite la defensa rival por aire y por tierra (y a WR/TE/RB), y el contexto del partido
     (total y spread del mercado -> puntos esperados del equipo, local/visita, clima).
  2. Un modelo de gradient boosting (perdida Poisson) estima la media.
  3. La dispersion real de cada mercado (binomial negativa) convierte la media en probabilidades
     de superar cualquier linea.
No hay lineas historicas de props gratis: el backtest mide PRECISION de proyeccion y calibracion,
no rentabilidad.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import nbinom
from sklearn.ensemble import HistGradientBoostingRegressor

from data import DATA
import prob_jugar as PJ
import sin_historial as SH
import jugadores_data as JD

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

PSTATS = ["att", "cmp", "pass_yds", "pass_td", "pass_int", "car", "rush_yds", "tgt", "rec", "rec_yds", "tshare", "wopr",
          "rush_td", "rec_td", "td"]
T_OFF = ["pass_att", "rush_att", "pass_yds", "rush_yds"]
T_DEF = ["pass_yds", "rush_yds", "rec_yds_wr", "rec_yds_te", "rec_yds_rb", "pass_att", "rush_att"]
FIRST_TRAIN = 2013
TEST_SEASONS = (2021, 2022, 2023, 2024, 2025)

# mercado -> posiciones, columna objetivo, umbral de elegibilidad (promedio reciente), etiqueta
MARKETS = {
    "pass_yds": dict(pos=["QB"], y="pass_yds", elig=("e_att", 15), label="Yardas por pase", unit="yds"),
    "pass_cmp": dict(pos=["QB"], y="cmp", elig=("e_att", 15), label="Pases completos", unit=""),
    "pass_td": dict(pos=["QB"], y="pass_td", elig=("e_att", 15), label="TD de pase", unit=""),
    "pass_int": dict(pos=["QB"], y="pass_int", elig=("e_att", 15), label="Intercepciones lanzadas", unit=""),
    "rush_yds": dict(pos=["RB"], y="rush_yds", elig=("e_car", 6), label="Yardas por tierra", unit="yds"),
    "rush_att": dict(pos=["RB"], y="car", elig=("e_car", 6), label="Acarreos", unit=""),
    "rec_yds": dict(pos=["WR", "TE", "RB"], y="rec_yds", elig=("e_tgt", 2.5), label="Yardas de recepción", unit="yds"),
    "rec": dict(pos=["WR", "TE", "RB"], y="rec", elig=("e_tgt", 2.5), label="Recepciones", unit=""),
    "tgt": dict(pos=["WR", "TE", "RB"], y="tgt", elig=("e_tgt", 2.5), label="Targets (veces buscado)", unit=""),
    # anotar al menos un TD (por tierra o recepcion; no cuenta el TD de pase). Elegible quien corre, recibe o es QB titular.
    "td": dict(pos=["QB", "RB", "WR", "TE"], y="td", elig=[("e_car", 3), ("e_tgt", 2.0), ("e_att", 15)],
               label="Anotar touchdown", unit=""),
}
MERCADOS_CONTEO = [m for m in MARKETS if m != "td"]


def elegible(X: pd.DataFrame, spec: dict) -> pd.Series:
    """Filtro de elegibilidad: una condicion (col, umbral) o varias alternativas (basta una)."""
    conds = spec["elig"] if isinstance(spec["elig"], list) else [spec["elig"]]
    ok = pd.Series(False, index=X.index)
    for col, thr in conds:
        ok |= X[col] >= thr
    return ok & X.position.isin(spec["pos"])


# ------------------------------------------------------------------ promedios moviles
class EW:
    """Promedio movil exponencial con tasa adaptativa: media corriente al inicio (con k0
    partidos 'fantasma' del valor previo) y EWMA de vida media `halflife` despues."""

    def __init__(self, halflife: float, k0: float = 2.0):
        self.a, self.k0, self.v, self.n = 1 - 0.5 ** (1 / halflife), k0, {}, defaultdict(int)

    def update(self, key, x, prior):
        n = self.n[key]
        v = self.v.get(key, prior)
        a = max(self.a, 1 / (n + 1 + self.k0))
        self.v[key] = v + a * (x - v)
        self.n[key] = n + 1


def team_games(games: pd.DataFrame) -> pd.DataFrame:
    """Una fila por equipo y partido con el contexto del mercado."""
    g = games.copy()
    g["dome"] = g.roof.isin(["dome", "closed"]).astype(int)
    g["wind_eff"] = np.where(g.dome == 1, 0.0, g.wind.fillna(0.0))
    cols = ["game_id", "season", "week", "gameday", "total_line", "wind_eff", "dome", "result"]
    h = g[cols].assign(team=g.home_team, opp=g.away_team, is_home=1, spread_fav=g.spread_line)
    a = g[cols].assign(team=g.away_team, opp=g.home_team, is_home=0, spread_fav=-g.spread_line)
    t = pd.concat([h, a], ignore_index=True)
    t["implied"] = t.total_line / 2 + t.spread_fav / 2    # puntos esperados del equipo
    return t.sort_values(["gameday", "game_id"]).reset_index(drop=True)


def team_off_stats(pw: pd.DataFrame) -> pd.DataFrame:
    off = pw.groupby(["season", "week", "team"]).agg(pass_att=("att", "sum"), pass_yds=("pass_yds", "sum"),
                                                     rush_att=("car", "sum"), rush_yds=("rush_yds", "sum")).reset_index()
    rec = pw.pivot_table(index=["season", "week", "team"], columns="position", values="rec_yds",
                         aggfunc="sum", fill_value=0)
    rec.columns = [f"rec_yds_{c.lower()}" for c in rec.columns]
    return off.merge(rec.reset_index(), on=["season", "week", "team"], how="left").fillna(0)


def build_team_features(tgm: pd.DataFrame, off: pd.DataFrame):
    """Ataque propio y yardas PERMITIDAS por cada defensa (EWMA pre-partido), en cifras y relativo a la liga."""
    obs = {(r.season, r.week, r.team): r._asdict() for r in off.itertuples(index=False)}
    ew, lg = EW(6, 2), EW(1500, 0)
    rows, pending, cur_day = [], [], None

    def flush():  # las actualizaciones se aplican al terminar el dia (sin fuga entre partidos del mismo dia)
        for t in pending:
            x = obs[(t["season"], t["week"], t["team"])]
            for s in T_OFF:
                ew.update(("off", t["team"], s), x[s], lg.v.get(s, 0))
            for s in T_DEF:
                ew.update(("def", t["opp"], s), x[s], lg.v.get(s, 0))
        for t in pending:
            x = obs[(t["season"], t["week"], t["team"])]
            for s in T_DEF:
                lg.update(s, x[s], 0)
        pending.clear()

    for _, gm in tgm.groupby("game_id", sort=False):
        gm = gm.to_dict("records")
        if gm[0]["gameday"] != cur_day:
            flush()
            cur_day = gm[0]["gameday"]
        for t in gm:  # 1) registrar estado previo de ambos equipos
            o = t["opp"]
            r = {"game_id": t["game_id"], "team": t["team"]}
            for s in T_OFF:
                r[f"own_{s}"] = ew.v.get(("off", t["team"], s), lg.v.get(s, 0))
            for s in T_DEF:
                base = lg.v.get(s, 0)
                r[f"opp_{s}"] = ew.v.get(("def", o, s), base)
                r[f"opp_{s}_rel"] = r[f"opp_{s}"] / base if base else 1.0
                r[f"own_def_{s}"] = ew.v.get(("def", t["team"], s), base)
            rows.append(r)
        ks = [(t["season"], t["week"], t["team"]) for t in gm]
        if all(k in obs for k in ks):  # 2) actualizar solo si se jugo y hay estadisticas de ambos
            pending.extend(gm)
    flush()
    state = {"lg": dict(lg.v), "def": {k[1]: {} for k in ew.v if k[0] == "def"}}
    for (kind, team, s), v in ew.v.items():
        if kind == "def":
            state["def"][team][s] = v
    return pd.DataFrame(rows), state


def build_player_features(pw: pd.DataFrame, tgm: pd.DataFrame, tf: pd.DataFrame) -> pd.DataFrame:
    """Variables pre-partido por jugador. `pw` puede incluir filas futuras (played=0, estadisticas NaN)."""
    ctx = ["season", "week", "team", "game_id", "gameday", "opp", "is_home", "implied", "spread_fav",
           "total_line", "wind_eff", "dome"]
    d = pw.copy()
    if "played" not in d:
        d["played"] = 1
    d = d.merge(tgm[ctx], on=["season", "week", "team"], how="left").dropna(subset=["gameday"])
    d = d.sort_values(["gameday", "player_id"], kind="stable").reset_index(drop=True)

    ew, pos_ew = EW(6, 2), EW(3000, 0)
    n_prior, last_team = defaultdict(int), {}
    feats, npr, newt = [], [], []
    cols = {s: d[s].to_numpy(float) for s in PSTATS}
    pid, pos, team, played = d.player_id.to_numpy(), d.position.to_numpy(), d.team.to_numpy(), d.played.to_numpy()
    gd = d.gameday.to_numpy()
    pending = []

    def flush():  # actualizar al terminar cada dia: los partidos del mismo dia no se contaminan entre si
        for j in pending:
            for s in PSTATS:
                x = cols[s][j]
                ew.update((pid[j], s), x, pos_ew.v.get((pos[j], s), 0.0))
            n_prior[pid[j]] += 1
            last_team[pid[j]] = team[j]
        for j in pending:
            for s in PSTATS:
                pos_ew.update((pos[j], s), cols[s][j], 0.0)
        pending.clear()

    for i in range(len(d)):
        if i > 0 and gd[i] != gd[i - 1]:
            flush()
        p = pid[i]
        feats.append([ew.v.get((p, s), pos_ew.v.get((pos[i], s), 0.0)) for s in PSTATS])
        npr.append(n_prior[p])
        newt.append(int(p in last_team and last_team[p] != team[i]))
        if played[i] == 1:
            pending.append(i)
    flush()
    F = pd.DataFrame(feats, columns=[f"e_{s}" for s in PSTATS])
    d = pd.concat([d, F], axis=1)
    d["n_prior"], d["new_team"] = npr, newt
    d = d.merge(tf, on=["game_id", "team"], how="left")
    d["e_ypt"] = d.e_rec_yds / d.e_tgt.clip(lower=0.5)
    d["e_ypr"] = d.e_rec_yds / d.e_rec.clip(lower=0.3)
    d["e_catch"] = d.e_rec / d.e_tgt.clip(lower=0.5)
    d["e_ypa"] = d.e_pass_yds / d.e_att.clip(lower=3)
    d["e_ypc"] = d.e_rush_yds / d.e_car.clip(lower=1)
    d["e_int_rate"] = d.e_pass_int / d.e_att.clip(lower=3)
    for p in ("QB", "RB", "WR", "TE"):
        d[f"is_{p.lower()}"] = (d.position == p).astype(int)
    return d


FEATS = ([f"e_{s}" for s in PSTATS] + ["e_ypt", "e_ypr", "e_catch", "e_ypa", "e_ypc", "e_int_rate", "n_prior", "new_team",
         "is_home", "implied", "spread_fav", "total_line", "wind_eff", "dome", "is_qb", "is_rb", "is_wr", "is_te"]
         + [f"own_{s}" for s in T_OFF] + [f"opp_{s}_rel" for s in T_DEF])


# Bajas «nuevas»: uso esperado (e_*) de los companeros que jugaron el partido anterior del equipo y hoy no estan.
# Con las bajas largas el promedio reciente ya se adapto; lo que falta es la baja de esta semana.
AUS = ["aus_tgt_wr", "aus_tgt_te", "aus_tgt_rb", "aus_car", "aus_att"]
FEATS = FEATS + AUS

FEATS_N = ([f"e_{s}" for s in PSTATS] + ["e_ypt", "e_ypr", "e_catch", "e_ypa", "e_ypc", "e_int_rate", "n_prior", "new_team",
           "is_qb", "is_rb", "is_wr", "is_te"])


def agregar_bajas(X: pd.DataFrame, fuera=None) -> pd.DataFrame:
    """Agrega las columnas AUS. Historico: ausente = jugo el partido previo del equipo (con >=3 partidos de historial) y hoy no
    tiene fila. Partido futuro (played = 0): ausente = ademas, quien aparece en `fuera` (Out/Doubtful de la semana)."""
    X = X.copy()
    fuera = set(fuera or ())
    orden = {k: sorted(g.week.unique()) for k, g in X.groupby(["season", "team"])}
    prev = {(s, b, t): a for (s, t), ws in orden.items() for a, b in zip(ws[:-1], ws[1:])}
    sub = X[X.played == 1][["season", "week", "team", "player_id", "position", "e_tgt", "e_car", "e_att", "n_prior"]]
    jugaron = {k: g[g.n_prior >= 3] for k, g in sub.groupby(["season", "week", "team"])}
    add = {}
    for (s, w, t), g in X.groupby(["season", "week", "team"]):
        a = prev.get((s, w, t))
        p0 = jugaron.get((s, a, t)) if a is not None else None
        if p0 is None or p0.empty:
            continue
        hoy = set(g[(g.played == 1) | (~g.player_id.isin(fuera))].player_id)
        aus = p0[~p0.player_id.isin(hoy)]
        if aus.empty:
            continue
        add[(s, w, t)] = (aus[aus.position == "WR"].e_tgt.sum(), aus[aus.position == "TE"].e_tgt.sum(),
                          aus[aus.position == "RB"].e_tgt.sum(), aus[aus.position == "RB"].e_car.sum(),
                          aus[aus.position == "QB"].e_att.sum())
    arr = np.array([add.get(k, (0, 0, 0, 0, 0)) for k in zip(X.season, X.week, X.team)], float).reshape(-1, len(AUS))
    for j, c in enumerate(AUS):
        X[c] = arr[:, j]
    return X


# Variables de ROL (snaps, cuota de acarreos, descanso, ausencias propias). Medido fuera de muestra 2021-2026, todas mejoran:
# error de yardas por pase -7 %, pases completos -7.5 %, acarreos -5.5 %, yardas por tierra -3 %, receptores -1 a -2 %.
ROL_J = ["e_snap", "snap_last", "e_snap2", "e_snapn", "snap_trend", "e_cshare", "cshare_last", "juego_prev4", "jugo_prev"]
ROL = ROL_J + ["rest"]
FEATS = FEATS + ROL
FEATS_N = FEATS_N + ROL_J


def agregar_rol(X: pd.DataFrame, games: pd.DataFrame, snaps: pd.DataFrame | None) -> pd.DataFrame:
    """Anade las variables de rol a X usando SOLO informacion de partidos anteriores (merge_asof estricto por fecha)."""
    X = X.copy()
    X["_o"] = np.arange(len(X))
    X["gameday"] = pd.to_datetime(X.gameday)
    X = X.sort_values("gameday")
    if snaps is not None and len(snaps):
        sg = snaps.merge(games[["game_id", "gameday"]], on="game_id")
        sg["gameday"] = pd.to_datetime(sg.gameday)
        sg = sg.sort_values(["player_id", "gameday"])
        g = sg.groupby("player_id")
        sg["snap_last"] = sg.offense_pct
        sg["e_snap"] = g.offense_pct.transform(lambda s: s.ewm(halflife=6, min_periods=1).mean())
        sg["e_snap2"] = g.offense_pct.transform(lambda s: s.ewm(halflife=2, min_periods=1).mean())
        sg["e_snapn"] = g.offense_snaps.transform(lambda s: s.ewm(halflife=6, min_periods=1).mean())
        post = sg[["player_id", "gameday", "snap_last", "e_snap", "e_snap2", "e_snapn"]].rename(columns={"gameday": "gd_s"}).sort_values("gd_s")
        X = pd.merge_asof(X, post, left_on="gameday", right_on="gd_s", by="player_id", allow_exact_matches=False).drop(columns="gd_s")
    else:
        for c in ("snap_last", "e_snap", "e_snap2", "e_snapn"):
            X[c] = np.nan
    X["snap_trend"] = X.snap_last - X.e_snap
    pl = X[X.played == 1]
    tc = pl.groupby(["game_id", "team"]).car.transform("sum")
    y = pl.assign(cshare=pl.car / tc.clip(lower=1)).sort_values(["player_id", "gameday"])
    y["e_cshare"] = y.groupby("player_id").cshare.transform(lambda s: s.ewm(halflife=6, min_periods=1).mean())
    pc = y[["player_id", "gameday", "e_cshare", "cshare"]].rename(columns={"gameday": "gd_c", "cshare": "cshare_last"}).sort_values("gd_c")
    X = pd.merge_asof(X.sort_values("gameday"), pc, left_on="gameday", right_on="gd_c", by="player_id", allow_exact_matches=False).drop(columns="gd_c")
    # descanso (dias) del equipo antes de ese partido
    rest = pd.concat([games[["game_id", "home_team", "home_rest"]].rename(columns={"home_team": "team", "home_rest": "rest"}),
                      games[["game_id", "away_team", "away_rest"]].rename(columns={"away_team": "team", "away_rest": "rest"})])
    X = X.merge(rest.drop_duplicates(["game_id", "team"]), on=["game_id", "team"], how="left")
    # ausencias propias: de los 4 juegos previos del equipo, en cuantos aparecio
    tg = X[["team", "season", "week"]].drop_duplicates().sort_values(["team", "season", "week"]).reset_index(drop=True)
    tg["_g"] = tg.groupby("team").cumcount()
    X = X.merge(tg, on=["team", "season", "week"], how="left")
    pset = set(zip(X.loc[X.played == 1, "player_id"] + "|" + X.loc[X.played == 1, "team"], X.loc[X.played == 1, "_g"]))
    key, gg = (X.player_id + "|" + X.team).to_numpy(), X._g.to_numpy()
    X["juego_prev4"] = [sum((k, x - j) in pset for j in range(1, 5)) for k, x in zip(key, gg)]
    X["jugo_prev"] = [int((k, x - 1) in pset) for k, x in zip(key, gg)]
    return X.sort_values("_o").drop(columns=["_o", "_g"]).reset_index(drop=True)


def construir_X(games, pw, extra_rows: pd.DataFrame | None = None, fuera=None):
    tgm = team_games(games)
    off = team_off_stats(pw)
    tf, state = build_team_features(tgm, off)
    allp = pw if extra_rows is None else pd.concat([pw.assign(played=1), extra_rows], ignore_index=True)
    X = agregar_bajas(build_player_features(allp, tgm, tf), fuera)
    try:
        snaps = JD.load_snaps(sorted(set(int(s) for s in pw.season)))
    except Exception as e:
        print(f"  [aviso] sin snaps ({e}); las variables de rol quedan vacias")
        snaps = None
    return agregar_rol(X, games, snaps), tf, state


# ------------------------------------------------------------------ modelos
def make_model():
    return HistGradientBoostingRegressor(loss="poisson", learning_rate=0.05, max_iter=200, max_leaf_nodes=8,
                                         min_samples_leaf=60, l2_regularization=1.0, random_state=0)


def _rows(X, spec):
    return X[elegible(X, spec) & (X.n_prior >= 2) & (X.season >= FIRST_TRAIN)]


def entrenar_final(X: pd.DataFrame) -> dict:
    out = {}
    for m, spec in MARKETS.items():
        d = _rows(X, spec)
        d = d[d.played == 1]
        out[m] = make_model().fit(d[FEATS], d[spec["y"]].clip(lower=0))
    return out


def entrenar_neutral(X: pd.DataFrame) -> dict:
    """Modelo 'sin contexto': solo el historial del jugador. Aproxima la linea normal de un jugador; la diferencia
    con el modelo completo es lo que aportan el rival, el guion del partido y el clima."""
    out = {}
    for m, spec in MARKETS.items():
        d = _rows(X, spec)
        d = d[d.played == 1]
        out[m] = make_model().fit(d[FEATS_N], d[spec["y"]].clip(lower=0))
    return out


def nb_pn(mu, phi):
    mu = np.clip(np.asarray(mu, float), 1e-3, None)
    n = 1 / phi
    return n, n / (n + mu)


def p_over(mu, phi, line):
    """P(Y > linea). Con lineas .5 no hay push."""
    n, p = nb_pn(mu, phi)
    return 1 - nbinom.cdf(np.floor(line), n, p)


def p_under(mu, phi, line):
    n, p = nb_pn(mu, phi)
    return nbinom.cdf(np.ceil(line) - 1, n, p)


def estimar_phi(y, mu) -> float:
    y, mu = np.asarray(y, float), np.clip(np.asarray(mu, float), 1e-3, None)
    return float(max(0.02, np.sum((y - mu) ** 2 - mu) / np.sum(mu ** 2)))


def backtest_props(X: pd.DataFrame, log=print) -> dict:
    """Walk-forward: cada temporada de TEST_SEASONS se predice con modelos entrenados con temporadas previas."""
    res, rows = {}, []
    for m, spec in MARKETS.items():
        d = _rows(X, spec)
        d = d[d.played == 1]
        ycol, ecol = spec["y"], "e_" + spec["y"]
        parts = []
        for s in TEST_SEASONS:
            tr, te = d[d.season < s], d[d.season == s]
            mu = make_model().fit(tr[FEATS], tr[ycol].clip(lower=0)).predict(te[FEATS])
            mun = make_model().fit(tr[FEATS_N], tr[ycol].clip(lower=0)).predict(te[FEATS_N])
            parts.append(pd.DataFrame({"season": s, "y": te[ycol].clip(lower=0).values, "mu": mu, "mu_n": mun, "base": te[ecol].values}))
        o = pd.concat(parts, ignore_index=True)
        phi_b = estimar_phi(o.y, o.base)
        # Encogimiento hacia el promedio reciente: mu = base + lam * (mu_modelo - base). Se elige lam por logscore OOS.
        best = None
        for lam in (0.4, 0.6, 0.8, 1.0):
            mu_l = np.clip(o.base + lam * (o.mu - o.base), 1e-3, None)
            ph = estimar_phi(o.y, mu_l)
            n_, p_ = nb_pn(mu_l, ph)
            ll = float(nbinom.logpmf(np.round(o.y), n_, p_).mean())
            if best is None or ll > best[0]:
                best = (ll, lam, ph, mu_l)
        ll_m, lam, phi_m, mu_best = best
        o["mu"] = mu_best
        o["mu_n"] = np.clip(o.base + lam * (o.mu_n - o.base), 1e-3, None)
        nb_, pb_ = nb_pn(o.base.clip(lower=1e-3), phi_b)
        ll_b = float(nbinom.logpmf(np.round(o.y), nb_, pb_).mean())
        line = np.floor(o.base) + 0.5                       # linea hipotetica pegada al promedio reciente
        if m == "td":
            line = np.full(len(o), 0.5)                     # «anotar» = mas de 0.5 touchdowns
        po = p_over(o.mu, phi_m, line)
        o["over"], o["p_over"] = (o.y > line).astype(int), po
        cortes = [0, .1, .2, .3, .4, .5, 1.0] if m == "td" else [0, .35, .45, .55, .65, 1.0]
        bins = pd.cut(o.p_over, cortes, include_lowest=True)
        cal = o.groupby(bins, observed=True).agg(n=("over", "size"), pred=("p_over", "mean"), real=("over", "mean")).reset_index(drop=True)
        # Ajuste por contexto: ¿cuando el modelo completo sube/baja la proyeccion vs la 'normal', pasa de verdad?
        o["aj"] = o.mu / o.mu_n - 1
        ln = np.full(len(o), 0.5) if m == "td" else np.floor(o.mu_n) + 0.5
        o["over_n"] = (o.y > ln).astype(int)
        up, dn = o[o.aj >= 0.08], o[o.aj <= -0.08]
        adj = {"p_over_all": float(o.over_n.mean()), "n_up": int(len(up)), "p_over_up": float(up.over_n.mean()) if len(up) else None,
               "n_dn": int(len(dn)), "p_over_dn": float(dn.over_n.mean()) if len(dn) else None,
               "mae_neutral": float((o.y - o.mu_n).abs().mean())}
        res[m] = {"n": int(len(o)), "adj": adj, "mae_modelo": float((o.y - o.mu).abs().mean()), "mae_base": float((o.y - o.base).abs().mean()),
                  "phi": phi_m, "lam": lam, "logscore_modelo": ll_m, "logscore_base": ll_b, "cal": cal.round(3).to_dict("list")}
        if m == "td":
            res[m]["td"] = _eval_td(o, phi_m, phi_b)
            t = res[m]["td"]
            log(f"    P(anotar): log-loss {t['ll_modelo']:.4f} (promedio reciente {t['ll_base']:.4f}); "
                f"entre el 10% con mayor probabilidad anotó {t['top10_real'] * 100:.0f}% (esperado {t['top10_pred'] * 100:.0f}%)")
        rows.append((m, res[m]))
        log(f"  {spec['label']}: error medio {res[m]['mae_modelo']:.2f} vs promedio reciente {res[m]['mae_base']:.2f} (n={len(o)})")
    return res


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def calibrar_td(p, platt) -> np.ndarray:
    """Recalibracion logistica de P(anotar) con los parametros (a, b) hallados en el backtest."""
    a, b = platt
    return 1 / (1 + np.exp(-(a + b * _logit(p))))


def _eval_td(o: pd.DataFrame, phi_m: float, phi_b: float) -> dict:
    """Mide P(anotar al menos un TD) fuera de muestra: log-loss y Brier contra el simple promedio reciente,
    fiabilidad por tramos y recalibracion logistica."""
    from sklearn.linear_model import LogisticRegression
    y = (o.y >= 1).astype(float).to_numpy()
    p = np.clip(p_over(o.mu, phi_m, 0.5), 1e-4, 1 - 1e-4)
    p0 = np.clip(p_over(o.base.clip(lower=1e-3), phi_b, 0.5), 1e-4, 1 - 1e-4)
    lr = LogisticRegression(C=1e6, max_iter=500).fit(_logit(p).reshape(-1, 1), y)
    platt = (float(lr.intercept_[0]), float(lr.coef_[0][0]))
    pc = calibrar_td(p, platt)
    ll = lambda q: float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())
    br = lambda q: float(((y - q) ** 2).mean())
    corte = np.quantile(pc, 0.9)
    top = pc >= corte
    bins = pd.cut(pd.Series(pc), [0, .1, .2, .3, .4, .5, .6, 1.0], include_lowest=True)
    cal = pd.DataFrame({"b": bins, "pred": pc, "real": y}).groupby("b", observed=True).agg(
        n=("real", "size"), pred=("pred", "mean"), real=("real", "mean")).reset_index(drop=True)
    return {"n": int(len(y)), "tasa": float(y.mean()), "ll_base": ll(p0), "ll_modelo": ll(np.clip(p, 1e-4, 1 - 1e-4)),
            "ll_cal": ll(pc), "brier_base": br(p0), "brier_modelo": br(p), "brier_cal": br(pc), "platt": platt,
            "top10_pred": float(pc[top].mean()), "top10_real": float(y[top].mean()), "cal": cal.round(3).to_dict("list")}


def cargar_evaluacion(X, refrescar=False, log=print) -> dict:
    """Evaluacion y dispersion por mercado, guardadas en disco (se recalculan una vez al mes)."""
    path = DATA / "props_eval_v4.json"
    import time
    if path.exists() and not refrescar and time.time() - path.stat().st_mtime < 30 * 86400:
        return json.loads(path.read_text())
    log("Evaluando el modelo de props con temporadas pasadas (solo ocurre una vez al mes, ~2-4 minutos)...")
    r = backtest_props(X, log)
    path.write_text(json.dumps(r))
    return r


# ------------------------------------------------------------------ proyeccion de la semana
def candidatos(games, pw, week_games: pd.DataFrame, inj: pd.DataFrame, season: int, week: int, vigente: dict | None = None):
    """Jugadores probables de jugar en los partidos pendientes (con su fila 'futura').
    `vigente` = {player_id: equipo actual} para quien lo traspasaron y aun no juega con el nuevo (ver movimientos.py)."""
    done = games[games.result.notna()]
    tw = pd.concat([done[["season", "week", "home_team"]].rename(columns={"home_team": "team"}),
                    done[["season", "week", "away_team"]].rename(columns={"away_team": "team"})])
    last = pw.sort_values(["season", "week"]).groupby("player_id").tail(1)
    if vigente:
        last = last.assign(team=last.player_id.map(vigente).fillna(last.team))
    teams = set(week_games.home_team) | set(week_games.away_team)
    last = last[last.team.isin(teams)]
    keep = []
    for r in last.itertuples():
        gap = ((tw.team == r.team) & ((tw.season > r.season) | ((tw.season == r.season) & (tw.week > r.week)))).sum()
        if gap <= 2:
            keep.append(r.player_id)
    cand = last[last.player_id.isin(keep)][["player_id", "name", "position", "team"]].copy()
    cand["season"], cand["week"], cand["played"] = season, week, 0
    return cand


def proyectar(games, pw, inj, week_games, season, week, evalu: dict, models: dict | None = None, X_full=None, prefer=None,
              depth: pd.DataFrame | None = None, draft: pd.DataFrame | None = None, vigente: dict | None = None):
    """DataFrame con una fila por jugador-mercado de los partidos pendientes."""
    cand = candidatos(games, pw, week_games, inj, season, week, vigente)
    if depth is not None and len(depth):          # novatos / jugadores sin partidos que el depth chart ya pone en un rol
        cand = SH.candidatos_nuevos(cand, pw, depth, set(week_games.home_team) | set(week_games.away_team), season, week)
    for s in PSTATS:
        cand[s] = np.nan
    fuera = set()
    if inj is not None and len(inj):
        fuera = set(inj[(inj.season == season) & (inj.week == week) & inj.report_status.isin(["Out", "Doubtful"])].gsis_id)
    X, tf, state = construir_X(games, pw, cand, fuera)
    F = X[(X.played == 0) & (X.season == season) & (X.week == week)].copy()
    if depth is not None and len(depth):
        F, rol = SH.prior_por_rol(F, depth, PSTATS)
    else:
        F["rango"], rol = np.nan, pd.Series(False, index=F.index)
    draft = draft if draft is not None else pd.DataFrame(columns=["season", "round", "pick", "gsis_id"])
    hist = X[X.played == 1] if X_full is None else X_full
    models = models or entrenar_final(X[X.played == 1])
    neutral = entrenar_neutral(X[X.played == 1])

    # estado de lesiones de la semana
    flag = {}
    if inj is not None and len(inj):
        w = inj[(inj.season == season) & (inj.week == week)]
        for r in w.itertuples():
            st = r.report_status if isinstance(r.report_status, str) else ""
            pr = r.practice_status if isinstance(r.practice_status, str) else ""
            flag[r.gsis_id] = (st, pr, r.report_primary_injury if isinstance(r.report_primary_injury, str) else "")
    out, excl = [], []
    for m, spec in MARKETS.items():
        d = F[(elegible(F, spec) & (F.n_prior >= 2)) | (rol & F.position.isin(spec["pos"]))].copy()
        if d.empty:
            continue
        d["base"] = d["e_" + spec["y"]]
        d["mu"] = np.clip(d.base + evalu[m]["lam"] * (models[m].predict(d[FEATS]) - d.base), 1e-3, None)
        d["mu_n"] = np.clip(d.base + evalu[m]["lam"] * (neutral[m].predict(d[FEATS_N]) - d.base), 1e-3, None)
        sin = d[FEATS].copy()
        sin[AUS] = 0.0
        mu_sin = np.clip(d.base + evalu[m]["lam"] * (models[m].predict(sin) - d.base), 1e-3, None)
        d["aj_bajas"] = d.mu / mu_sin - 1               # cuanto cambia la proyeccion por las bajas de companeros
        # jugadores con rol pero fuera del rango con que se entreno el modelo (poco uso previo): proyeccion = su promedio de rol
        fuera_rango = ~elegible(d, spec).to_numpy()
        for c in ("mu", "mu_n"):
            d.loc[fuera_rango, c] = d.loc[fuera_rango, "base"]
        d.loc[fuera_rango, "aj_bajas"] = 0.0
        d["ajuste"] = d.mu / d.mu_n - 1
        # Questionable: probabilidad de jugar (segun la practica) y proyeccion «si juega» un poco menor
        d["estado"] = d.player_id.map(lambda i: flag.get(i, ("", "", ""))[0])
        d["practica"] = d.player_id.map(lambda i: flag.get(i, ("", "", ""))[1])
        d = PJ.ajustar(d, m)
        d = SH.mezclar_qb(d, m, draft)
        d["line_n"] = np.floor(d.mu_n) + 0.5
        phi = np.where((d.n_prior < 2) & (d.position != "QB"), evalu[m]["phi"] * SH.ENSANCHE_SKILL, evalu[m]["phi"])
        n, p = nb_pn(d.mu, phi)
        for q in (10, 25, 50, 75, 90):
            d[f"p{q}"] = nbinom.ppf(q / 100, n, p)
        d["market"], d["phi"], d["label"] = m, phi, spec["label"]
        d["line_base"] = np.floor(d.base) + 0.5
        d["p_over_base"] = p_over(d.mu, phi, d.line_base)
        d["p_over_n"] = p_over(d.mu, phi, d.line_n)
        out.append(d)
    P = pd.concat(out, ignore_index=True)
    P["p_td"] = np.nan
    es_td = P.market == "td"
    if es_td.any():
        P.loc[es_td, "p_td"] = calibrar_td(p_over(P.loc[es_td, "mu"], evalu["td"]["phi"], 0.5), evalu["td"]["td"]["platt"])
    P["estado"] = P.player_id.map(lambda i: flag.get(i, ("", "", ""))[0])
    P["practica"] = P.player_id.map(lambda i: flag.get(i, ("", "", ""))[1])
    P["lesion"] = P.player_id.map(lambda i: flag.get(i, ("", "", ""))[2])
    excluidos = P[P.estado.isin(["Out", "Doubtful"])][["name", "team", "position", "estado", "lesion"]].drop_duplicates()
    P = P[~P.estado.isin(["Out", "Doubtful"])].reset_index(drop=True)
    # un solo QB por equipo: el titular (depth chart / Ourlads) y, si no hay, el de mayor volumen reciente.
    # Se elige DESPUES de sacar a los lesionados (Out/Doubtful), para no quedarse sin QB por escoger a uno que no juega.
    pref = set(prefer or [])
    qb = (P[P.position == "QB"].assign(_pref=lambda q: q.player_id.isin(pref))
          .assign(_dep=lambda q: -q.rango.fillna(99))
          .sort_values(["_pref", "_dep", "e_att"], ascending=False).drop_duplicates("team").player_id)
    P = P[(P.position != "QB") | P.player_id.isin(qb.values)].reset_index(drop=True)
    return P, excluidos, tf, state


def tabla_defensas(state: dict) -> pd.DataFrame:
    """Yardas permitidas por partido (promedio reciente) por aire, tierra y a cada posicion receptora."""
    lg = state["lg"]
    rows = []
    for t, d in state["def"].items():
        rows.append({"team": t, "pase": d["pass_yds"], "tierra": d["rush_yds"], "wr": d["rec_yds_wr"], "te": d["rec_yds_te"],
                     "rb_rec": d["rec_yds_rb"], "pase_rel": d["pass_yds"] / lg["pass_yds"] - 1,
                     "tierra_rel": d["rush_yds"] / lg["rush_yds"] - 1})
    return pd.DataFrame(rows).sort_values("pase", ascending=False).reset_index(drop=True)
