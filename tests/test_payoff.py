"""Pérdida/ganancia máxima y break-even contra las fórmulas clásicas de cada estrategia."""
import pytest

from strategies.modelo import Pata, analizar_payoff, payoff_bruto, texto_patas

S = 100.0


def debito(patas, precios):
    return sum(p.cant * px for p, px in zip(patas, precios))


def test_bull_call_spread():
    patas = [Pata("CALL", 100, 1), Pata("CALL", 110, -1)]
    d = debito(patas, [5.0, 2.0])  # paga ask 5, cobra bid 2 -> débito 3
    a = analizar_payoff(patas, d, S)
    assert d == 3.0
    assert a.perdida_max == pytest.approx(3.0)
    assert a.ganancia_max == pytest.approx(7.0)
    assert a.breakevens == [pytest.approx(103.0)]


def test_iron_condor_vendido():
    patas = [Pata("PUT", 90, 1), Pata("PUT", 95, -1), Pata("CALL", 105, -1), Pata("CALL", 110, 1)]
    d = debito(patas, [0.5, 1.5, 1.4, 0.4])  # crédito 2.0
    a = analizar_payoff(patas, d, S)
    assert d == pytest.approx(-2.0)
    assert a.ganancia_max == pytest.approx(2.0)
    assert a.perdida_max == pytest.approx(3.0)  # ancho 5 - crédito 2
    assert a.breakevens == [pytest.approx(93.0), pytest.approx(107.0)]


def test_iron_condor_comprado_es_el_espejo_del_vendido():
    vendido = [Pata("PUT", 90, 1), Pata("PUT", 95, -1), Pata("CALL", 105, -1), Pata("CALL", 110, 1)]
    comprado = [Pata(p.tipo, p.strike, -p.cant) for p in vendido]
    precios = [0.5, 1.5, 1.4, 0.4]
    av = analizar_payoff(vendido, debito(vendido, precios), S)
    ac = analizar_payoff(comprado, debito(comprado, precios), S)
    assert ac.ganancia_max == pytest.approx(av.perdida_max)
    assert ac.perdida_max == pytest.approx(av.ganancia_max)


def test_mariposa_comprada():
    patas = [Pata("CALL", 90, 1), Pata("CALL", 100, -2), Pata("CALL", 110, 1)]
    d = debito(patas, [11.5, 5.0, 1.5])  # 11.5 - 10 + 1.5 = 3
    a = analizar_payoff(patas, d, S)
    assert a.perdida_max == pytest.approx(3.0)
    assert a.ganancia_max == pytest.approx(7.0)
    assert a.breakevens == [pytest.approx(93.0), pytest.approx(107.0)]


def test_covered_call():
    patas = [Pata("SPOT", 0.0, 1), Pata("CALL", 110, -1)]
    d = debito(patas, [S, 2.0])  # 98
    a = analizar_payoff(patas, d, S)
    assert a.perdida_max == pytest.approx(98.0)  # el papel llega a 0
    assert a.ganancia_max == pytest.approx(12.0)  # 110 - 98
    assert a.breakevens == [pytest.approx(98.0)]


def test_collar():
    patas = [Pata("SPOT", 0.0, 1), Pata("PUT", 95, 1), Pata("CALL", 110, -1)]
    d = debito(patas, [S, 1.5, 2.0])  # 99.5
    a = analizar_payoff(patas, d, S)
    assert a.perdida_max == pytest.approx(4.5)  # 99.5 - 95
    assert a.ganancia_max == pytest.approx(10.5)  # 110 - 99.5
    assert a.breakevens == [pytest.approx(99.5)]


def test_long_straddle_ganancia_ilimitada():
    patas = [Pata("CALL", 100, 1), Pata("PUT", 100, 1)]
    a = analizar_payoff(patas, 8.0, S)
    assert a.ganancia_ilimitada
    assert a.perdida_max == pytest.approx(8.0)
    assert a.breakevens == [pytest.approx(92.0), pytest.approx(108.0)]


def test_call_descubierto_se_descarta_por_perdida_ilimitada():
    assert analizar_payoff([Pata("CALL", 100, -1)], -5.0, S) is None


@pytest.mark.parametrize("signo", [1, -1])
def test_conversion_y_reversion_tienen_payoff_constante(signo):
    """Propiedad clave: un arbitraje de paridad rinde lo mismo en cualquier escenario."""
    patas = [Pata("SPOT", 0.0, signo), Pata("PUT", 100, signo), Pata("CALL", 100, -signo)]
    st = [50, 80, 100, 120, 200]
    pagos = payoff_bruto(patas, st)
    assert max(pagos) == pytest.approx(min(pagos))
    assert pagos[0] == pytest.approx(signo * 100.0)  # = +K en conversión, -K en reversión


def test_reversion_resultado_fijo_correcto():
    """Reversión: cobro S + P - C hoy y pago K al vencimiento; el resultado es S + P - C - K."""
    patas = [Pata("SPOT", 0.0, -1), Pata("PUT", 100, -1), Pata("CALL", 100, 1)]
    d = debito(patas, [100.0, 6.0, 2.0])  # -100 - 6 + 2 = -104
    a = analizar_payoff(patas, d, S)
    assert a.ganancia_max == pytest.approx(4.0)  # 104 - 100
    assert a.perdida_max == 0.0


def test_texto_patas():
    patas = [Pata("CALL", 90, 1), Pata("CALL", 100, -2), Pata("SPOT", 0.0, 1), Pata("PUT", 95, -1)]
    assert texto_patas(patas, 100.0) == "C_C:90 / 2xC_V:100 / SPOT:100 / P_V:95"
