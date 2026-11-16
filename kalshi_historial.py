"""Historial de precios de Kalshi (mercados de props NFL ya liquidados) para medir al modelo CONTRA EL MERCADO.

Que baja (API publica de solo lectura, sin cuenta ni llave):
  1. La lista de mercados ya liquidados de las 9 series de props (zona «historical» + «settled» recientes), con su resultado.
  2. Para cada jugador-partido-mercado, los 2 escalones con mas volumen (los que estan mas cerca de «50-50»), y de cada uno
     sus velas por hora (bid y ask de cierre). Con eso se sabe cual era el precio ANTES del partido.
Guarda todo en data/kalshi_hist.db (se puede interrumpir y reanudar; solo baja lo que falta).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

import lineas_casas as LC
from data import DATA

RUTA = DATA / "kalshi_hist.db"
ESCALONES_POR_JUGADOR = 1
VOL_MIN = 50.0


def _con():
    c = sqlite3.connect(RUTA)
    c.execute("CREATE TABLE IF NOT EXISTS mercados (ticker TEXT PRIMARY KEY, event_ticker TEXT, serie TEXT, mercado TEXT, jugador TEXT, "
              "equipo TEXT, partido TEXT, fecha_juego TEXT, umbral REAL, linea REAL, volumen REAL, abre TEXT, cierra TEXT, resultado REAL, origen TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS velas (ticker TEXT PRIMARY KEY, ok INTEGER, datos TEXT)")
    return c


def _parsear(m: dict, serie: str, origen: str):
    try:
        if m.get("strike_type") not in ("greater", "structured") or m.get("floor_strike") is None or m.get("result") not in ("yes", "no"):
            return None
        ev = m["event_ticker"].split("-")[-1]
        mm = re.match(r"(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$", ev)
        eq = LC._partir_equipos(mm.group(4))
        if not eq:
            return None
        fecha = f"20{mm.group(1)}-{LC.MESES[mm.group(2)]:02d}-{mm.group(3)}"
        resto = m["ticker"].split("-")[2]
        propio = next((t for t in eq if resto.startswith(t)), None)
        return (m["ticker"], m["event_ticker"], serie, LC.KALSHI_SERIES[serie], m["yes_sub_title"].split(":")[0].strip(),
                LC._norm_equipo(propio) if propio else "", "-".join(LC._norm_equipo(t) for t in eq), fecha,
                float(m["floor_strike"]) + 0.5, float(m["floor_strike"]), LC._f(m.get("volume_fp")),
                m.get("open_time"), m.get("close_time"), 1.0 if m["result"] == "yes" else 0.0, origen)
    except Exception:
        return None


def bajar_mercados(log=print) -> int:
    con = _con()
    total = 0
    for serie in LC.KALSHI_SERIES:
        n_serie = 0
        for ruta, params, origen in (("/historical/markets", {}, "historical"), ("/markets", {"status": "settled"}, "settled")):
            cur = None
            for _ in range(60):
                q = dict(series_ticker=serie, limit=1000, **params)
                if cur:
                    q["cursor"] = cur
                j = LC._get(LC.KALSHI_BASES, ruta, q)
                filas = [r for r in (_parsear(m, serie, origen) for m in j.get("markets", [])) if r]
                con.executemany("INSERT OR REPLACE INTO mercados VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
                n_serie += len(filas)
                cur = j.get("cursor")
                if not cur:
                    break
        con.commit()
        total += n_serie
        log(f"  {serie}: {n_serie} escalones liquidados")
    con.close()
    return total


def _inicios() -> dict:
    """(fecha, equipo) -> segundo UTC en que empieza el partido (el calendario trae la hora de Nueva York)."""
    from zoneinfo import ZoneInfo
    import data as D
    g = D.load_schedules(False)
    et = ZoneInfo("America/New_York")
    out = {}
    for r in g.itertuples():
        try:
            h, mi = (int(x) for x in str(r.gametime).split(":")[:2])
            dia = pd.Timestamp(r.gameday).strftime("%Y-%m-%d")
            ts = int(dt.datetime.fromisoformat(dia).replace(hour=h, minute=mi, tzinfo=et).timestamp())
        except Exception:
            continue
        out[(dia, r.home_team)] = ts
        out[(dia, r.away_team)] = ts
    return out


def elegir_escalones() -> pd.DataFrame:
    """Un escalon por jugador-partido-mercado: el DEL MEDIO de la escalera que ya estaba publicada ANTES del partido.
    (Elegir por volumen sesgaria la muestra: en pleno partido se opera mas en los escalones que se estan cumpliendo.)"""
    con = _con()
    d = pd.read_sql("SELECT * FROM mercados WHERE abre IS NOT NULL", con)
    con.close()
    ko = _inicios()
    d["ko"] = [ko.get((f, e)) for f, e in zip(d.fecha_juego, d.equipo)]
    d = d.dropna(subset=["ko"])
    d = d[d.abre.map(_iso) <= d.ko]
    d = d.sort_values(["event_ticker", "serie", "jugador", "umbral"])
    g = d.groupby(["event_ticker", "serie", "jugador"])
    d["pos"], d["n"] = g.cumcount(), g.umbral.transform("size")
    return d[d.pos == (d.n - 1) // 2].drop(columns=["pos", "n", "ko"])


def _iso(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _velas(serie: str, ticker: str, abre: str, cierra: str, origen: str):
    q = {"start_ts": _iso(abre) - 3600, "end_ts": _iso(cierra) + 3600, "period_interval": 60}
    rutas = ([f"/historical/markets/{ticker}/candlesticks", f"/series/{serie}/markets/{ticker}/candlesticks"] if origen == "historical"
             else [f"/series/{serie}/markets/{ticker}/candlesticks", f"/historical/markets/{ticker}/candlesticks"])
    ultimo = None
    for r in rutas:
        try:
            j = LC._get(LC.KALSHI_BASES[:1], r, q, intentos=4)
            out = []
            for c in j.get("candlesticks", []):
                # la zona «settled» usa claves *_dollars / volume_fp; la «historical» usa close / volume
                g = lambda d, k: (d or {}).get(k + "_dollars", (d or {}).get(k))
                b, a, p = g(c.get("yes_bid"), "close"), g(c.get("yes_ask"), "close"), g(c.get("price"), "close")
                out.append([c["end_period_ts"], LC._f(b), LC._f(a), LC._f(p), LC._f(c.get("volume_fp", c.get("volume")))])
            return out
        except Exception as e:
            ultimo = e
    raise RuntimeError(ultimo)


def bajar_velas(log=print, max_minutos: float = 40.0, hilos: int = 6) -> dict:
    """Baja las velas en paralelo (varias consultas a la vez); reanuda donde se quedo."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    esc = elegir_escalones()
    con = _con()
    hechos = {r[0] for r in con.execute("SELECT ticker FROM velas")}
    pend = esc[~esc.ticker.isin(hechos)].sort_values("fecha_juego", ascending=False)
    log(f"  Escalones elegidos: {len(esc)}; por bajar: {len(pend)}")
    t0, n, mal = time.time(), 0, 0
    filas = list(pend.itertuples())

    def uno(r):
        try:
            return r.ticker, 1, json.dumps(_velas(r.serie, r.ticker, r.abre, r.cierra, r.origen))
        except Exception as e:
            return r.ticker, 0, str(e)[:200]

    lote = hilos * 25
    for k in range(0, len(filas), lote):
        if time.time() - t0 > max_minutos * 60:
            break
        with ThreadPoolExecutor(hilos) as ex:
            for fu in as_completed([ex.submit(uno, r) for r in filas[k:k + lote]]):
                t, ok, dat = fu.result()
                con.execute("INSERT OR REPLACE INTO velas VALUES (?,?,?)", (t, ok, dat))
                n += 1
                if not ok:
                    mal += 1
                    if mal <= 3:
                        log(f"  [aviso] velas {t}: {dat}")
        con.commit()
        if (k // lote) % 4 == 0:
            log(f"  ... {n} de {len(filas)} ({(time.time() - t0) / 60:.1f} min, {mal} fallidos)")
    con.commit()
    con.close()
    return {"bajados": n, "fallidos": mal, "pendientes": max(len(filas) - n, 0)}


def reparar(log=print) -> int:
    """Borra las velas que hay que volver a bajar: las de la zona «historical» (se leian mal) y las rechazadas por limite de velocidad (429)."""
    con = _con()
    n = con.execute("DELETE FROM velas WHERE ticker IN (SELECT ticker FROM mercados WHERE origen = 'historical') "
                    "OR (ok = 0 AND datos LIKE '%429%')").rowcount
    con.commit()
    con.close()
    log(f"  velas por volver a bajar: {n}")
    return n


def cargar() -> pd.DataFrame:
    """Un renglon por escalon con precio antes del partido: `velas` = lista [ts, bid, ask, precio, volumen] por hora."""
    con = _con()
    d = pd.read_sql("SELECT m.*, v.datos FROM mercados m JOIN velas v ON v.ticker = m.ticker WHERE v.ok = 1", con)
    con.close()
    d["velas"] = d.datos.map(json.loads)
    return d.drop(columns="datos")


if __name__ == "__main__":
    print(bajar_mercados())
    print(bajar_velas())
