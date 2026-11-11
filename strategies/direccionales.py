"""Direccionales: Bull Call Spread (alcista) y Bear Put Spread (bajista)."""
from __future__ import annotations

from itertools import combinations
from typing import Iterable

from strategies.base import BaseStrategy, Candidato, Contexto
from strategies.modelo import Pata


class DireccionalesStrategy(BaseStrategy):
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        strikes = sorted(set(ctx.strikes_aba(4) + ctx.strikes_arr(4)))

        for k_inf, k_sup in combinations(strikes, 2):
            # Bull Call Spread: +C(K inf) -C(K sup)
            yield Candidato(
                "Alcistas", "Bull Call Spread", [Pata("CALL", k_inf, 1), Pata("CALL", k_sup, -1)]
            )
            # Bear Put Spread: +P(K sup) -P(K inf)
            yield Candidato(
                "Bajistas", "Bear Put Spread", [Pata("PUT", k_sup, 1), Pata("PUT", k_inf, -1)]
            )
