import math

import pandas as pd
import pytest

import config


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, r, sig, tipo):
    d1 = (math.log(S / K) + (r + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    if tipo == "CALL":
        return S * _N(d1) - K * math.exp(-r * T) * _N(d2), _N(d1)
    return K * math.exp(-r * T) * _N(-d2) - S * _N(-d1), _N(d1) - 1


def cadena_sintetica(spot=100.0, dias=30, iv=0.50, hv=0.30, r=0.35, hs=0.03, strikes=None, ticker="XXX", vto="2026-12-18"):
    """Cadena con precios Black-Scholes a vol implícita `iv`; bid/ask = mid ± hs; vol histórica `hv`."""
    strikes = strikes or [85, 90, 95, 100, 105, 110, 115]
    T = dias / 365.0
    filas = []
    for k in strikes:
        for tipo in ("CALL", "PUT"):
            mid, delta = bs(spot, k, T, r, iv, tipo)
            filas.append(
                dict(
                    ticker_base=ticker, vencimiento=vto, tipo=tipo, strike=float(k), suby_px=spot,
                    dias_vto=float(dias), hora="15:00:00", last=mid, bid=mid * (1 - hs), ask=mid * (1 + hs),
                    precio_teorico=mid, delta=delta, vol_impl=iv * 100, vol_hist=hv * 100, open_interest=100.0,
                    cant_ops=5.0,
                )
            )
    return pd.DataFrame(filas)


@pytest.fixture
def cadena():
    return cadena_sintetica()


@pytest.fixture(autouse=True)
def config_por_defecto(monkeypatch):
    monkeypatch.setattr(config, "MODO_PRECIO", "bid_ask")
    monkeypatch.setattr(config, "SLIPPAGE_PCT", 0.0)
    monkeypatch.setattr(config, "OPS_MIN", 0)
    monkeypatch.setattr(config, "EDAD_MAX_MIN", 0)
    monkeypatch.setattr(config, "SINCRONIA_MAX_MIN", 30)
    monkeypatch.setattr(config, "SPREAD_REL_MAX", 0.5)
    monkeypatch.setattr(config, "PROB_EXITO_MIN", 0.25)
    monkeypatch.setattr(config, "EXIGIR_SUPERAR_TASA", True)
