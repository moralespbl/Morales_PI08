import pandas as pd
import pytest

import config
from ranking import ranking_por_estrategia, separar_tablas
from strategies.arbitrajes_tasas import ArbitrajesTasasStrategy
from strategies.cobertura import CoberturaStrategy
from strategies.direccionales import DireccionalesStrategy
from strategies.neutrales import NeutralesStrategy
from strategies.volatilidad import VolatilidadStrategy
from tests.conftest import cadena_sintetica

FAMILIAS = [NeutralesStrategy, VolatilidadStrategy, DireccionalesStrategy, CoberturaStrategy, ArbitrajesTasasStrategy]
COLS = [
    "Clasificación", "Estrategia", "Subyacente / Ticker", "Vencimiento(s)", "Strikes", "Capital Comprometido",
    "Pérdida Máxima", "Ganancia Máxima", "Punto de Equilibrio (Break-even)", "Prob. Éxito (%)", "Valor Esperado",
    "TNA Esperada (%)", "Buffer (%)", "Ratio R/R", "Delta Proxy", "Score Cuanti",
]


def correr(df, tasa=0.35):
    filas = []
    for F in FAMILIAS:
        filas += F("XXX", "2026-12-18", tasa).calcular_estructura(df)
    return pd.DataFrame(filas)


def test_columnas_y_escenarios(cadena):
    df = correr(cadena)
    assert not df.empty
    for c in COLS:
        assert c in df.columns
    assert {f"Escenario {p}%" for p in (-15, -10, -5, 0, 5, 10, 15)} <= set(df.columns)


def test_filtros_se_cumplen(cadena):
    df = correr(cadena)
    assert (df["Score Cuanti"] > 0).all()
    assert (df["Prob. Éxito (%)"] >= config.PROB_EXITO_MIN * 100).all()
    assert (df.groupby("Estrategia").size() <= config.TOP_LOCAL).all()


def test_vol_implicita_alta_favorece_vender_vol_y_no_comprarla():
    """IV 50% vs HV 30%: las primas están caras. Vender vol tiene ventaja; comprar un straddle, no."""
    df = correr(cadena_sintetica(iv=0.50, hv=0.30))
    estrategias = set(df["Estrategia"])
    assert "Long Straddle" not in estrategias
    assert estrategias & {"Iron Condor Vendido", "Mariposa Vendida"}


def test_vol_implicita_baja_favorece_comprar_vol():
    """IV 20% vs HV 60%: las primas están baratas, comprar vol tiene ventaja."""
    df = correr(cadena_sintetica(iv=0.20, hv=0.60))
    assert "Long Straddle" in set(df["Estrategia"]) or "Long Strangle" in set(df["Estrategia"])


def test_sin_bid_ask_no_hay_resultados_en_modo_bid_ask(monkeypatch):
    df = cadena_sintetica()
    df["bid"] = 0.0
    df["ask"] = 0.0
    assert correr(df).empty
    monkeypatch.setattr(config, "MODO_PRECIO", "last")
    assert not correr(df).empty  # con last sí hay datos operables


def _solo_last(monkeypatch, **cfg):
    """Feed como el real de BYMA Educa: sin bid/ask, solo último operado."""
    df = cadena_sintetica()
    df["bid"] = df["ask"] = 0.0
    monkeypatch.setattr(config, "MODO_PRECIO", "last")
    for k, v in cfg.items():
        monkeypatch.setattr(config, k, v)
    return df


def test_feed_sin_puntas_funciona_en_modo_last(monkeypatch):
    assert not correr(_solo_last(monkeypatch, SLIPPAGE_PCT=0.02, OPS_MIN=1)).empty


def test_slippage_empeora_los_resultados(monkeypatch):
    sin = correr(_solo_last(monkeypatch, SLIPPAGE_PCT=0.0))
    con = correr(_solo_last(monkeypatch, SLIPPAGE_PCT=0.10))
    assert con["Score Cuanti"].sum() < sin["Score Cuanti"].sum()


def test_opciones_sin_operaciones_se_descartan(monkeypatch):
    df = _solo_last(monkeypatch, OPS_MIN=1)
    df["cant_ops"] = 0.0
    assert correr(df).empty


def test_sincronia_entre_patas_en_modo_last(monkeypatch):
    df = _solo_last(monkeypatch, SINCRONIA_MAX_MIN=30)
    # las opciones alternan hora: 10:00 y 15:00 -> toda estructura con patas mezcladas queda afuera
    df["hora"] = ["10:00:00" if i % 2 == 0 else "15:00:00" for i in range(len(df))]
    mezclada = correr(df)
    df["hora"] = "15:00:00"
    sincronica = correr(df)
    assert len(mezclada) < len(sincronica)


def test_edad_maxima_respecto_del_ultimo_operado_del_subyacente(monkeypatch):
    df = _solo_last(monkeypatch, EDAD_MAX_MIN=60, SINCRONIA_MAX_MIN=10_000)
    df["hora"] = "10:00:00"            # todo operó a la mañana...
    df.loc[df.index[0], "hora"] = "16:30:00"  # ...salvo una opción: el spot "actual" es de las 16:30
    assert correr(df).empty             # las patas de las 10:00 están a 6,5 h: se descartan
    monkeypatch.setattr(config, "EDAD_MAX_MIN", 0)
    assert not correr(df).empty         # con el filtro apagado vuelven


def test_solo_precio_teorico_no_genera_nada(monkeypatch):
    df = cadena_sintetica()
    df["bid"] = df["ask"] = df["last"] = 0.0
    monkeypatch.setattr(config, "MODO_PRECIO", "last")
    assert correr(df).empty


def _par(spot, K, c_bid, c_ask, p_bid, p_ask):
    filas = []
    for tipo, bid, ask in (("CALL", c_bid, c_ask), ("PUT", p_bid, p_ask)):
        filas.append(
            dict(ticker_base="XXX", vencimiento="2026-12-18", tipo=tipo, strike=K, suby_px=spot, dias_vto=30.0,
                 hora="15:00:00", last=(bid + ask) / 2, bid=bid, ask=ask, precio_teorico=0.0, delta=0.5 if tipo == "CALL" else -0.5,
                 vol_impl=40.0, vol_hist=40.0, open_interest=10.0)
        )
    return pd.DataFrame(filas)


def test_conversion_detectada_con_tasa_implicita_correcta():
    # Cuesto: 100 + 2.0 (ask put) - 6.0 (bid call) = 96 -> cobro K=100 en 30 días
    df = _par(100.0, 100.0, 6.0, 6.2, 1.8, 2.0)
    arb = pd.DataFrame(ArbitrajesTasasStrategy("XXX", "2026-12-18", 0.30).calcular_estructura(df))
    conv = arb[arb["Estrategia"].str.startswith("Conversión")]
    assert len(conv) == 1
    esperado = (100.0 / 96.0 - 1.0) * 365 / 30 * 100
    assert conv.iloc[0]["Tasa Implícita (%)"] == pytest.approx(esperado, abs=0.01)
    esc = [c for c in arb.columns if c.startswith("Escenario")]
    assert conv.iloc[0][esc].nunique() == 1  # resultado fijo en todos los escenarios
    assert conv.iloc[0]["Prob. Éxito (%)"] == 100.0
    assert not arb["Estrategia"].str.startswith("Reversión").any()  # acá la reversión sale cara


def test_reversion_detectada_cuando_el_financiamiento_implicito_es_barato():
    # Cobro 100 + 6.0 (bid put) - 2.2 (ask call) = 103.8 hoy y pago K=100: ganancia fija
    df = _par(100.0, 100.0, 2.0, 2.2, 6.0, 6.2)
    arb = pd.DataFrame(ArbitrajesTasasStrategy("XXX", "2026-12-18", 0.30).calcular_estructura(df))
    rev = arb[arb["Estrategia"].str.startswith("Reversión")]
    assert len(rev) == 1
    esc = [c for c in arb.columns if c.startswith("Escenario")]
    assert rev.iloc[0][esc].nunique() == 1
    assert rev.iloc[0]["Escenario 0%"] == pytest.approx(3.8, abs=0.01)  # 103.8 - 100
    assert rev.iloc[0]["Tasa Implícita (%)"] < 0  # te financiás a tasa negativa


def test_vence_hoy_no_se_calcula(cadena):
    cadena["dias_vto"] = 0.0
    assert correr(cadena).empty


# ---- ranking por estrategia ----------------------------------------------
def test_ranking_por_estrategia_no_deja_que_una_tape_a_la_otra():
    df = pd.DataFrame(
        {
            "Clasificación": ["Neutrales"] * 7,
            "Estrategia": ["Mariposa Comprada"] * 4 + ["Iron Condor Vendido"] * 3,
            "Score Cuanti": [9000, 8000, 7000, 6000, 12.0, 8.0, 5.0],
            "Escenario 0%": range(7),
        }
    )
    top = ranking_por_estrategia(df, 3)
    por_estrategia = top.groupby("Estrategia")["Score Cuanti"].apply(list).to_dict()
    assert por_estrategia["Mariposa Comprada"] == [9000, 8000, 7000]
    assert por_estrategia["Iron Condor Vendido"] == [12.0, 8.0, 5.0]  # sigue apareciendo completo


def test_separar_tablas():
    df = pd.DataFrame({"Clasificación": ["A"], "Estrategia": ["x"], "Strikes": ["s"], "Score Cuanti": [1.0], "Escenario 5%": [2.0]})
    a, b = separar_tablas(df)
    assert "Escenario 5%" not in a.columns
    assert "Escenario 5%" in b.columns
