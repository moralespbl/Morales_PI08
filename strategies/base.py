"""Clase base: evalúa cualquier estrategia descrita como lista de patas.

Métricas (todas por unidad de subyacente, al vencimiento):
  - Valor Esperado   : E[P&L] con S_T lognormal, deriva = tasa libre y vol HISTÓRICA.
                       Es decir, sin sesgo direccional: mide cuánto "regalan" las primas
                       respecto de la volatilidad realizada.
  - Prob. Éxito      : probabilidad de superar la tasa libre (P&L - costo financiero > 0).
  - Score Cuanti     : exceso de retorno esperado sobre capital, anualizado, en puntos
                       sobre la tasa libre (TNA esperada - tasa libre).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import config
from strategies.modelo import (
    Pata,
    analizar_payoff,
    distribucion_terminal,
    estimar_sigma,
    payoff_bruto,
    texto_patas,
)
from strategies.precios import a_segundos, precio_ejecucion, sincronia_ok

log = logging.getLogger(__name__)


@dataclass
class Candidato:
    clasificacion: str
    estrategia: str
    patas: List[Pata]
    capital_abs: bool = False          # capital = |débito| (arbitrajes)
    k_arbitraje: Optional[float] = None  # strike para calcular la tasa implícita


@dataclass
class Contexto:
    ticker: str
    vencimiento: str
    spot: float
    dias: float
    T: float
    sigma: float
    tasa: float
    calls: pd.DataFrame
    puts: pd.DataFrame
    strikes: List[float]
    st: np.ndarray
    w: np.ndarray
    hora_ref: Optional[int] = None  # segundos: último operado entre todas las opciones del subyacente

    def fila(self, tipo: str, strike: float):
        tabla = self.calls if tipo == "CALL" else self.puts
        return tabla.loc[strike] if strike in tabla.index else None

    def strikes_aba(self, n: int) -> List[float]:
        """Hasta n strikes <= spot, los más cercanos."""
        return [s for s in self.strikes if s <= self.spot][-n:]

    def strikes_arr(self, n: int) -> List[float]:
        """Hasta n strikes > spot, los más cercanos."""
        return [s for s in self.strikes if s > self.spot][:n]


def _indexar(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    t = df[df["tipo"] == tipo]
    if "open_interest" in t.columns:
        t = t.sort_values("open_interest", ascending=False)
    return t.drop_duplicates("strike").set_index("strike")


def _num(fila, campo: str) -> float:
    try:
        x = float(fila.get(campo, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x else 0.0


class BaseStrategy(ABC):
    def __init__(self, ticker: str, vencimiento: str, tasa_libre: Optional[float] = None):
        """`tasa_libre`: TNA en decimal (0.35 = 35%) del vencimiento."""
        self.ticker = ticker
        self.vencimiento = vencimiento
        self.tasa_libre = tasa_libre

    # -- a implementar por cada familia ------------------------------------
    @abstractmethod
    def generar_candidatos(self, ctx: Contexto) -> Iterable[Candidato]:
        ...

    # -- pipeline común -----------------------------------------------------
    def calcular_estructura(self, df_chain: pd.DataFrame) -> List[Dict[str, Any]]:
        ctx = self._crear_contexto(df_chain)
        if ctx is None:
            return []
        filas = []
        for cand in self.generar_candidatos(ctx):
            fila = self._evaluar(cand, ctx)
            if fila:
                filas.append(fila)
        return self._top_por_estrategia(filas)

    def _crear_contexto(self, df_chain: pd.DataFrame) -> Optional[Contexto]:
        df = df_chain[
            (df_chain["ticker_base"] == self.ticker) & (df_chain["vencimiento"] == self.vencimiento)
        ]
        if df.empty:
            return None
        spot = _num(df.iloc[0], "suby_px")
        dias = _num(df.iloc[0], "dias_vto")
        if spot <= 0 or dias < 1:  # vence hoy o sin precio: no hay nada que rankear
            return None
        sigma = estimar_sigma(df)
        if sigma is None:
            log.warning("%s %s: sin volatilidad (hist ni implícita); se omite", self.ticker, self.vencimiento)
            return None
        tasa = self.tasa_libre if self.tasa_libre is not None else config.TASA_LIBRE_DEFAULT_PCT / 100.0
        T = dias / 365.0
        calls, puts = _indexar(df, "CALL"), _indexar(df, "PUT")
        strikes = sorted(set(calls.index) | set(puts.index))
        if not strikes:
            return None
        st, w = distribucion_terminal(spot, sigma, T, mu=tasa)
        horas = [a_segundos(h) for h in df["hora"]] if "hora" in df.columns else []
        horas = [h for h in horas if h is not None]
        return Contexto(
            self.ticker, self.vencimiento, spot, dias, T, sigma, tasa, calls, puts, strikes, st, w,
            hora_ref=max(horas) if horas else None,
        )

    def _evaluar(self, cand: Candidato, ctx: Contexto) -> Optional[Dict[str, Any]]:
        # 1. Precios operables de cada pata (ask si compro, bid si vendo)
        filas_pata, precios = [], []
        for p in cand.patas:
            if p.tipo == "SPOT":
                filas_pata.append(None)
                precios.append(ctx.spot)
                continue
            fila = ctx.fila(p.tipo, p.strike)
            if fila is None:
                return None
            px = precio_ejecucion(
                fila, p.cant, config.MODO_PRECIO, config.SPREAD_REL_MAX, config.SLIPPAGE_PCT, config.OPS_MIN
            )
            if px is None:
                return None
            filas_pata.append(fila)
            precios.append(px)
        if config.MODO_PRECIO == "last":
            opciones = [f for f in filas_pata if f is not None]
            if not sincronia_ok(opciones, config.SINCRONIA_MAX_MIN):
                return None
            if config.EDAD_MAX_MIN > 0 and ctx.hora_ref is not None:
                for f in opciones:
                    seg = a_segundos(f.get("hora"))
                    if seg is None or (ctx.hora_ref - seg) / 60.0 > config.EDAD_MAX_MIN:
                        return None

        debito = float(sum(p.cant * px for p, px in zip(cand.patas, precios)))  # >0 pago, <0 cobro

        # 2. Forma del payoff (exacta)
        a = analizar_payoff(cand.patas, debito, ctx.spot)
        if a is None:
            return None

        # 3. Probabilidad y valor esperado (neto del costo financiero del débito)
        pnl = payoff_bruto(cand.patas, ctx.st) - debito
        costo_fin = debito * ctx.tasa * ctx.T
        pnl_exc = pnl - costo_fin
        ev_exc = float(np.dot(ctx.w, pnl_exc))
        prob = float(ctx.w[pnl_exc > 0].sum())
        ev = ev_exc + costo_fin

        # 4. Capital comprometido
        if cand.capital_abs:
            capital = abs(debito)
        elif debito > 0:
            capital = debito
        elif a.perdida_max > 0:
            capital = a.perdida_max
        else:
            capital = abs(debito)
        if capital <= 1e-9:
            return None

        # 5. Filtros de calidad
        if config.EXIGIR_SUPERAR_TASA and ev_exc <= 0:
            return None
        if prob < config.PROB_EXITO_MIN:
            return None

        score = ev_exc / capital / ctx.T * 100.0        # pp sobre la tasa libre
        tna_esp = ev / capital / ctx.T * 100.0
        be = a.breakevens
        buffer_pct = min(abs(b - ctx.spot) for b in be) / ctx.spot * 100.0 if be else None
        ratio = (
            a.ganancia_max / a.perdida_max
            if (not a.ganancia_ilimitada and a.perdida_max > 1e-9)
            else None
        )
        delta = sum(
            p.cant * (1.0 if f is None else _num(f, "delta")) for p, f in zip(cand.patas, filas_pata)
        )

        fila: Dict[str, Any] = {
            "Clasificación": cand.clasificacion,
            "Estrategia": cand.estrategia,
            "Subyacente / Ticker": ctx.ticker,
            "Vencimiento(s)": ctx.vencimiento,
            "Strikes": texto_patas(cand.patas, ctx.spot),
            "Capital Comprometido": round(capital, 2),
            "Pérdida Máxima": round(a.perdida_max, 2),
            "Ganancia Máxima": "Ilimitada" if a.ganancia_ilimitada else round(a.ganancia_max, 2),
            "Punto de Equilibrio (Break-even)": " / ".join(f"{b:.2f}" for b in be) if be else "n/a",
            "Prob. Éxito (%)": round(prob * 100.0, 1),
            "Valor Esperado": round(ev, 2),
            "TNA Esperada (%)": round(tna_esp, 2),
            "Buffer (%)": None if buffer_pct is None else round(buffer_pct, 2),
            "Ratio R/R": None if ratio is None else round(ratio, 4),
            "Delta Proxy": round(delta, 4),
            "Score Cuanti": round(score, 2),
        }
        if cand.k_arbitraje is not None and abs(debito) > 1e-9:
            fila["Tasa Implícita (%)"] = round((cand.k_arbitraje / abs(debito) - 1.0) / ctx.T * 100.0, 2)

        st_esc = ctx.spot * (1.0 + np.array(config.ESCENARIOS_PCT))
        pnl_esc = payoff_bruto(cand.patas, st_esc) - debito
        for pct, v in zip(config.ESCENARIOS_PCT, pnl_esc):
            fila[f"Escenario {int(round(pct * 100))}%"] = round(float(v), 2)
        return fila

    @staticmethod
    def _top_por_estrategia(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Se queda con las TOP_LOCAL mejores de cada Estrategia (rankeadas por separado)."""
        grupos = defaultdict(list)
        for f in filas:
            grupos[f["Estrategia"]].append(f)
        salida = []
        for lista in grupos.values():
            lista.sort(key=lambda f: f["Score Cuanti"], reverse=True)
            salida.extend(lista[: config.TOP_LOCAL])
        return salida
