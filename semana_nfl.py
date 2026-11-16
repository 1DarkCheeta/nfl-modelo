"""
 SEMANA NFL  -  abre este archivo en IDLE y pulsa F5 (Run > Run Module).

 Cada vez que lo ejecutes:
   1. Descarga los datos mas recientes (la primera vez tarda ~1-2 minutos).
   2. Calcula las probabilidades de la proxima semana con lineas publicadas.
   3. Crea un reporte con graficos en la carpeta "reportes" y lo abre en tu navegador.
   4. Guarda tambien un CSV en "outputs" y la semana en "historial".
   5. Todo se guarda en la base de datos SQL data/nfl.db (ver base_datos.py para consultarla).

 Puedes cambiar estas opciones:
"""
SEMANA = None            # None = la proxima semana con partidos pendientes; o escribe un numero, p. ej. 8
UMBRAL_VENTAJA = 0.02    # ventaja minima (0.02 = 2 puntos de probabilidad) para marcar "posible valor"
ACTUALIZAR_DATOS = True  # False = usa solo los datos ya descargados (sin internet)

import os
import subprocess
import sys
import traceback
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

PAQUETES = {"pandas": "pandas", "numpy": "numpy", "scipy": "scipy", "sklearn": "scikit-learn", "matplotlib": "matplotlib"}


def instalar_faltantes():
    faltan = []
    for modulo, pip_name in PAQUETES.items():
        try:
            __import__(modulo)
        except ImportError:
            faltan.append(pip_name)
    if faltan:
        print("Instalando paquetes que faltan:", ", ".join(faltan), "(solo la primera vez)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *faltan])


def main():
    instalar_faltantes()
    from predict import compute, guardar_historial, tabla_csv
    from reporte import construir

    print("Descargando datos y calculando (puede tardar un minuto)...")
    try:
        r = compute(ACTUALIZAR_DATOS, SEMANA, False, UMBRAL_VENTAJA)
    except Exception as e:
        if not ACTUALIZAR_DATOS:
            raise
        print(f"\nNo pude descargar datos nuevos ({e}).\nUso los datos que ya estaban guardados.")
        r = compute(False, SEMANA, False, UMBRAL_VENTAJA)

    if r["res"].empty:
        print("\nNo hay partidos pendientes con linea publicada (puede ser fuera de temporada o las casas aun no publican).")
        return

    res, cur, wk = r["res"], r["cur"], r["week"]
    guardar_historial(res, cur, wk)
    csv = AQUI / "outputs" / f"probabilidades_{cur}_semana{wk}.csv"
    tabla_csv(res, UMBRAL_VENTAJA).to_csv(csv, index=False)
    extras = None
    try:
        import extras as EX
        extras = EX.calcular(r, ACTUALIZAR_DATOS)
        pcsv = AQUI / "outputs" / f"props_{cur}_semana{wk}.csv"
        EX.csv_props(extras["P"]).to_csv(pcsv, index=False)
        print("Props    :", pcsv)
        tcsv = AQUI / "outputs" / f"touchdowns_{cur}_semana{wk}.csv"
        EX.csv_td(extras["P"], extras.get("cres"), cur).to_csv(tcsv, index=False)
        print("Touchdowns:", tcsv)
        vcsv = AQUI / "outputs" / f"valor_kalshi_{cur}_semana{wk}.csv"
        vv = EX.csv_valor_casas(extras.get("V"))
        if len(vv):
            vv.to_csv(vcsv, index=False)
            print("Kalshi vs modelo:", vcsv)
    except Exception:
        print("\n[aviso] No pude calcular props/matchups (el reporte de equipos sigue funcionando). Detalle:")
        traceback.print_exc()
    try:
        import db
        n = db.guardar_historial(res, extras["P"] if extras else None, cur, wk)
        print(f"Base de datos: {db.RUTA}  (lineas nuevas: {n.get('lineas', 0)}, predicciones: {n.get('predicciones', 0)}, "
              f"props: {n.get('props', 0)})")
    except Exception:
        print("\n[aviso] No pude guardar el historial en la base de datos (el reporte sigue funcionando). Detalle:")
        traceback.print_exc()
    ruta = construir(r, extras=extras)

    n_val = sum(int((res[f"{k}_edge"] >= UMBRAL_VENTAJA).sum()) for k in ("sp", "to", "ml"))
    print(f"\nListo. Temporada {cur}, semana {wk}: {len(res)} partidos, {n_val} posible(s) valor(es).")
    print("Reporte :", ruta)
    print("CSV     :", csv)
    try:                                   # copia el reporte a la carpeta docs/ (la pagina web); no borra nada
        import publicar_web
        publicar_web.publicar(ruta)
    except Exception:
        print("\n[aviso] No pude preparar la pagina web (el reporte normal sigue funcionando). Detalle:")
        traceback.print_exc()
    if not os.environ.get("NFL_SIN_NAVEGADOR"):    # en la nube no hay navegador que abrir
        webbrowser.open(ruta.as_uri())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n*** Ocurrio un error. Copia el texto de abajo si necesitas ayuda ***\n")
        traceback.print_exc()
