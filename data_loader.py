"""Descarga y normaliza la cadena de opciones de BYMA."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

log = logging.getLogger(__name__)

# columna destino -> (campo en el JSON, valor por defecto)
CAMPOS_NUM: Dict[str, Tuple[str, float]] = {
    "dias_vto": ("dias_vto", 0.0),
    "lote": ("lote", 100.0),
    "suby_px": ("suby_px", 0.0),
    "strike": ("strike", 0.0),
    "bid": ("bid", 0.0),
    "ask": ("ask", 0.0),
    "last": ("ultimo", 0.0),  # OJO: en el JSON es "ultimo"; en el DataFrame es "last"
    "apertura": ("apertura", 0.0),
    "minimo": ("minimo", 0.0),
    "maximo": ("maximo", 0.0),
    "cant_ops": ("cant_ops", 0.0),
    "precio_teorico": ("precio_teorico", 0.0),
    "valor_intrinseco": ("valor_intrinseco", 0.0),
    "valor_temporal": ("valor_temporal", 0.0),
    "desvio_teorico": ("desvio_teorico", 0.0),
    "desvio_teorico_pct": ("desvio_teorico_pct", 0.0),
    "dist": ("dist", 0.0),
    "delta": ("delta", 0.0),
    "gamma": ("gamma", 0.0),
    "theta": ("theta", 0.0),
    "vega": ("vega", 0.0),
    "rho": ("rho", 0.0),
    "vol_impl": ("vol_impl", 0.0),
    "vol_hist": ("vol_hist", 0.0),
    "iv_hv": ("iv_hv", 0.0),
    "open_interest": ("open_interest", 0.0),
    "oi_nocional": ("oi_nocional", 0.0),
    "vol_ef": ("vol_ef", 0.0),
    "var_prima": ("var_prima", 0.0),
    "var_oi": ("var_oi", 0.0),
}
CAMPOS_TXT = ["seccion", "moneyness", "hora", "iv_estado", "tasa_ticker", "subyacente_nombre"]


def _num(valor: Any, defecto: Optional[float] = 0.0) -> Optional[float]:
    """float tolerante: acepta '1,5', None, '' y NaN."""
    if valor is None or valor == "":
        return defecto
    try:
        x = float(str(valor).replace(",", ".")) if isinstance(valor, str) else float(valor)
    except (TypeError, ValueError):
        return defecto
    return x if x == x else defecto


def _normalizar_tipo(valor: Any) -> Optional[str]:
    t = str(valor or "").strip().upper()
    if t in ("CALL", "C"):
        return "CALL"
    if t in ("PUT", "P", "V"):
        return "PUT"
    return None


class BYMALoader:
    def __init__(self, url: str = config.BYMA_URL):
        self.url = url
        self.filas_crudas: List[dict] = []  # las reutiliza el exportador a Sheets (evita 2da descarga)

    def _sesion(self) -> requests.Session:
        s = requests.Session()
        reintentos = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        s.mount("https://", HTTPAdapter(max_retries=reintentos))
        s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://tablero.bymaeduca.com.ar/",
            }
        )
        return s

    def descargar(self) -> Any:
        try:
            resp = self._sesion().get(self.url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"Falló la descarga del JSON de opciones: {e}") from e

    @staticmethod
    def extraer_filas(datos: Any) -> List[dict]:
        """Soporta {"op": {"rows": [...]}}, cualquier {"x": {"rows": [...]}} o una lista."""
        if isinstance(datos, list):
            return [d for d in datos if isinstance(d, dict)]
        if isinstance(datos, dict):
            op = datos.get("op")
            if isinstance(op, dict) and op.get("rows"):
                return op["rows"]
            for v in datos.values():
                if isinstance(v, dict) and isinstance(v.get("rows"), list):
                    return v["rows"]
        return []

    def procesar(self, filas: List[dict]) -> Tuple[pd.DataFrame, Dict[str, float]]:
        registros, curva, descartadas = [], {}, 0
        for item in filas:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol") or ""
            tipo = _normalizar_tipo(item.get("tipo"))
            if not symbol or tipo is None:
                descartadas += 1
                continue

            vencimiento = item.get("vencimiento", "")
            tasa_raw = _num(item.get("tasa_libre"), None)
            if tasa_raw is None:
                tasa = config.TASA_LIBRE_DEFAULT_PCT / 100.0
            else:  # el feed la manda en % (ej. 29.62); se acepta también en decimal
                tasa = tasa_raw / 100.0 if tasa_raw > 1.0 else tasa_raw
            if vencimiento and vencimiento not in curva:
                curva[vencimiento] = tasa

            reg = {
                "symbol": symbol,
                "ticker_base": item.get("subyacente") or symbol[:4],
                "tipo": tipo,
                "vencimiento": vencimiento,
                "tasa_libre_riesgo": tasa,
            }
            for col in CAMPOS_TXT:
                reg[col] = item.get(col, "")
            for col, (campo, defecto) in CAMPOS_NUM.items():
                reg[col] = _num(item.get(campo), defecto)
            registros.append(reg)

        if descartadas:
            log.warning("Se descartaron %d filas sin symbol o con tipo distinto de CALL/PUT.", descartadas)
        df = pd.DataFrame(registros)
        log.info("Datos procesados: %d opciones, %d vencimientos con tasa.", len(df), len(curva))
        return df, curva

    def descargar_y_procesar(self) -> Tuple[pd.DataFrame, Dict[str, float]]:
        log.info("Conectando con BYMA para descargar opciones...")
        self.filas_crudas = self.extraer_filas(self.descargar())
        return self.procesar(self.filas_crudas)
