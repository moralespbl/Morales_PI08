"""Núcleo matemático: patas, payoff al vencimiento y distribución del subyacente.

Cada estrategia se describe como una lista de patas (CALL / PUT / SPOT con
cantidad positiva = compra, negativa = venta). A partir de ahí el payoff, la
pérdida/ganancia máxima, los break-even, los escenarios, la probabilidad y el
valor esperado se calculan de forma genérica (sin fórmulas a mano por estrategia).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class Pata:
    tipo: str      # "CALL" | "PUT" | "SPOT"
    strike: float  # 0.0 para SPOT
    cant: int      # > 0 compra, < 0 venta


@dataclass
class AnalisisPayoff:
    ganancia_max: float
    perdida_max: float
    ganancia_ilimitada: bool
    breakevens: List[float]


def payoff_bruto(patas: Sequence[Pata], st) -> np.ndarray:
    """Valor de las patas al vencimiento para cada precio final `st` (sin costo de entrada)."""
    st = np.asarray(st, dtype=float)
    total = np.zeros_like(st, dtype=float)
    for p in patas:
        if p.tipo == "CALL":
            total += p.cant * np.maximum(st - p.strike, 0.0)
        elif p.tipo == "PUT":
            total += p.cant * np.maximum(p.strike - st, 0.0)
        else:  # SPOT
            total += p.cant * st
    return total


def analizar_payoff(patas: Sequence[Pata], debito: float, spot: float) -> Optional[AnalisisPayoff]:
    """Pérdida/ganancia máxima y break-evens EXACTOS (el payoff es lineal por tramos).

    `debito` = costo neto de entrada (> 0 se paga, < 0 se cobra).
    Devuelve None si la pérdida es ilimitada (patas vendidas sin cobertura).
    """
    pendiente_inf = sum(p.cant for p in patas if p.tipo in ("CALL", "SPOT"))
    if pendiente_inf < 0:
        return None

    strikes = sorted({p.strike for p in patas if p.tipo != "SPOT"})
    grande = max([spot] + strikes) * 10.0
    xs = np.array(sorted({0.0, *strikes, grande}))
    ys = payoff_bruto(patas, xs) - debito

    ilimitada = pendiente_inf > 0
    ganancia_max = float("inf") if ilimitada else max(0.0, float(ys.max()))
    perdida_max = max(0.0, -float(ys.min()))

    raices = []
    for i in range(len(xs) - 1):
        x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
        if y0 == 0.0 and y1 != 0.0:
            raices.append(x0)
        elif y0 * y1 < 0.0:
            raices.append(x0 - y0 * (x1 - x0) / (y1 - y0))
    breakevens = sorted({round(float(r), 6) for r in raices})
    return AnalisisPayoff(ganancia_max, perdida_max, ilimitada, breakevens)


def normalizar_vol(v) -> Optional[float]:
    """Vol en % (ej. 40) o decimal (ej. 0.40) -> decimal. None si no es válida."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v) or v <= 0:
        return None
    return v / 100.0 if v > 3.0 else v


def estimar_sigma(df) -> Optional[float]:
    """Vol del subyacente: mediana de la histórica; si falta, de la implícita."""
    for col in ("vol_hist", "vol_impl"):
        if col in df.columns:
            vals = [normalizar_vol(v) for v in df[col]]
            vals = [v for v in vals if v]
            if vals:
                return float(np.median(vals))
    return None


def distribucion_terminal(
    spot: float, sigma: float, T: float, mu: float, n: int = 801, zmax: float = 6.0
) -> Tuple[np.ndarray, np.ndarray]:
    """Discretiza S_T lognormal con deriva `mu` y vol `sigma`.

    Devuelve (precios, pesos) con pesos que suman 1, para calcular esperanzas
    y probabilidades por cuadratura sin depender de scipy.
    """
    z = np.linspace(-zmax, zmax, n)
    w = np.exp(-0.5 * z**2)
    w /= w.sum()
    st = spot * np.exp((mu - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * z)
    return st, w


_ETIQUETAS = {
    ("PUT", 1): "P_C",
    ("PUT", -1): "P_V",
    ("CALL", 1): "C_C",
    ("CALL", -1): "C_V",
}


def texto_patas(patas: Sequence[Pata], spot: float) -> str:
    """Notación: P_C/P_V = put comprado/vendido, C_C/C_V = call comprado/vendido."""
    partes = []
    for p in patas:
        if p.tipo == "SPOT":
            partes.append(("SPOT" if p.cant > 0 else "SHORT_SPOT") + f":{spot:g}")
        else:
            etiqueta = _ETIQUETAS[(p.tipo, 1 if p.cant > 0 else -1)]
            prefijo = f"{abs(p.cant)}x" if abs(p.cant) > 1 else ""
            partes.append(f"{prefijo}{etiqueta}:{p.strike:g}")
    return " / ".join(partes)
