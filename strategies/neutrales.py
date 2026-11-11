"""Neutrales: Iron Condors y Mariposas (comprados y vendidos)."""
from __future__ import annotations

import math
from itertools import combinations
from typing import Iterable

from strategies.base import BaseStrategy, Candidato, Contexto
from strategies.modelo import Pata

CLASIF = "Neutrales"


class NeutralesStrategy(BaseStrategy):
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        aba, arr = ctx.strikes_aba(4), ctx.strikes_arr(4)

        # Iron Condor: K1 < K2 <= spot < K3 < K4
        #   Vendido : +P(K1) -P(K2) -C(K3) +C(K4)   (cobra crédito)
        #   Comprado: la posición inversa            (paga débito)
        for k1, k2 in combinations(aba, 2):
            for k3, k4 in combinations(arr, 2):
                for signo, nombre in ((1, "Iron Condor Vendido"), (-1, "Iron Condor Comprado")):
                    yield Candidato(
                        CLASIF,
                        nombre,
                        [
                            Pata("PUT", k1, signo),
                            Pata("PUT", k2, -signo),
                            Pata("CALL", k3, -signo),
                            Pata("CALL", k4, signo),
                        ],
                    )

        # Mariposa con calls: K1 < K2 < K3 equidistantes y K1 <= spot <= K3
        #   Comprada: +C(K1) -2C(K2) +C(K3)  |  Vendida: inversa
        for k1, k2, k3 in combinations(sorted(set(aba + arr)), 3):
            if not math.isclose(k2 - k1, k3 - k2, rel_tol=1e-9, abs_tol=1e-9):
                continue
            if not (k1 <= ctx.spot <= k3):
                continue
            for signo, nombre in ((1, "Mariposa Comprada"), (-1, "Mariposa Vendida")):
                yield Candidato(
                    CLASIF,
                    nombre,
                    [Pata("CALL", k1, signo), Pata("CALL", k2, -2 * signo), Pata("CALL", k3, signo)],
                )
