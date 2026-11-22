"""Alertas gratis al celular: avisa por Telegram (y/o ntfy) cuando aparece un posible valor NUEVO.

Lo corre el workflow "Reporte NFL" justo despues del modelo. No calcula nada: solo lee el CSV que ya guardo predict.py
(historial/prob_<temporada>_s<semana>.csv) y manda los partidos con ventaja >= umbral (el mismo min_edge del modelo).

Para que se acuerde de lo que ya aviso (y no repita) guarda historial/avisos_enviados.json; el workflow lo conserva
en la rama "datos" junto con el resto del historial.

Destinos (todos opcionales; sin ninguno, no hace nada y no falla). Se configuran como "secrets" del repositorio en GitHub:
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID     (bot creado con @BotFather)
  NTFY_TOPIC  [+ NTFY_SERVER, por defecto https://ntfy.sh]   (app ntfy, sin cuenta)

Uso a mano:  python avisos.py --dry-run      (muestra el mensaje y no manda ni guarda nada)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from odds_fmt import a_dec, fd
from web_extra import tamano_u

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "historial"
ESTADO = HIST / "avisos_enviados.json"
SITIO = os.environ.get("SITE_URL", "https://1darkcheeta.github.io/nfl-modelo/")
MERCADOS = (("sp", "Spread"), ("to", "Total de puntos"), ("ml", "Ganador"))


def _lt(s: str) -> str:
    return str(s).replace("OVER", "Más de").replace("UNDER", "Menos de")


def _hoy_cdmx():
    return (datetime.now(timezone.utc) - timedelta(hours=6)).date()


def candidatos(csv: Path, hoy=None) -> list[dict]:
    """Elecciones con ventaja >= umbral de partidos que aun no pasan (por fecha)."""
    d = pd.read_csv(csv)
    hoy = hoy or _hoy_cdmx()
    out = []
    for r in d.itertuples(index=False):
        try:
            if pd.to_datetime(r.gameday).date() < hoy:
                continue
        except Exception:
            pass
        me = float(getattr(r, "min_edge", 0.02) or 0.02)
        for k, t in MERCADOS:
            if k == "ml" and not bool(r.tiene_ml):
                continue
            e = getattr(r, f"{k}_edge")
            if e != e or e < me:
                continue
            lado = getattr(r, f"{k}_lado")
            lab = f"{str(lado).replace(' ML', '')} gana" if k == "ml" else _lt(lado)
            cuota = float(getattr(r, f"{k}_cuota"))
            p = float(getattr(r, f"{k}_p"))
            out.append({"clave": f"{r.game_id}|{k}|{lado}", "mercado": t, "partido": f"{r.away_team} @ {r.home_team}", "lab": lab,
                        "cuota": fd(cuota), "ventaja": e * 100, "u": tamano_u(p, float(a_dec(cuota))), "dia": str(r.gameday)[:10]})
    out.sort(key=lambda x: (x["dia"], -x["ventaja"]))
    return out


def mensaje(nuevos: list[dict], semana) -> str:
    L = [f"🏈 NFL semana {semana}: {len(nuevos)} posible{'s' if len(nuevos) != 1 else ''} valor{'es' if len(nuevos) != 1 else ''} nuevo{'s' if len(nuevos) != 1 else ''}", ""]
    for x in nuevos:
        tam = f" · tamaño sugerido {x['u']:g} u" if x["u"] else ""
        L.append(f"• {x['mercado']} · {x['partido']} ({x['dia']})\n  {x['lab']} · cuota {x['cuota']} · ventaja {x['ventaja']:+.1f} pts{tam}")
    L += ["", "Es un modelo estadístico: no es garantía ni asesoría financiera. 1 u = 1 % de tu banca.", f"Detalle: {SITIO}"]
    return "\n".join(L)[:3900]


def _post(url: str, data: bytes, headers: dict, secreto: str = "") -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None          # sin la URL: llevaria el token del bot
    except Exception as e:
        raise RuntimeError(type(e).__name__) from None


def enviar(texto: str) -> list[str]:
    """Manda el texto a los destinos configurados. Devuelve los nombres de los que lo recibieron."""
    ok = []
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        body = urllib.parse.urlencode({"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}).encode()
        try:
            _post(f"{base}/bot{tok}/sendMessage", body, {"Content-Type": "application/x-www-form-urlencoded"})
            ok.append("telegram")
        except RuntimeError as e:
            print(f"[avisos] Telegram falló ({e}).")
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        srv = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        try:
            _post(f"{srv}/{urllib.parse.quote(topic)}", texto.encode("utf-8"),
                  {"Title": "NFL: posible valor nuevo", "Click": SITIO, "Tags": "football", "Content-Type": "text/plain; charset=utf-8"})
            ok.append("ntfy")
        except RuntimeError as e:
            print(f"[avisos] ntfy falló ({e}).")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="muestra el mensaje sin mandarlo ni guardar nada")
    a = ap.parse_args(argv)
    csvs = sorted(glob.glob(str(HIST / "prob_*_s*.csv")))
    if not csvs:
        print("[avisos] No hay historial de la semana; nada que avisar.")
        return 0
    csv = Path(csvs[-1])
    semana = csv.stem.rsplit("_s", 1)[-1].lstrip("0") or "0"
    try:
        enviados = set(json.loads(ESTADO.read_text(encoding="utf-8")).get("claves", []))
    except Exception:
        enviados = set()
    cand = candidatos(csv)
    nuevos = [x for x in cand if x["clave"] not in enviados]
    print(f"[avisos] {len(cand)} elecciones con ventaja, {len(nuevos)} nuevas.")
    if not nuevos:
        return 0
    txt = mensaje(nuevos, semana)
    if a.dry_run:
        print(txt)
        return 0
    if not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")) and not os.environ.get("NTFY_TOPIC"):
        print("[avisos] Sin destino configurado (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, o NTFY_TOPIC): no se envía nada.")
        return 0
    if enviar(txt):
        HIST.mkdir(exist_ok=True)
        ESTADO.write_text(json.dumps({"claves": sorted(enviados | {x["clave"] for x in nuevos})}, ensure_ascii=False, indent=0), encoding="utf-8")
        print("[avisos] Aviso enviado.")
    else:
        print("[avisos] No se pudo enviar a ningún destino; se volverá a intentar en la próxima corrida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
