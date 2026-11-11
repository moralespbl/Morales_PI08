"""Cobertura: Covered Call y Collar (con el subyacente en cartera)."""
from __future__ import annotations

from typing import Iterable

from strategies.base import BaseStrategy, Candidato, Contexto
from strategies.modelo import Pata

CLASIF = "Cobertura"


class CoberturaStrategy(BaseStrategy):
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        aba = [k for k in ctx.strikes_aba(3) if k < ctx.spot]
        arr = ctx.strikes_arr(3)

        # Covered Call: +SPOT -C(K > spot)
        for k_call in arr:
            yield Candidato(CLASIF, "Covered Call", [Pata("SPOT", 0.0, 1), Pata("CALL", k_call, -1)])

        # Collar: +SPOT +P(K < spot) -C(K > spot)
        for k_put in aba:
            for k_call in arr:
                yield Candidato(
                    CLASIF,
                    "Collar",
                    [Pata("SPOT", 0.0, 1), Pata("PUT", k_put, 1), Pata("CALL", k_call, -1)],
                )
