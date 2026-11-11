import math

import numpy as np
import pytest

from strategies.modelo import distribucion_terminal, normalizar_vol
from strategies.precios import precio_ejecucion, sincronia_ok


def test_esperanza_del_subyacente_crece_a_la_tasa_libre():
    st, w = distribucion_terminal(100.0, 0.40, 30 / 365, mu=0.35)
    assert w.sum() == pytest.approx(1.0)
    assert np.dot(w, st) == pytest.approx(100.0 * math.exp(0.35 * 30 / 365), rel=1e-4)


def test_probabilidad_coincide_con_N_d2():
    S, K, sig, T, r = 100.0, 105.0, 0.40, 60 / 365, 0.30
    st, w = distribucion_terminal(S, sig, T, mu=r)
    d2 = (math.log(S / K) + (r - 0.5 * sig**2) * T) / (sig * math.sqrt(T))
    esperado = 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
    assert w[st > K].sum() == pytest.approx(esperado, abs=0.01)


def test_normalizar_vol():
    assert normalizar_vol(40) == pytest.approx(0.40)
    assert normalizar_vol(0.4) == pytest.approx(0.4)
    assert normalizar_vol(0) is None
    assert normalizar_vol("x") is None
    assert normalizar_vol(float("nan")) is None


# ---- precios de ejecución -------------------------------------------------
FILA = {"bid": 1.0, "ask": 1.2, "last": 5.0, "precio_teorico": 9.0}


def test_compra_al_ask_y_venta_al_bid():
    assert precio_ejecucion(FILA, +1) == 1.2
    assert precio_ejecucion(FILA, -1) == 1.0


def test_modo_last():
    assert precio_ejecucion(FILA, +1, modo="last") == 5.0


def test_last_con_slippage_penaliza_en_contra():
    fila = {"last": 10.0, "cant_ops": 3}
    assert precio_ejecucion(fila, +1, modo="last", slippage=0.02) == pytest.approx(10.2)  # compro más caro
    assert precio_ejecucion(fila, -1, modo="last", slippage=0.02) == pytest.approx(9.8)   # vendo más barato


def test_last_exige_operaciones_en_la_rueda():
    assert precio_ejecucion({"last": 10.0, "cant_ops": 0}, +1, modo="last", ops_min=1) is None
    assert precio_ejecucion({"last": 10.0}, +1, modo="last", ops_min=1) is None
    assert precio_ejecucion({"last": 10.0, "cant_ops": 1}, +1, modo="last", ops_min=1) == 10.0


def test_nunca_usa_el_precio_teorico():
    assert precio_ejecucion({"precio_teorico": 9.0}, +1) is None
    assert precio_ejecucion({"precio_teorico": 9.0}, -1, modo="last") is None


def test_sin_punta_necesaria():
    assert precio_ejecucion({"bid": 0.0, "ask": 1.2}, -1) is None  # no hay bid para vender
    assert precio_ejecucion({"bid": 1.0, "ask": 0.0}, +1) is None  # no hay ask para comprar


def test_spread_demasiado_ancho_o_punta_cruzada():
    assert precio_ejecucion({"bid": 1.0, "ask": 3.0}, +1, spread_rel_max=0.5) is None
    assert precio_ejecucion({"bid": 2.0, "ask": 1.0}, +1) is None


def test_sincronia():
    assert sincronia_ok([{"hora": "10:00:00"}, {"hora": "10:20"}], 30)
    assert not sincronia_ok([{"hora": "10:00:00"}, {"hora": "11:00:00"}], 30)
    assert sincronia_ok([{"hora": ""}, {"hora": "11:00:00"}], 30)  # sin dato no bloquea
