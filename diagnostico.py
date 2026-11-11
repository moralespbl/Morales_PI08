"""Diagnóstico: por qué no salen estructuras (o salen pocas).

Uso:  python diagnostico.py
No envía nada a Telegram ni a Sheets. Muestra:
  1. por subyacente: cuántas opciones tienen último operado, operaciones y volatilidad;
  2. cuántas estructuras salen con tu configuración y relajando de a un filtro,
     para ver cuál es el que más descarta.
"""
import logging

import pandas as pd

import config
from data_loader import BYMALoader
from main import calcular_universo

logging.basicConfig(level=logging.ERROR)  # silencia los avisos repetidos; acá resumimos nosotros


def contar(df, curva, **cambios):
    original = {k: getattr(config, k) for k in cambios}
    try:
        for k, v in cambios.items():
            setattr(config, k, v)
        res = calcular_universo(df, curva)
    finally:
        for k, v in original.items():
            setattr(config, k, v)
    return res


def main():
    df, curva = BYMALoader().descargar_y_procesar()
    print(f"\nOpciones: {len(df)} | Tasas por vencimiento (%): { {k: round(v * 100, 2) for k, v in curva.items()} }")
    print(f"Config: MODO_PRECIO={config.MODO_PRECIO} SLIPPAGE_PCT={config.SLIPPAGE_PCT} OPS_MIN={config.OPS_MIN} "
          f"SINCRONIA_MAX_MIN={config.SINCRONIA_MAX_MIN} EDAD_MAX_MIN={config.EDAD_MAX_MIN} PROB_EXITO_MIN={config.PROB_EXITO_MIN}")

    marcas = pd.DataFrame(
        {
            "ticker": df["ticker_base"],
            "con_last": df["last"] > 0,
            "con_ops": (df["last"] > 0) & (df["cant_ops"] >= max(config.OPS_MIN, 1)),
            "vol_hist": df["vol_hist"] > 0,
            "vol_impl": df["vol_impl"] > 0,
        }
    )
    tabla = marcas.groupby("ticker").agg(
        opciones=("ticker", "size"), con_last=("con_last", "sum"), con_ops=("con_ops", "sum"),
        vol_hist=("vol_hist", "sum"), vol_impl=("vol_impl", "sum"),
    )
    print("\nOPCIONES CON CADA DATO (por subyacente)")
    print(tabla.sort_values("opciones", ascending=False).to_string())

    escenarios = [
        ("Tu configuración", {}),
        ("Sin slippage", {"SLIPPAGE_PCT": 0.0}),
        ("Sincronía entre patas 240 min", {"SINCRONIA_MAX_MIN": 240}),
        ("Sin mínimo de operaciones", {"OPS_MIN": 0}),
        ("Sin prob. mínima ni exigir superar la tasa", {"PROB_EXITO_MIN": 0.0, "EXIGIR_SUPERAR_TASA": False}),
        ("TODO relajado", {"SLIPPAGE_PCT": 0.0, "SINCRONIA_MAX_MIN": 10_000, "OPS_MIN": 0, "EDAD_MAX_MIN": 0,
                           "PROB_EXITO_MIN": 0.0, "EXIGIR_SUPERAR_TASA": False}),
    ]
    print("\nESTRUCTURAS GENERADAS SEGÚN EL FILTRO QUE SE RELAJA")
    for nombre, cambios in escenarios:
        res = contar(df, curva, **cambios)
        detalle = "" if res.empty else "  -> " + ", ".join(f"{k}: {v}" for k, v in res.groupby("Estrategia").size().items())
        print(f"  {nombre:<45} {len(res):>5}{detalle}")

    cols = ["symbol", "tipo", "strike", "suby_px", "last", "cant_ops", "hora", "vol_hist", "vol_impl", "dias_vto"]
    print("\nMuestra de 5 opciones:")
    print(df[[c for c in cols if c in df.columns]].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
