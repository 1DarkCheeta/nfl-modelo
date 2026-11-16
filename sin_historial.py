"""Jugadores con poco o ningun historial (novatos, QB suplentes que entran de titular, fichajes).

Medicion (QB que arrancan con menos de 2 partidos previos, 2017-2025, 113 casos, fuera de muestra):
  * El promedio de la posicion que ya usa el modelo da un error de ~63 yardas por pase y su rango de incertidumbre ya esta
    bien calibrado (el rango 10-90 % cubre 73-86 % cuando promete 80 %). No hacia falta ensanchar la dispersion.
  * Mezclar 50/50 con el promedio de los QB debutantes de su misma ronda del draft mejora poco pero de forma consistente
    (TD de pase: error 0.88 -> 0.79; yardas 62.7 -> 62.1). Es lo que se aplica aqui.
  * El problema real era de cobertura: el modelo exigia 2+ partidos previos y no consideraba a quien aun no tenia ninguno.
Para RB/WR/TE con poco historial no hay forma limpia de validar (el rol real depende del depth chart): se les asigna el uso
promedio de su lugar en el depth chart (titular, segundo, tercero), un poco recortado, y se ensancha su dispersion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import BASE, DATA, _download

# promedio por partido de QB que arrancan con <2 partidos previos, por ronda del draft (2013-2025)
QB_DEBUT = {"R1": {"pass_yds": 212.7, "pass_cmp": 19.58, "pass_td": 1.05, "pass_int": 0.89},
            "R2-3": {"pass_yds": 196.1, "pass_cmp": 18.77, "pass_td": 1.00, "pass_int": 0.84},
            "R4-7": {"pass_yds": 184.8, "pass_cmp": 17.58, "pass_td": 0.69, "pass_int": 0.98},
            "sin_draft": {"pass_yds": 191.3, "pass_cmp": 16.58, "pass_td": 0.91, "pass_int": 1.15}}
PESO_DRAFT = 0.5
MAX_RANGO = {"QB": 2, "RB": 3, "WR": 4, "TE": 2}       # hasta que lugar del depth chart se considera «rol esperado»
MIN_PARTIDOS = 5                                       # para calcular el uso promedio de un lugar del depth chart
RECORTE_SKILL = 0.85                                   # novato en un rol = algo menos que el promedio de ese lugar
ENSANCHE_SKILL = 1.3                                   # factor sobre la dispersion (phi) de RB/WR/TE con <2 partidos


def load_draft(refresh: bool = True) -> pd.DataFrame:
    """Ronda de draft por jugador (gsis_id). Guarda una copia reducida; sin internet usa la guardada."""
    ruta = DATA / "draft_min.csv"
    viejo = (not ruta.exists()) or (pd.Timestamp.now().timestamp() - ruta.stat().st_mtime > 20 * 86400)
    if refresh and viejo:
        tmp = DATA / "_draft.csv"
        try:
            if _download(f"{BASE}/draft_picks/draft_picks.csv", tmp):
                d = pd.read_csv(tmp, usecols=["season", "round", "pick", "gsis_id"]).dropna(subset=["gsis_id"])
                d.drop_duplicates("gsis_id").to_csv(ruta, index=False)
        except Exception as e:
            print(f"  [aviso] no pude bajar el draft ({e})")
        finally:
            tmp.unlink(missing_ok=True)
    return pd.read_csv(ruta) if ruta.exists() else pd.DataFrame(columns=["season", "round", "pick", "gsis_id"])


def cubeta(ronda) -> str:
    if pd.isna(ronda):
        return "sin_draft"
    return "R1" if ronda == 1 else ("R2-3" if ronda <= 3 else "R4-7")


def roles(depth: pd.DataFrame) -> pd.DataFrame:
    """Jugadores del depth chart en un lugar de «rol esperado»: columnas gsis_id, name, position, team, rango."""
    if depth is None or depth.empty:
        return pd.DataFrame(columns=["gsis_id", "name", "position", "team", "rango"])
    d = depth[depth.pos_abb.isin(MAX_RANGO)].copy()
    d = d[d.pos_rank <= d.pos_abb.map(MAX_RANGO)]
    d = d.rename(columns={"player_name": "name", "pos_abb": "position", "pos_rank": "rango"})
    return d[["gsis_id", "name", "position", "team", "rango"]].dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")


def candidatos_nuevos(cand: pd.DataFrame, pw: pd.DataFrame, depth: pd.DataFrame, equipos: set, season: int, week: int) -> pd.DataFrame:
    """Jugadores del depth chart que nunca han tenido estadisticas (novatos, practice squad que sube): no estaban en `cand`."""
    r = roles(depth)
    r = r[r.team.isin(equipos) & ~r.gsis_id.isin(set(pw.player_id)) & ~r.gsis_id.isin(set(cand.player_id))]
    if r.empty:
        return cand
    nuevo = r.rename(columns={"gsis_id": "player_id"})[["player_id", "name", "position", "team"]].copy()
    nuevo["season"], nuevo["week"], nuevo["played"] = season, week, 0
    return pd.concat([cand, nuevo], ignore_index=True)


def _derivadas(d: pd.DataFrame) -> pd.DataFrame:
    d["e_ypt"] = d.e_rec_yds / d.e_tgt.clip(lower=0.5)
    d["e_ypr"] = d.e_rec_yds / d.e_rec.clip(lower=0.3)
    d["e_catch"] = d.e_rec / d.e_tgt.clip(lower=0.5)
    d["e_ypa"] = d.e_pass_yds / d.e_att.clip(lower=3)
    d["e_ypc"] = d.e_rush_yds / d.e_car.clip(lower=1)
    d["e_int_rate"] = d.e_pass_int / d.e_att.clip(lower=3)
    return d


def prior_por_rol(F: pd.DataFrame, depth: pd.DataFrame, pstats: list) -> tuple[pd.DataFrame, pd.Series]:
    """Para RB/WR/TE con <2 partidos y rol en el depth chart: sustituye su promedio previo por el de su lugar en el depth chart
    (promedio de los titulares/segundos/terceros de la liga con 5+ partidos) recortado. Devuelve (F, mascara de rol)."""
    r = roles(depth).set_index("gsis_id")
    F = F.copy()
    F["rango"] = F.player_id.map(r.rango)
    rol = F.rango.notna() & (F.n_prior < 2)
    skill = rol & F.position.isin(["RB", "WR", "TE"])
    ref = F[F.rango.notna() & (F.n_prior >= MIN_PARTIDOS)]
    cols = [f"e_{s}" for s in pstats]
    media = ref.groupby(["position", "rango"])[cols].mean()
    for i in F.index[skill]:
        k = (F.at[i, "position"], F.at[i, "rango"])
        if k in media.index:
            F.loc[i, cols] = media.loc[k].values * RECORTE_SKILL
    return _derivadas(F), rol


def mezclar_qb(d: pd.DataFrame, market: str, draft: pd.DataFrame) -> pd.DataFrame:
    """QB con <2 partidos previos: mezcla la proyeccion con el promedio de debutantes de su ronda del draft."""
    if market not in QB_DEBUT["R1"]:
        return d
    d = d.copy()
    ronda = d.player_id.map(draft.drop_duplicates("gsis_id").set_index("gsis_id")["round"]) if len(draft) else pd.Series(np.nan, index=d.index)
    ref = np.array([QB_DEBUT[cubeta(x)][market] for x in ronda])
    m = ((d.position == "QB") & (d.n_prior < 2)).to_numpy()
    for c in ("mu", "mu_n"):
        if c in d:
            d.loc[m, c] = (1 - PESO_DRAFT) * d.loc[m, c] + PESO_DRAFT * ref[m]
    return d
