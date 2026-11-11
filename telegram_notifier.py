"""Envío a Telegram con división correcta de mensajes largos."""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime
from typing import Iterable, List, Optional

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

LIMITE = 4000  # Telegram admite 4096; dejamos margen


def _cortar(txt: str, n: int) -> List[str]:
    return [txt[i : i + n] for i in range(0, max(len(txt), 1), n)]


def empaquetar(items: Iterable[str], sep: str = "\n", max_len: int = LIMITE) -> List[str]:
    """Junta items en mensajes de hasta max_len sin partir un item (salvo que solo él exceda el límite)."""
    partes: List[str] = []
    actual = ""
    for item in items:
        for trozo in _cortar(item, max_len):
            candidato = f"{actual}{sep}{trozo}" if actual else trozo
            if len(candidato) > max_len:
                partes.append(actual)
                actual = trozo
            else:
                actual = candidato
    if actual:
        partes.append(actual)
    return partes


def dividir_mensaje(texto: str, max_len: int = LIMITE) -> List[str]:
    """Parte cualquier texto largo por líneas (sirve para la salida de la IA, que no tiene separadores fijos)."""
    if len(texto) <= max_len:
        return [texto]
    return empaquetar(texto.split("\n"), "\n", max_len)


def md_a_html(texto: str) -> str:
    """Convierte el Markdown típico de una IA al HTML básico que acepta Telegram."""
    t = html.escape(texto, quote=False)
    t = re.sub(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", r"<b>\1</b>", t, flags=re.M)
    t = re.sub(r"^\s*[\*\-]\s+", "• ", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return t


def _sin_html(texto: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def _post(payload: dict) -> requests.Response:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code == 429:  # límite de envío: esperar lo que pida Telegram
        try:
            espera = float(r.json().get("parameters", {}).get("retry_after", 3))
        except (ValueError, AttributeError):
            espera = 3.0
        time.sleep(min(espera, 30))
        r = requests.post(url, json=payload, timeout=15)
    return r


def enviar_mensaje_telegram(texto: str, es_html: bool = False) -> bool:
    """Envía `texto`. Si es_html, cada parte se intenta como HTML y, si Telegram la rechaza, como texto plano."""
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en el entorno.")
        return False

    partes = dividir_mensaje(texto)
    ok_total = True
    for i, parte in enumerate(partes, 1):
        try:
            payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": parte, "disable_web_page_preview": True}
            if es_html:
                payload["parse_mode"] = "HTML"
            r = _post(payload)
            if r.status_code != 200 and es_html:
                log.warning("Parte %d rechazada con HTML (%s); reenvío como texto plano.", i, r.status_code)
                payload.pop("parse_mode")
                payload["text"] = _sin_html(parte)
                r = _post(payload)
            if r.status_code == 200:
                log.info("Telegram: parte %d/%d enviada.", i, len(partes))
            else:
                log.error("Telegram: parte %d falló (%s): %s", i, r.status_code, r.text[:200])
                ok_total = False
        except requests.exceptions.RequestException as e:
            log.error("Telegram: error de red en parte %d: %s", i, type(e).__name__)
            ok_total = False
    return ok_total


def _fmt(valor, decimales: int = 2, signo: bool = False) -> str:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return "n/d"
    if isinstance(valor, (int, float)):
        return f"{valor:+.{decimales}f}" if signo else f"{valor:.{decimales}f}"
    return html.escape(str(valor))


def construir_bloques_resumen(df_top: pd.DataFrame) -> List[str]:
    """Un bloque HTML por estrategia: la mejor de cada una (df_top ya viene rankeado)."""
    mejores = df_top.groupby("Estrategia", sort=False).head(1)
    esc_cols = [c for c in df_top.columns if c.startswith("Escenario")]
    bloques = []
    for _, r in mejores.iterrows():
        esc = " ".join(f"{c.replace('Escenario ', '')}:{_fmt(r[c], 1)}" for c in esc_cols)
        lineas = [
            f"<b>{html.escape(str(r['Estrategia']))}</b> · {html.escape(str(r['Subyacente / Ticker']))} · {html.escape(str(r['Vencimiento(s)']))}",
            f"<code>{html.escape(str(r['Strikes']))}</code>",
            f"Éxito {_fmt(r.get('Prob. Éxito (%)'), 1)}% · R/R {_fmt(r.get('Ratio R/R'))} · "
            f"TNA esp. {_fmt(r.get('TNA Esperada (%)'), 1)}% · Score {_fmt(r.get('Score Cuanti'), 1, True)}",
            f"Capital {_fmt(r.get('Capital Comprometido'))} · Pérd.máx {_fmt(r.get('Pérdida Máxima'))} · "
            f"Gan.máx {_fmt(r.get('Ganancia Máxima'))}",
            f"BE {_fmt(r.get('Punto de Equilibrio (Break-even)'))}",
        ]
        if "Tasa Implícita (%)" in r.index and pd.notna(r["Tasa Implícita (%)"]):
            lineas.append(f"Tasa implícita {_fmt(r['Tasa Implícita (%)'], 1)}%")
        if esc:
            lineas.append(f"<code>{esc}</code>")
        bloques.append("\n".join(lineas))
    return bloques


def enviar_resumen_telegram(
    df_top: pd.DataFrame,
    tasa_libre_pct: float,
    texto_ia: Optional[str] = None,
    proveedor_ia: Optional[str] = None,
) -> bool:
    """Resumen del ranking (mejor de cada estrategia) y, si existe, el informe de la IA."""
    if df_top is None or df_top.empty:
        return enviar_mensaje_telegram("⚠️ Sin estrategias viables en esta rueda.")

    cab = (
        f"⚡ <b>REPORTE CUANTITATIVO BYMA</b> · {datetime.now():%d/%m/%Y %H:%M}\n"
        f"Tasa libre de referencia: {tasa_libre_pct:.1f}%\n"
        "Mejor de cada estrategia · Éxito = prob. de superar la tasa libre (vol. histórica, sin sesgo direccional)"
    )
    bloques = [cab] + construir_bloques_resumen(df_top)
    if config.MODO_PRECIO == "last":
        nota = (
            f"Precios: último operado ±{config.SLIPPAGE_PCT * 100:.1f}% de slippage; confirmar contra el libro "
            "antes de operar."
        )
    else:
        nota = "Precios ejecutables (ask/bid)."
    bloques.append(f"<i>{nota} No es asesoramiento financiero.</i>")
    ok = True
    for mensaje in empaquetar(bloques, sep="\n\n"):
        ok &= enviar_mensaje_telegram(mensaje, es_html=True)

    if texto_ia:
        encabezado = f"🤖 <b>ANÁLISIS DE MERCADO</b> ({html.escape(proveedor_ia or 'IA')})\n\n"
        # Se parte el texto CRUDO y luego se convierte cada parte (así no se corta una etiqueta HTML a la mitad)
        partes = dividir_mensaje(texto_ia, LIMITE - 400)
        for i, parte in enumerate(partes):
            ok &= enviar_mensaje_telegram((encabezado if i == 0 else "") + md_a_html(parte), es_html=True)
    else:
        ok &= enviar_mensaje_telegram("ℹ️ Informe de IA no disponible en esta corrida (se envió solo el ranking).")
    return ok
