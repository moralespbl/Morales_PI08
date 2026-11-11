"""Precio de ejecución de cada pata: ASK para comprar, BID para vender.

Nunca se usa el precio teórico: una estrategia calculada con precios que no se
pueden operar no sirve para rankear (ni para detectar arbitrajes).
"""
from __future__ import annotations

from typing import Iterable, Optional


def _num(fila, campo: str) -> float:
    try:
        x = float(fila.get(campo, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x else 0.0  # NaN -> 0


def precio_ejecucion(
    fila,
    cant: int,
    modo: str = "bid_ask",
    spread_rel_max: float = 0.5,
    slippage: float = 0.0,
    ops_min: float = 0.0,
) -> Optional[float]:
    """Precio al que se ejecutaría la pata, o None si no hay precio operable.

    modo "last": último operado, exigiendo `cant_ops >= ops_min` y penalizado por `slippage`
                 (compra: último*(1+s); venta: último*(1-s)) para aproximar el spread.
    modo "bid_ask": ask para comprar, bid para vender (solo si el feed trae puntas).
    """
    if modo == "last":
        px = _num(fila, "last")
        if px <= 0:
            return None
        if ops_min > 0 and _num(fila, "cant_ops") < ops_min:
            return None  # sin operaciones en la rueda: el precio puede estar viejo
        return px * (1.0 + slippage) if cant > 0 else px * (1.0 - slippage)

    bid, ask = _num(fila, "bid"), _num(fila, "ask")
    if bid > 0 and ask > 0:
        if ask < bid:  # punta cruzada: dato inconsistente
            return None
        mid = (bid + ask) / 2.0
        if (ask - bid) / mid > spread_rel_max:
            return None
    px = ask if cant > 0 else bid
    return px if px > 0 else None


def _a_segundos(hora) -> Optional[int]:
    try:
        partes = str(hora).split(".")[0].split(":")
        h, m = int(partes[0]), int(partes[1])
        s = int(partes[2]) if len(partes) > 2 else 0
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


a_segundos = _a_segundos


def sincronia_ok(filas: Iterable, max_minutos: float = 30) -> bool:
    """Las patas no deben haber operado con más de `max_minutos` de diferencia.

    Solo tiene sentido en modo "last". Si no hay horas válidas, no bloquea.
    """
    segundos = [_a_segundos(f.get("hora")) for f in filas]
    segundos = [s for s in segundos if s is not None]
    if len(segundos) < 2:
        return True
    return (max(segundos) - min(segundos)) / 60.0 <= max_minutos
