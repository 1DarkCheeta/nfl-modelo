"""
 MIS APUESTAS  -  abre este archivo en IDLE y pulsa F5.

 1) Registra tus apuestas (copiándolas desde el reporte semanal con el botón «copiar», o a mano).
 2) Las liquida solas con los resultados reales cuando terminan los partidos.
 3) Crea reportes/mis_apuestas.html: ganancia, ROI con su incertidumbre, acierto, calibración del modelo y CLV.

 Tus apuestas viven en data/mis_apuestas.csv (puedes abrirlo y corregirlo en Excel; guarda como CSV).
"""
import sys
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))


def _portapapeles() -> str:
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        t = r.clipboard_get()
        r.destroy()
        return t
    except Exception:
        return ""


def _ask(txt, default=""):
    v = input(f"{txt}" + (f" [{default}]" if default else "") + ": ").strip()
    return v or default


def liquidar_y_reportar(abrir=True):
    import apuestas as A
    import data as D
    import reporte_apuestas as RA
    from jugadores_data import FIRST_PLAYER_SEASON, load_player_weeks, load_snaps

    games = D.load_schedules(True)
    cur = int(games[games.result.notna()].season.max())
    d0 = A.cargar()
    if d0.empty:
        print("Aun no tienes apuestas registradas.")
    else:
        pw = load_player_weeks(range(FIRST_PLAYER_SEASON, cur + 1), refresh_seasons=(cur,))
        try:
            snaps = load_snaps(range(max(2013, cur - 1), cur + 1), refresh_seasons=(cur,))
        except Exception:
            snaps = None
        A.liquidar(games, pw, snaps)
    d = A.cargar()
    ruta = RA.construir(d, AQUI / "reportes" / "mis_apuestas.html")
    r = A.resumen(d)
    print(f"\nApuestas: {r['total']} (liquidadas {r['liquidadas']}, pendientes {r['pendientes']}).")
    if r["liquidadas"]:
        print(f"Monto {r['monto']:,.2f} | ganancia {r['ganancia']:+,.2f} | ROI {r['roi'] * 100:+.1f}% (intervalo 90%: {r['roi_lo90'] * 100:+.1f}% a {r['roi_hi90'] * 100:+.1f}%)")
    print("Reporte:", ruta)
    if abrir:
        webbrowser.open(ruta.as_uri())


def registrar_portapapeles():
    import apuestas as A
    filas = A.desde_portapapeles(_portapapeles())
    if not filas:
        print("No encontre apuestas copiadas. En el reporte semanal escribe tu linea y cuota, y pulsa «copiar» junto al resultado; luego vuelve aqui.")
        return
    print(f"Encontre {len(filas)} apuesta(s):")
    for f in filas:
        print(f"  - {f['jugador'] or f['equipo']} {f['mercado']} {f['lado']} {f['linea']} @ {f['cuota']}")
    monto = _ask("Monto de CADA una (en tu moneda)", "10")
    casa = _ask("Casa o plataforma (kalshi, draftkings, caliente, ...)", filas[0].get("casa") or "")
    for f in filas:
        f["monto"], f["casa"] = monto, casa or f.get("casa", "")
    A.agregar(filas)
    print("Guardadas.")


def registrar_a_mano():
    import apuestas as A
    tipo = _ask("Tipo (prop / ml / spread / total)", "prop").lower()
    f = {"tipo": tipo, "game_id": _ask("game_id (ej. 2026_09_CIN_ATL; esta en el CSV del reporte)")}
    gid = f["game_id"]
    import re
    m = re.match(r"(\d{4})_(\d{2})_", gid)
    if m:
        f["temporada"], f["semana"] = m.group(1), str(int(m.group(2)))
    f["equipo"] = _ask("Tu equipo (abreviatura, ej. CIN)").upper()
    if tipo == "prop":
        f["jugador"], f["player_id"] = _ask("Jugador"), _ask("player_id (opcional, en el CSV de props)")
        f["mercado"] = _ask("Mercado (pass_yds, rush_yds, rush_att, rec_yds, rec, td, ...)")
        f["lado"] = _ask("Lado (over / under / si / no)", "over").lower()
        f["linea"] = _ask("Linea (ej. 68.5)")
    elif tipo == "ml":
        f["lado"] = "equipo"
        f["mercado"] = "ml"
    elif tipo == "spread":
        f["lado"], f["mercado"], f["linea"] = "equipo", "spread", _ask("Handicap de TU equipo (ej. -3.5 o +6.5)")
    else:
        f["lado"], f["mercado"], f["linea"] = _ask("over / under", "over").lower(), "total", _ask("Linea de puntos (ej. 44.5)")
    f["cuota"] = _ask("Cuota (americana +150 / -110, o precio de Kalshi 44c)")
    f["casa"] = _ask("Casa o plataforma")
    f["monto"] = _ask("Monto", "10")
    p = _ask("Probabilidad que te daba el modelo (0-1, opcional)")
    if p:
        f["prob_modelo"] = p
    f["cierre"] = _ask("Cuota de cierre si la sabes (opcional)")
    A.agregar([f])
    print("Guardada.")


def main():
    try:
        liquidar_y_reportar(abrir=False)
    except Exception as e:
        print(f"[aviso] no pude liquidar ahora ({e})")
    while True:
        print("\n1) Registrar apuestas copiadas del reporte (portapapeles)\n2) Registrar una apuesta a mano\n3) Liquidar y ver mis resultados\n4) Salir")
        op = input("Elige: ").strip()
        if op == "1":
            registrar_portapapeles()
        elif op == "2":
            registrar_a_mano()
        elif op == "3":
            liquidar_y_reportar()
        elif op == "4":
            break


if __name__ == "__main__":
    main()
