"""Tasas y Arbitrajes: Conversión y Reversión (paridad put-call).

Ambas dejan un resultado fijo K al vencimiento, así que lo único que importa es
la tasa implícita K / |costo neto| - 1 contra la tasa libre:
  - Conversión: +SPOT +P(K) -C(K)  -> "prestás" a la tasa implícita.
  - Reversión : -SPOT -P(K) +C(K)  -> "te financiás" a la tasa implícita
                                      (conviene si es menor que la tasa libre).

Ojo (no modelado): las opciones de BYMA son americanas, por lo que el call/put
vendido tiene riesgo de ejercicio anticipado; tampoco se descuentan comisiones
ni derechos de mercado, ni las restricciones/costos de la venta en corto.
"""
from __future__ import annotations

from typing import Iterable

import config
from strategies.base import BaseStrategy, Candidato, Contexto
from strategies.modelo import Pata

CLASIF = "Tasas y Arbitrajes"


class ArbitrajesTasasStrategy(BaseStrategy):
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        cercanos = [
            k
            for k in ctx.strikes
            if abs(k - ctx.spot) / ctx.spot <= config.ARB_DISTANCIA_STRIKE_MAX
            and k in ctx.calls.index
            and k in ctx.puts.index
        ]
        for k in cercanos:
            yield Candidato(
                CLASIF,
                "Conversión (Arbitraje Tasa)",
                [Pata("SPOT", 0.0, 1), Pata("PUT", k, 1), Pata("CALL", k, -1)],
                capital_abs=True,
                k_arbitraje=k,
            )
            yield Candidato(
                CLASIF,
                "Reversión (Arbitraje Tasa)",
                [Pata("SPOT", 0.0, -1), Pata("PUT", k, -1), Pata("CALL", k, 1)],
                capital_abs=True,
                k_arbitraje=k,
            )
