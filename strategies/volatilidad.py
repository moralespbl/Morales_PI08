"""Volatilidad: Long Straddle y Long Strangle."""
from __future__ import annotations

from typing import Iterable

from strategies.base import BaseStrategy, Candidato, Contexto
from strategies.modelo import Pata

CLASIF = "Volatilidad"


class VolatilidadStrategy(BaseStrategy):
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        aba, arr = ctx.strikes_aba(4), ctx.strikes_arr(4)
        if not aba or not arr:
            return

        # Long Straddle: call + put en el strike más cercano al spot
        k_atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        yield Candidato(CLASIF, "Long Straddle", [Pata("CALL", k_atm, 1), Pata("PUT", k_atm, 1)])

        # Long Strangle: put y call OTM (un strike más lejos que el ATM)
        if len(aba) >= 2 and len(arr) >= 2:
            yield Candidato(
                CLASIF, "Long Strangle", [Pata("PUT", aba[-2], 1), Pata("CALL", arr[1], 1)]
            )
