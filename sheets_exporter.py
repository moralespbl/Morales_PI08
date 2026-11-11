"""Exportación a Google Sheets (opcional: si faltan credenciales se omite sin romper el pipeline)."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any, List, Optional

import pandas as pd

import config

log = logging.getLogger(__name__)

LIMITE_CELDA = 45_000  # Google Sheets admite 50.000 caracteres por celda


def _cliente():
    import gspread  # import perezoso: el resto del proyecto funciona sin gspread instalado

    if config.GOOGLE_CREDENTIALS_JSON:
        return gspread.service_account_from_dict(json.loads(config.GOOGLE_CREDENTIALS_JSON))
    return gspread.service_account(filename=config.GOOGLE_CREDENTIALS_FILE)


def _celda(v: Any) -> Any:
    """Números como números (no como texto); NaN/inf/None -> vacío."""
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    if hasattr(v, "item"):  # numpy -> python
        v = v.item()
    return v


def _hoja(spreadsheet, nombre: str, filas: int, cols: int):
    import gspread

    try:
        return spreadsheet.worksheet(nombre)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=nombre, rows=str(filas), cols=str(cols))


def _disponible() -> bool:
    if not config.SPREADSHEET_ID:
        log.warning("SPREADSHEET_ID no configurado: se omite Google Sheets.")
        return False
    return True


def exportar_a_google_sheets(df_maestro: pd.DataFrame, filas_crudas: Optional[List[dict]] = None) -> None:
    """Sube la tabla maestra y (opcional) el JSON crudo que ya descargó el loader."""
    if not _disponible():
        return
    try:
        spreadsheet = _cliente().open_by_key(config.SPREADSHEET_ID)

        ws = _hoja(spreadsheet, "Tabla_Maestra_Rueda", 1000, 30)
        datos = [df_maestro.columns.tolist()] + [[_celda(v) for v in fila] for fila in df_maestro.itertuples(index=False)]
        ws.clear()
        ws.update(values=datos, range_name="A1")
        log.info("Hoja 'Tabla_Maestra_Rueda' actualizada: %d filas.", len(df_maestro))

        if filas_crudas:
            df_json = pd.DataFrame(filas_crudas)
            ws_j = _hoja(spreadsheet, "Datos_JSON", 2000, 40)
            ws_j.clear()
            ws_j.update(values=[df_json.columns.tolist()] + df_json.astype(str).values.tolist(), range_name="A1")
            log.info("Hoja 'Datos_JSON' actualizada: %d registros.", len(df_json))
    except Exception as e:
        log.error("Error al sincronizar con Google Sheets: %s", e)


def guardar_analisis(texto: str, proveedor: str = "") -> None:
    if not _disponible():
        return
    try:
        spreadsheet = _cliente().open_by_key(config.SPREADSHEET_ID)
        ws = _hoja(spreadsheet, "Analisis_IA", 100, 5)
        if not ws.get_all_values():
            ws.update(values=[["Fecha", "Proveedor", "Informe"]], range_name="A1")
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), proveedor, texto[:LIMITE_CELDA]])
        log.info("Informe de IA guardado en 'Analisis_IA'.")
    except Exception as e:
        log.error("Error al guardar el análisis en Sheets: %s", e)
