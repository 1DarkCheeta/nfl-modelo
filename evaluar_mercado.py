"""
 MODELO vs MERCADO  -  abre este archivo en IDLE y pulsa F5.

 Compara las probabilidades del modelo con los precios de Kalshi justo antes de cada partido ya jugado, y crea el reporte
 reportes/modelo_vs_mercado.html (error, calibracion, apuestas simuladas, movimiento del precio).

 Cada vez que lo corres, primero baja los precios de los partidos que faltan (rapido si ya corriste antes) y luego evalua.
 Hazlo de vez en cuando (p. ej. cada semana despues del lunes): con mas partidos las conclusiones son mas firmes.
"""
MINUTOS_DESCARGA = 15      # maximo de minutos para bajar precios nuevos de Kalshi en cada corrida

import sys
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))


def main():
    import pandas as pd
    import data as D
    import kalshi_historial as KH
    import mercado_eval as ME
    import props as P
    import reporte_mercado as RM
    from jugadores_data import FIRST_PLAYER_SEASON, load_player_weeks

    print("Precios de Kalshi de partidos ya jugados ...")
    try:
        print("  escalones liquidados:", KH.bajar_mercados(log=print))
        print(" ", KH.bajar_velas(log=print, max_minutos=MINUTOS_DESCARGA))
    except Exception as e:
        print(f"  [aviso] no pude actualizar Kalshi ({e}); uso lo ya guardado")

    games = D.load_schedules(False)
    cur = int(games[games.result.notna()].season.max())
    pw = load_player_weeks(range(FIRST_PLAYER_SEASON, cur + 1), refresh_seasons=())
    print("Predicciones del modelo hechas solo con datos anteriores (la primera vez tarda 2-4 minutos) ...")
    X, _, _ = P.construir_X(games, pw)
    O = ME.predicciones_oos_cache(X)
    H = KH.cargar()
    K = ME.precios_previos(H, games, pw)
    Dm = ME.probabilidad_modelo(K, O)
    res = ME.evaluar(Dm)
    d = res.pop("d")
    out = AQUI / "outputs"
    out.mkdir(exist_ok=True)
    d.drop(columns=["ticker"], errors="ignore").to_csv(out / "modelo_vs_mercado_detalle.csv", index=False, encoding="utf-8-sig")
    ruta = RM.construir(res, AQUI / "reportes" / "modelo_vs_mercado.html",
                        fuente=f"Datos: Kalshi, {res['semanas']} semanas de partidos.")
    g = res["global"]
    print(f"\nError Brier  mercado {g['mercado']['brier']:.4f}  modelo {g['modelo']['brier']:.4f}  mezcla 15% {g['mezcla_15']['brier']:.4f}  mezcla 25% {g['mezcla_25']['brier']:.4f}")
    print("Reporte:", ruta)
    webbrowser.open(ruta.as_uri())


if __name__ == "__main__":
    main()
