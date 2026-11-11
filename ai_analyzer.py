"""Informe con IA y respaldo entre proveedores.

Se prueban los proveedores de config.IA_PROVEEDORES en orden (los que no tienen
API key se saltean). Si uno falla por cuota (429) o error permanente, se pasa al
siguiente; los errores transitorios (5xx, timeout) se reintentan antes.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

# Columnas REALES que produce el motor (la versión anterior pedía columnas que no existían)
COLUMNAS_IA = [
    "Clasificación",
    "Estrategia",
    "Subyacente / Ticker",
    "Vencimiento(s)",
    "Strikes",
    "Capital Comprometido",
    "Pérdida Máxima",
    "Ganancia Máxima",
    "Punto de Equilibrio (Break-even)",
    "Prob. Éxito (%)",
    "Valor Esperado",
    "TNA Esperada (%)",
    "Tasa Implícita (%)",
    "Ratio R/R",
    "Delta Proxy",
    "Score Cuanti",
]


@dataclass
class AnalisisIA:
    texto: str
    proveedor: str


class ErrorIA(Exception):
    def __init__(self, mensaje: str, reintentable: bool = False):
        super().__init__(mensaje)
        self.reintentable = reintentable


def registros_para_ia(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """TODAS las filas recibidas (sin recortar) con las columnas útiles; NaN -> null."""
    cols = [c for c in COLUMNAS_IA if c in df.columns]
    return json.loads(df[cols].to_json(orient="records", force_ascii=False))


def _descripcion_precios() -> str:
    if config.MODO_PRECIO == "last":
        return (
            "Los precios son los ÚLTIMOS OPERADOS del día (no hay puntas), ajustados un "
            f"{config.SLIPPAGE_PCT * 100:.1f}% en contra para aproximar el spread: pueden estar "
            "desactualizados y hay que confirmarlos contra el libro antes de operar."
        )
    return "Los precios usados son ejecutables: ASK para compras y BID para ventas."


def construir_prompt(df: pd.DataFrame, tasa_libre_pct: float) -> str:
    datos = json.dumps(registros_para_ia(df), ensure_ascii=False, indent=1)
    return f"""Actuá como un operador cuantitativo experto en opciones del mercado argentino (BYMA).
Fecha del análisis: {datetime.now().strftime('%Y-%m-%d')}.
Tasa libre de riesgo de referencia: {tasa_libre_pct:.1f}% TNA.

Abajo hay las mejores estructuras de cada tipo de estrategia, ya rankeadas por el motor (cada
estrategia compite solo contra sí misma). Significado de las columnas:
- Prob. Éxito (%): probabilidad estimada de superar la tasa libre al vencimiento (modelo lognormal,
  volatilidad histórica, sin sesgo direccional).
- Valor Esperado: P&L esperado por unidad de subyacente al vencimiento.
- TNA Esperada (%): retorno esperado anualizado sobre el capital comprometido.
- Score Cuanti: exceso de TNA esperada sobre la tasa libre, en puntos porcentuales.
- Tasa Implícita (%): solo en arbitrajes de conversión/reversión.
- {_descripcion_precios()}

DATOS (JSON):
{datos}

Elaborá un informe ejecutivo y operativo, en español, con estas secciones:
1. Lectura de mercado: qué muestran las primas y las tasas implícitas frente a la tasa libre.
2. Mejores 2 o 3 oportunidades: elegilas SOLO de los datos y justificá el trade-off entre
   probabilidad, riesgo máximo y retorno esperado. Si ninguna ofrece ventaja clara, decilo.
3. Cómo armarlas paso a paso (patas, strikes, vencimiento) y puntos críticos de gestión del riesgo.

Reglas: usá únicamente los números del JSON, no inventes cifras; mencioná que las opciones de BYMA
son americanas (riesgo de ejercicio anticipado en patas vendidas) y que esto no es asesoramiento
financiero. Máximo 3000 caracteres.
"""


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------
def _revisar_status(r: requests.Response) -> None:
    if r.status_code == 200:
        return
    detalle = r.text[:300].replace("\n", " ")
    if r.status_code in (500, 502, 503, 504):
        raise ErrorIA(f"HTTP {r.status_code} (transitorio): {detalle}", reintentable=True)
    # 429 = cuota agotada: no sirve esperar, se pasa al próximo proveedor
    raise ErrorIA(f"HTTP {r.status_code}: {detalle}", reintentable=False)


def _llamar_gemini(cfg: dict, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['modelo']}:generateContent"
    r = requests.post(
        url,
        headers={"x-goog-api-key": cfg["api_key"]},  # en header, no en la URL
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=90,
    )
    _revisar_status(r)
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ErrorIA(f"Respuesta de Gemini sin texto: {e}") from e


def _llamar_openai(cfg: dict, prompt: str) -> str:
    r = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={"model": cfg["modelo"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
        timeout=90,
    )
    _revisar_status(r)
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ErrorIA(f"Respuesta sin texto: {e}") from e


_LLAMADORES = {"gemini": _llamar_gemini, "openai": _llamar_openai}


def _con_reintentos(cfg: dict, prompt: str, intentos: int = 3, espera: float = 5.0) -> str:
    llamar = _LLAMADORES[cfg["tipo"]]
    ultimo: Optional[Exception] = None
    for i in range(1, intentos + 1):
        try:
            texto = llamar(cfg, prompt)
            if not texto or not texto.strip():
                raise ErrorIA("Respuesta vacía")
            return texto.strip()
        except requests.exceptions.RequestException as e:  # timeout / conexión
            ultimo = ErrorIA(f"Red: {type(e).__name__}", reintentable=True)
        except ErrorIA as e:
            if not e.reintentable:
                raise
            ultimo = e
        if i < intentos:
            time.sleep(espera * 2 ** (i - 1))
    raise ultimo or ErrorIA("Error desconocido")


def analizar_estrategias(df: pd.DataFrame, tasa_libre_pct: float) -> Optional[AnalisisIA]:
    """Devuelve el informe y qué proveedor lo generó, o None si todos fallaron."""
    if df is None or df.empty:
        return None
    prompt = construir_prompt(df, tasa_libre_pct)
    for nombre in config.IA_PROVEEDORES:
        cfg = config.PROVEEDORES_IA.get(nombre)
        if not cfg or not cfg.get("api_key"):
            log.info("IA '%s' sin API key; se saltea.", nombre)
            continue
        try:
            log.info("Generando informe con %s (%s)...", nombre, cfg["modelo"])
            return AnalisisIA(_con_reintentos(cfg, prompt), nombre)
        except ErrorIA as e:
            log.warning("IA '%s' falló: %s. Pruebo el siguiente proveedor.", nombre, e)
    log.error("Ningún proveedor de IA pudo generar el informe.")
    return None
