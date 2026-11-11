import pandas as pd
import pytest

import ai_analyzer
import config
from ai_analyzer import AnalisisIA, ErrorIA, analizar_estrategias, construir_prompt, registros_para_ia
from data_loader import BYMALoader
from telegram_notifier import dividir_mensaje, empaquetar, md_a_html


# ---- loader ----------------------------------------------------------------
def test_loader_mapea_ultimo_a_last_y_descarta_tipos_invalidos():
    filas = [
        {"symbol": "GFGC100", "tipo": "CALL", "subyacente": "GFG", "vencimiento": "2026-12-18", "ultimo": "1,5",
         "bid": 1.4, "ask": 1.6, "tasa_libre": 29.62, "strike": 100, "suby_px": 98, "dias_vto": 38},
        {"symbol": "COMEX", "tipo": "ACCION"},   # tiene una "C" y una "V"... y no es opción
        {"symbol": "", "tipo": "PUT"},
    ]
    df, curva = BYMALoader().procesar(filas)
    assert len(df) == 1
    assert df.iloc[0]["last"] == 1.5
    assert df.iloc[0]["tipo"] == "CALL"
    assert curva == {"2026-12-18": pytest.approx(0.2962)}


FILA_REAL = {
    "symbol": "ALUC1000DI", "subyacente": "ALUA", "moneyness": "OTM", "hora": "10:35:33.121", "iv_estado": "OK",
    "tasa_ticker": "S30N6", "strike": 1000.0, "suby_px": 774.0, "open_interest": 2090.0, "vol_ef": 790.0,
    "apertura": 7.9, "minimo": 7.9, "maximo": 7.9, "ultimo": 7.9, "cant_ops": 1.0, "precio_teorico": 7.9,
    "valor_intrinseco": 0.0, "valor_temporal": 7.9, "dias_vto": 42.0, "lote": 100.0, "delta": 0.12411,
    "gamma": 0.001481, "theta": -0.39057, "vega": 0.544036, "rho": 0.102731, "desvio_teorico": 0.0, "dist": -21.7,
    "var_prima": 31.644726, "var_oi": 0.0, "vol_hist": 31.314159, "vol_impl": 52.057112,
    "desvio_teorico_pct": 0.0, "iv_hv": 20.742953, "tasa_libre": 22.114909, "tipo": "CALL",
    "seccion": "Acciones", "subyacente_nombre": None, "vencimiento": "2026-12-18", "oi_nocional": 161766000.0,
}


def test_loader_con_una_fila_real_del_feed():
    """Fila tal cual la entrega tablero.bymaeduca.com.ar: no trae bid/ask, solo 'ultimo'."""
    df, curva = BYMALoader().procesar([FILA_REAL])
    r = df.iloc[0]
    assert (r["ticker_base"], r["tipo"], r["strike"], r["suby_px"]) == ("ALUA", "CALL", 1000.0, 774.0)
    assert r["last"] == 7.9 and r["cant_ops"] == 1.0
    assert r["bid"] == 0.0 and r["ask"] == 0.0           # el feed no trae puntas
    assert curva == {"2026-12-18": pytest.approx(0.22114909)}
    # vol en % -> el motor la normaliza a decimal
    from strategies.modelo import normalizar_vol
    assert normalizar_vol(r["vol_hist"]) == pytest.approx(0.31314159)


def test_loader_extrae_filas_de_distintas_formas():
    assert BYMALoader.extraer_filas({"op": {"rows": [{"a": 1}]}}) == [{"a": 1}]
    assert BYMALoader.extraer_filas({"x": {"rows": [{"b": 2}]}}) == [{"b": 2}]
    assert BYMALoader.extraer_filas([{"c": 3}, "basura"]) == [{"c": 3}]
    assert BYMALoader.extraer_filas({}) == []


# ---- IA ---------------------------------------------------------------------
def _df_ia(n_estrategias=6):
    filas = [
        {"Clasificación": f"F{i}", "Estrategia": f"Estrategia {i}", "Subyacente / Ticker": "GGAL", "Vencimiento(s)": "v",
         "Strikes": "s", "Prob. Éxito (%)": 60.0, "Valor Esperado": 1.0, "TNA Esperada (%)": 50.0, "Score Cuanti": 10.0,
         "Escenario 5%": 1.0}
        for i in range(n_estrategias)
    ]
    return pd.DataFrame(filas)


def test_la_ia_recibe_todas_las_filas_y_las_columnas_reales():
    """Regresión: antes head(12) dejaba afuera familias enteras y se pedían columnas inexistentes."""
    df = _df_ia(20)
    regs = registros_para_ia(df)
    assert len(regs) == 20
    assert "Prob. Éxito (%)" in regs[0] and "Valor Esperado" in regs[0]
    assert "Escenario 5%" not in regs[0]
    prompt = construir_prompt(df, 35.0)
    assert "Estrategia 19" in prompt and "35.0%" in prompt


def test_respaldo_entre_proveedores(monkeypatch):
    monkeypatch.setattr(config, "IA_PROVEEDORES", ["gemini", "groq"])
    monkeypatch.setattr(
        config, "PROVEEDORES_IA",
        {"gemini": {"tipo": "gemini", "modelo": "m", "api_key": "k"},
         "groq": {"tipo": "openai", "base_url": "u", "modelo": "m", "api_key": "k"}},
    )

    def gemini_sin_cuota(cfg, prompt):
        raise ErrorIA("HTTP 429", reintentable=False)

    monkeypatch.setitem(ai_analyzer._LLAMADORES, "gemini", gemini_sin_cuota)
    monkeypatch.setitem(ai_analyzer._LLAMADORES, "openai", lambda cfg, prompt: "informe de respaldo")
    res = analizar_estrategias(_df_ia(), 35.0)
    assert res == AnalisisIA("informe de respaldo", "groq")


def test_proveedor_sin_api_key_se_saltea_y_si_todos_fallan_devuelve_none(monkeypatch):
    monkeypatch.setattr(config, "IA_PROVEEDORES", ["gemini"])
    monkeypatch.setattr(config, "PROVEEDORES_IA", {"gemini": {"tipo": "gemini", "modelo": "m", "api_key": ""}})
    assert analizar_estrategias(_df_ia(), 35.0) is None


def test_errores_transitorios_se_reintentan(monkeypatch):
    monkeypatch.setattr(ai_analyzer.time, "sleep", lambda s: None)
    llamadas = {"n": 0}

    def inestable(cfg, prompt):
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            raise ErrorIA("HTTP 503", reintentable=True)
        return "ok"

    monkeypatch.setitem(ai_analyzer._LLAMADORES, "gemini", inestable)
    assert ai_analyzer._con_reintentos({"tipo": "gemini"}, "p") == "ok"
    assert llamadas["n"] == 3


# ---- Telegram ---------------------------------------------------------------
def test_texto_largo_sin_separadores_se_divide_bajo_el_limite():
    """Regresión: el informe de la IA (sin '━━━') superaba 4096 y Telegram lo rechazaba entero."""
    texto = "\n".join(f"Línea {i} " + "palabra " * 20 for i in range(200))
    partes = dividir_mensaje(texto)
    assert len(partes) > 1
    assert all(len(p) <= 4000 for p in partes)
    assert "".join(partes).replace("\n", "") == texto.replace("\n", "")


def test_una_sola_linea_gigante_tambien_se_corta():
    texto = "x" * 9000
    partes = dividir_mensaje(texto)
    assert all(len(p) <= 4000 for p in partes)
    assert "".join(partes) == texto


def test_empaquetar_no_parte_bloques():
    bloques = ["a" * 1500, "b" * 1500, "c" * 1500]
    partes = empaquetar(bloques, sep="\n\n")
    assert partes == ["a" * 1500 + "\n\n" + "b" * 1500, "c" * 1500]


def test_md_a_html():
    assert md_a_html("**hola** <b> & más") == "<b>hola</b> &lt;b&gt; &amp; más"
    assert md_a_html("## Título") == "<b>Título</b>"
    assert md_a_html("* punto uno") == "• punto uno"
