"""Movimientos de jugadores entre equipos (traspasos, fichajes): quien llego a donde, y que el modelo lo use con su equipo actual.

El problema que resuelve: las estadisticas por jugador (player_weeks) traen el equipo DEL ULTIMO PARTIDO JUGADO. Un jugador traspasado
que aun no ha jugado con su nuevo equipo (p. ej. Jacoby Brissett: ARI -> BAL el 6-nov-2026, con semana de descanso en medio) seguia
proyectado con el equipo viejo y su nuevo equipo seguia viendo como QB a otro. Aqui:
  * `equipos_vigentes`: equipo actual segun el depth chart (nflverse, se actualiza a diario) para quien cambio de equipo y aun no juega con el nuevo.
  * `detectar`: todos los cambios de equipo de la temporada (ya jugaron con el nuevo equipo, o estan por hacerlo), con su rol actual.
  * `TRASPASOS_2026`: lista fija de los traspasos del periodo (hasta el cierre del martes 10-nov-2026 4 pm ET), verificada en ESPN / DAZN / SI.
    Incluye linea defensiva y ofensiva, que no entran al modelo de jugadores. Se cruza con los datos para avisar si el modelo ya los tiene bien.
  * `html_movimientos`: la seccion de la pagina.
"""
from __future__ import annotations

import html

import pandas as pd

# (fecha, jugador, posicion, de, a). Fuente: ESPN (trade deadline tracker), DAZN y SI.
TRASPASOS_2026 = [
    ("2026-11-10", "Ryan Neuzil", "C", "ATL", "BAL"), ("2026-11-10", "Andrew Vorhees", "OL", "BAL", "ATL"),
    ("2026-11-10", "Josh Downs", "WR", "IND", "KC"), ("2026-11-10", "Kirk Cousins", "QB", "LV", "MIN"),
    ("2026-11-10", "Amani Hooker", "S", "TEN", "BUF"), ("2026-11-10", "Keenan Allen", "WR", "IND", "SF"),
    ("2026-11-09", "Jordan Davis", "DT", "PHI", "JAX"), ("2026-11-09", "Davon Godchaux", "DT", "NO", "JAX"),
    ("2026-11-09", "Andre Cisco", "S", "NYJ", "DET"), ("2026-11-09", "Jessie Bates III", "S", "ATL", "JAX"),
    ("2026-11-06", "Jacoby Brissett", "QB", "ARI", "BAL"), ("2026-10-29", "Jeffery Simmons", "DT", "TEN", "CHI"),
    ("2026-10-27", "DeForest Buckner", "DT", "IND", "SF"), ("2026-10-27", "Quenton Nelson", "G", "IND", "SEA"),
    ("2026-10-12", "Marvin Harrison Jr.", "WR", "ARI", "HOU"), ("2026-10-07", "Cam Jurgens", "C", "PHI", "BAL"),
    ("2026-10-01", "Joey Porter Jr.", "CB", "PIT", "DAL"), ("2026-09-28", "J.J. McCarthy", "QB", "MIN", "NYG"),
]
FUENTE_TRASPASOS = "ESPN, DAZN y SI (cierre de traspasos: martes 10 de noviembre de 2026, 4 p. m. ET)"
SKILL = ("QB", "RB", "WR", "TE")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _norm(s) -> str:
    try:
        from fuentes_web import nombre_norm
        return nombre_norm(s)
    except Exception:
        return str(s).lower().replace(".", "").strip()


def _dep_por_id(depth: pd.DataFrame) -> pd.DataFrame:
    if depth is None or len(depth) == 0:
        return pd.DataFrame(columns=["gsis_id", "team", "pos_abb", "pos_rank"]).set_index("gsis_id")
    d = depth.dropna(subset=["gsis_id"]).sort_values("pos_rank").drop_duplicates("gsis_id")
    return d.set_index("gsis_id")[["team", "pos_abb", "pos_rank"]]


def equipos_vigentes(pw: pd.DataFrame, depth: pd.DataFrame, cur: int) -> dict:
    """{gsis_id: equipo actual} solo para jugadores de esta temporada cuyo depth chart los pone en un equipo distinto al de su ultimo partido."""
    last = pw[pw.season == cur].sort_values("week").drop_duplicates("player_id", keep="last").set_index("player_id").team
    dep = _dep_por_id(depth)
    out = {}
    for pid, r in dep.iterrows():
        if pid in last.index and last[pid] != r.team and isinstance(r.team, str) and r.team:
            out[pid] = r.team
    return out


def _uso(d: pd.DataFrame) -> str:
    """Resumen de uso por partido (pases/acarreos/targets) de un tramo de partidos."""
    if d.empty:
        return ""
    g = len(d)
    partes = []
    for col, txt in (("att", "pases"), ("car", "acarreos"), ("tgt", "targets")):
        if col in d and d[col].sum() / g >= (8 if col == "att" else 2):
            partes.append(f"{d[col].sum() / g:.0f} {txt}/partido")
    return ", ".join(partes)


def detectar(pw: pd.DataFrame, depth: pd.DataFrame, cur: int) -> pd.DataFrame:
    """Cambios de equipo de la temporada. Columnas: player_id, name, position, de, a, semana (primer partido con el nuevo equipo, NaN si aun no),
    estado, rol (depth actual), uso_antes, uso_despues."""
    p = pw[pw.season == cur].sort_values("week")
    dep = _dep_por_id(depth)
    filas = []
    for pid, d in p.groupby("player_id"):
        t = d.team.tolist()
        for i in range(1, len(t)):
            if t[i] != t[i - 1]:
                antes, despues = d.iloc[:i], d.iloc[i:]
                filas.append({"player_id": pid, "name": d.name.iloc[-1], "position": d.position.iloc[-1], "de": t[i - 1], "a": t[i],
                              "semana": int(d.week.iloc[i]), "estado": "ya jugó con su nuevo equipo",
                              "uso_antes": _uso(antes.tail(4)), "uso_despues": _uso(despues)})
    ya = {(f["player_id"], f["a"]) for f in filas}
    last = p.drop_duplicates("player_id", keep="last").set_index("player_id")
    for pid, r in dep.iterrows():
        if pid in last.index and last.at[pid, "team"] != r.team and isinstance(r.team, str) and (pid, r.team) not in ya:
            d = p[p.player_id == pid]
            filas.append({"player_id": pid, "name": last.at[pid, "name"], "position": last.at[pid, "position"], "de": last.at[pid, "team"], "a": r.team,
                          "semana": float("nan"), "estado": "aún no juega con su nuevo equipo", "uso_antes": _uso(d.tail(4)), "uso_despues": ""})
    df = pd.DataFrame(filas, columns=["player_id", "name", "position", "de", "a", "semana", "estado", "uso_antes", "uso_despues"])
    if df.empty:
        df["rol"] = []
        return df
    df["rol"] = [f"{dep.at[x, 'pos_abb']}{int(dep.at[x, 'pos_rank'])}" if x in dep.index else "" for x in df.player_id]
    return df


def cruzar_oficial(pw: pd.DataFrame, depth: pd.DataFrame, cur: int) -> pd.DataFrame:
    """La lista fija de traspasos contra lo que el modelo tiene: equipo actual del jugador en los datos y si coincide con el destino."""
    p = pw[pw.season == cur].sort_values("week")
    last = p.drop_duplicates("player_id", keep="last")
    por_nombre = {_norm(n): (pid, t) for pid, n, t in zip(last.player_id, last.name, last.team)}
    dep = _dep_por_id(depth)
    filas = []
    for fecha, nom, pos, de, a in TRASPASOS_2026:
        pid_t = por_nombre.get(_norm(nom))
        equipo = None
        if pid_t:
            pid, t = pid_t
            equipo = dep.at[pid, "team"] if pid in dep.index else t
        filas.append({"fecha": fecha, "jugador": nom, "position": pos, "de": de, "a": a, "equipo_modelo": equipo,
                      "en_modelo": pos in SKILL})
    return pd.DataFrame(filas)


def guardar(df: pd.DataFrame, log=print) -> None:
    """Foto diaria de los movimientos detectados (se acumula el historial en la base de datos)."""
    try:
        import db
        if len(df):
            db.agregar_foto("movimientos_jugadores", df.assign(semana=df.semana.astype("float"), fuente="nflverse depth", capturado=db._ahora()))
            db.marcar_descarga("movimientos_jugadores", len(df), "nflverse depth")
    except Exception as e:
        log(f"  [aviso] no pude guardar los movimientos ({e})")


def notas_por_juego(det: pd.DataFrame, res: pd.DataFrame, wk: int, nombre=lambda t: t) -> dict:
    """{game_id: texto} con los fichajes recientes (aun sin jugar con el nuevo equipo, o desde hace <= 2 semanas) de los dos equipos del partido."""
    if det is None or det.empty or res is None or res.empty:
        return {}
    d = det[det.position.isin(SKILL)]
    d = d[d.semana.isna() | (d.semana >= wk - 2)]
    d = d[d.rol.str.match(r"^(QB1|RB[12]|WR[123]|TE1)$", na=False) | d.semana.isna() & d.rol.str.match(r"^(QB[12]|RB[123]|WR[1-4]|TE[12])$", na=False)]
    out = {}
    for x in res.itertuples():
        partes = []
        for t in (x.away_team, x.home_team):
            for r in d[d.a == t].itertuples():
                partes.append(f"{r.name} ({r.position}, llegó de {nombre(r.de)} a {nombre(t)}" + ("; aún no juega con ellos" if pd.isna(r.semana) else "") + ")")
        if partes:
            out[x.game_id] = "Fichajes recientes: " + "; ".join(partes) + "."
    return out


# ------------------------------------------------------------------------------------------ HTML
def _fecha(s: str) -> str:
    d = pd.Timestamp(s)
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}"


def html_movimientos(det: pd.DataFrame, oficial: pd.DataFrame, nombre=lambda t: t) -> str:
    if (det is None or det.empty) and (oficial is None or oficial.empty):
        return ""
    filas = []
    if det is not None and len(det):
        d = det[det.position.isin(SKILL)].copy()
        d["_o"] = d.position.map({"QB": 0, "RB": 1, "WR": 2, "TE": 3}) * 10 + d.semana.fillna(99).clip(upper=90) / 10
        d = d.sort_values(["estado", "_o"], ascending=[True, True])
        for r in d.itertuples():
            cuando = "ya jugó con su nuevo equipo desde la semana " + f"{int(r.semana)}" if pd.notna(r.semana) else "todavía no juega con el nuevo equipo"
            alerta = "mv-p" if pd.isna(r.semana) else ""
            uso = ""
            if r.uso_antes:
                uso = f"antes: {html.escape(r.uso_antes)}"
            if r.uso_despues:
                uso += ("; " if uso else "") + f"ahora: {html.escape(r.uso_despues)}"
            filas.append(f'<tr class="{alerta}"><td class="l"><b>{html.escape(str(r.name))}</b></td><td>{r.position}</td>'
                         f'<td>{html.escape(nombre(r.de))} → <b>{html.escape(nombre(r.a))}</b></td><td>{html.escape(r.rol) or "fuera del depth chart"}</td>'
                         f'<td class="l">{cuando}<small>{uso}</small></td></tr>')
    tabla = ('<div class="scroll"><table class="mvt"><thead><tr><th class="l">Jugador</th><th>Pos.</th><th>De → a</th><th>Rol actual</th>'
             '<th class="l">Situación</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table></div>") if filas else \
        '<p class="explain">No detecté jugadores de ataque (QB, RB, WR, TE) con cambio de equipo esta temporada.</p>'
    lista = ""
    if oficial is not None and len(oficial):
        f2 = []
        for r in oficial.itertuples():
            if not r.en_modelo:
                est = '<span class="mv-n">defensa / línea: no entra al modelo de jugadores</span>'
            elif r.equipo_modelo is None:
                est = '<span class="mv-n">sin estadísticas esta temporada</span>'
            elif r.equipo_modelo == r.a:
                est = f'<span class="mv-ok">✔ el modelo ya lo usa con {html.escape(nombre(r.a))}</span>'
            else:
                est = f'<span class="mv-no">⚠ el modelo lo ubica en {html.escape(nombre(str(r.equipo_modelo)))}</span>'
            f2.append(f'<tr><td>{_fecha(r.fecha)}</td><td class="l"><b>{html.escape(r.jugador)}</b> <small>{r.position}</small></td>'
                      f'<td>{html.escape(nombre(r.de))} → <b>{html.escape(nombre(r.a))}</b></td><td class="l">{est}</td></tr>')
        lista = (f'<details class="sec"><summary>Lista de traspasos del periodo ({len(oficial)}): quién se movió a dónde</summary>'
                 '<div class="scroll"><table class="mvt"><thead><tr><th>Fecha</th><th class="l">Jugador</th><th>De → a</th><th class="l">En el modelo</th></tr></thead><tbody>'
                 + "".join(f2) + f'</tbody></table></div><p class="leyenda">Fuente: {html.escape(FUENTE_TRASPASOS)}. '
                 'Las filas se cruzan con los datos del programa para comprobar que cada jugador esté con su equipo nuevo.</p></details>')
    return f"""<h2 id="movimientos">Movimientos de jugadores (traspasos y fichajes)</h2>
<p class="explain">Las estadísticas de cada jugador traen el equipo de su <b>último partido</b>; si lo traspasaron y todavía no juega con el nuevo equipo, el modelo
seguiría proyectándolo con el viejo. Por eso el programa lee cada día el <b>depth chart actual</b> y usa ese equipo para los props, los touchdowns y para saber quién abre de mariscal.
Abajo, los jugadores de ataque que cambiaron de equipo esta temporada (detectados con los datos, incluyen fichajes y cortes) y la lista de traspasos hasta el cierre del 10 de noviembre.</p>
{tabla}{lista}"""


CSS = """
.mvt{width:100%;border-collapse:collapse;font-size:.86rem}.mvt th,.mvt td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:center;vertical-align:top}
.mvt td.l,.mvt th.l{text-align:left}.mvt small{display:block;color:var(--ink2);font-size:.74rem}.mvt tr.mv-p td{background:rgba(217,130,43,.12)}
.mv-ok{color:var(--yesink)}.mv-no{color:#b3261e;font-weight:600}.mv-n{color:var(--ink2)}
"""
