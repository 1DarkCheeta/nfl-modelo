"""Correlaciones entre jugadores del MISMO partido y probabilidad conjunta de una combinada (parlay).

Que mide: para cada jugador-partido-mercado se calcula el «residuo» fuera de muestra (que tan por encima o por debajo de lo
esperado quedo, en escala normal). Luego se mide cuanto se mueven juntos los residuos de dos jugadores del mismo partido,
por tipo de par (p. ej. QB-yardas con WR-yardas del mismo equipo). 2021-2026, ~2 millones de pares.
Hallazgos principales (estables entre 2021-23 y 2024-26):
  * QB con sus propios receptores: +0.13 a +0.19 (yardas con yardas). Entre receptores del mismo equipo: ~0.
  * Mismo jugador, otro mercado: recepciones-yardas ~0.80, acarreos-yardas ~0.83, pases completos-yardas ~0.9; yardas con TD ~0.2-0.3.
  * QB contra el QB rival: +0.13 (partidos de muchos pases para los dos).
  * Validacion fuera de muestra (correlaciones de 2021-23 aplicadas a 2024-26): «ambos sobre lo esperado» ocurrio 29.0 %
    de las veces; independencia predice 25 %, la copula con estas correlaciones 28.6 %. Brier 0.2076 -> 0.2037.
La probabilidad conjunta usa una copula gaussiana: cada apuesta conserva su probabilidad propia y solo cambia como se combinan.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RUTA = Path(__file__).parent / "correlaciones_tabla.json"
KEEP = ["pass_yds", "pass_cmp", "pass_td", "rush_yds", "rush_att", "rec_yds", "rec", "td"]
ALIAS = {"tgt": "rec"}                  # targets se mueven como recepciones
N_MIN, K_ENCOGE = 300, 300


def cargar() -> dict:
    try:
        return json.loads(RUTA.read_text())
    except Exception:
        return {}


def clave(rel: str, pos_a: str, mk_a: str, pos_b: str, mk_b: str) -> str:
    ka, kb = f"{pos_a}|{ALIAS.get(mk_a, mk_a)}", f"{pos_b}|{ALIAS.get(mk_b, mk_b)}"
    if ka > kb:
        ka, kb = kb, ka
    return f"{rel}|{ka}|{kb}"


def estimar(oos: pd.DataFrame, X: pd.DataFrame) -> dict:
    """oos = mercado_eval.predicciones_oos(X, todas=True). Devuelve {clave: rho encogida}."""
    from scipy.stats import nbinom, norm
    import props as P
    info = X[X.played == 1][["player_id", "season", "week", "team", "game_id", "position"]].drop_duplicates(["player_id", "season", "week"])
    o = oos.merge(info, on=["player_id", "season", "week", "team"], how="left").dropna(subset=["game_id"])
    o = o[o.mercado.isin(KEEP)].copy()
    rng = np.random.default_rng(1)
    z = pd.Series(index=o.index, dtype=float)
    for m, g in o.groupby("mercado"):
        y = np.round(g.y.values)
        V = rng.random(len(g))
        if m == "td":
            p = g.p_td.values
            u = np.where(y < 1, V * (1 - p), (1 - p) + V * p)
        else:
            n, p = P.nb_pn(g.mu.values, g.phi.values)
            lo = np.where(y > 0, nbinom.cdf(y - 1, n, p), 0.0)
            u = lo + V * (nbinom.cdf(y, n, p) - lo)
        z.loc[g.index] = norm.ppf(np.clip(u, 1e-4, 1 - 1e-4))
    o["z"] = z.clip(-3, 3)
    o["team"] = o.team.astype(str)
    a = o[["game_id", "team", "player_id", "position", "mercado", "z"]].copy()
    a["k"] = a.position + "|" + a.mercado
    b = a.merge(a, on="game_id", suffixes=("_a", "_b"))
    b = b[(b.player_id_a < b.player_id_b) | ((b.player_id_a == b.player_id_b) & (b.mercado_a < b.mercado_b))]
    b["rel"] = np.where(b.player_id_a == b.player_id_b, "mismo_jugador", np.where(b.team_a == b.team_b, "mismo_equipo", "rivales"))
    sw = b.k_a > b.k_b
    b["ka"], b["kb"] = np.where(sw, b.k_b, b.k_a), np.where(sw, b.k_a, b.k_b)
    b["za"], b["zb"] = np.where(sw, b.z_b, b.z_a), np.where(sw, b.z_a, b.z_b)
    out = {}
    for (rel, ka, kb), t in b.groupby(["rel", "ka", "kb"]):
        if len(t) >= N_MIN:
            r = float(np.corrcoef(t.za, t.zb)[0, 1]) * len(t) / (len(t) + K_ENCOGE)
            if abs(r) >= 0.03:
                out[f"{rel}|{ka}|{kb}"] = round(r, 3)
    return out


def _psd(R: np.ndarray) -> np.ndarray:
    w, v = np.linalg.eigh(R)
    w = np.clip(w, 1e-3, None)
    R2 = (v * w) @ v.T
    d = np.sqrt(np.diag(R2))
    return R2 / np.outer(d, d)


def conjunta(legs: list[dict], tabla: dict | None = None) -> dict:
    """legs: [{player_id, team, game_id, position, market, p (prob. de que SE CUMPLA esa apuesta), lado ('over'|'under')}].
    Devuelve {'independiente': prod(p), 'conjunta': copula gaussiana}."""
    from scipy.stats import multivariate_normal, norm
    tabla = cargar() if tabla is None else tabla
    n = len(legs)
    p = np.clip([float(x["p"]) for x in legs], 1e-4, 1 - 1e-4)
    ind = float(np.prod(p))
    if n < 2:
        return {"independiente": ind, "conjunta": ind}
    R = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = legs[i], legs[j]
            if a["game_id"] != b["game_id"]:
                continue
            rel = "mismo_jugador" if a["player_id"] == b["player_id"] else ("mismo_equipo" if a["team"] == b["team"] else "rivales")
            r = tabla.get(clave(rel, a["position"], a["market"], b["position"], b["market"]), 0.0)
            sg = (1 if a["lado"] == "under" else -1) * (1 if b["lado"] == "under" else -1)    # over-over y under-under: mismo signo
            R[i, j] = R[j, i] = r * sg
    R = _psd(R)
    c = norm.ppf(p)
    # W_i = s_i Z_i con s=-1 para over, +1 para under; sus correlaciones ya incluyen el signo relativo
    conj = float(multivariate_normal(mean=np.zeros(n), cov=R, allow_singular=True).cdf(c))
    return {"independiente": ind, "conjunta": conj}


if __name__ == "__main__":
    t = cargar()
    print(len(t), "correlaciones")
    legs = [dict(player_id="qb", team="KC", game_id="g", position="QB", market="pass_yds", p=0.5, lado="over"),
            dict(player_id="wr", team="KC", game_id="g", position="WR", market="rec_yds", p=0.5, lado="over")]
    print(conjunta(legs, t))
