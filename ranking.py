"""Ranking POR ESTRATEGIA (no por familia).

Cada estrategia (Iron Condor Vendido, Bull Call Spread, Collar, ...) compite
solo contra sí misma, así que una estrategia con score estructuralmente alto
no tapa a las demás de su misma familia.
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd


def ranking_por_estrategia(df: pd.DataFrame, top: int) -> pd.DataFrame:
    """Las `top` mejores filas de cada Estrategia, ordenadas por familia, estrategia y score."""
    if df.empty:
        return df.copy()
    return (
        df.sort_values(
            by=["Clasificación", "Estrategia", "Score Cuanti"], ascending=[True, True, False]
        )
        .groupby("Estrategia", sort=False)
        .head(top)
        .reset_index(drop=True)
    )


def separar_tablas(df_top: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Tabla A (sin escenarios) y Tabla B (matriz de sensibilidad)."""
    esc = [c for c in df_top.columns if c.startswith("Escenario")]
    tabla_a = df_top[[c for c in df_top.columns if c not in esc]].copy()
    base_b = ["Clasificación", "Estrategia", "Subyacente / Ticker", "Vencimiento(s)", "Strikes", "Score Cuanti"]
    tabla_b = df_top[[c for c in base_b if c in df_top.columns] + esc].copy()
    return tabla_a, tabla_b
