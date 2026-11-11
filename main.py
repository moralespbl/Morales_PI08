"""Pipeline: BYMA -> estrategias -> ranking por estrategia -> Sheets -> IA -> Telegram.

Uso:
    python main.py              # corrida completa
    python main.py --dry-run    # calcula y muestra, sin enviar a Sheets ni a Telegram
"""
from __future__ import annotations

import argparse
import logging
import statistics
from typing import Dict, List

import pandas as pd

import config
from ai_analyzer import analizar_estrategias
from data_loader import BYMALoader
from ranking import ranking_por_estrategia, separar_tablas
from sheets_exporter import exportar_a_google_sheets, guardar_analisis
from strategies.arbitrajes_tasas import ArbitrajesTasasStrategy
from strategies.cobertura import CoberturaStrategy
from strategies.direccionales import DireccionalesStrategy
from strategies.neutrales import NeutralesStrategy
from strategies.volatilidad import VolatilidadStrategy
from telegram_notifier import enviar_resumen_telegram

log = logging.getLogger("main")

FAMILIAS = [
    NeutralesStrategy,
    VolatilidadStrategy,
    DireccionalesStrategy,
    CoberturaStrategy,
    ArbitrajesTasasStrategy,
]


def calcular_universo(df_chain: pd.DataFrame, curva: Dict[str, float]) -> pd.DataFrame:
    """Ejecuta todas las familias para cada (ticker, vencimiento) con la tasa de ESE vencimiento."""
    resultados: List[dict] = []
    errores = 0
    pares = df_chain[["ticker_base", "vencimiento"]].drop_duplicates().itertuples(index=False)
    for ticker, vto in pares:
        tasa = curva.get(vto)  # None -> la base usa TASA_LIBRE_DEFAULT_PCT
        for Familia in FAMILIAS:
            try:
                resultados.extend(Familia(ticker, vto, tasa).calcular_estructura(df_chain))
            except Exception:
                errores += 1
                log.exception("Falló %s para %s %s", Familia.__name__, ticker, vto)
    if errores:
        log.warning("%d cálculos fallaron (ver detalle arriba).", errores)
    return pd.DataFrame(resultados)


def main(dry_run: bool = False) -> None:
    loader = BYMALoader()
    df_chain, curva = loader.descargar_y_procesar()
    if df_chain.empty:
        log.error("No se pudieron cargar datos válidos de la cadena.")
        return
    if "ticker_base" not in df_chain.columns or "vencimiento" not in df_chain.columns:
        log.error("El DataFrame no contiene 'ticker_base' o 'vencimiento'.")
        return

    tasa_ref_pct = statistics.median(curva.values()) * 100.0 if curva else config.TASA_LIBRE_DEFAULT_PCT
    log.info("Tasa libre de referencia (mediana de la curva): %.2f%%", tasa_ref_pct)

    df_maestro = calcular_universo(df_chain, curva)
    if df_maestro.empty:
        log.warning(
            "No hay estructuras viables con los filtros actuales (MODO_PRECIO=%s, SINCRONIA_MAX_MIN=%s, "
            "OPS_MIN=%s, PROB_EXITO_MIN=%s). Corré 'python diagnostico.py' para ver cuál filtro las descarta.",
            config.MODO_PRECIO,
            config.SINCRONIA_MAX_MIN,
            config.OPS_MIN,
            config.PROB_EXITO_MIN,
        )
        return

    # Ranking POR ESTRATEGIA: cada una compite solo contra las de su mismo tipo
    df_top = ranking_por_estrategia(df_maestro, config.TOP_GLOBAL)
    tabla_a, tabla_b = separar_tablas(df_top)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1200)
    print("\n" + "=" * 80)
    print(f"🏆 TABLA A: RANKING EJECUTIVO (Top {config.TOP_GLOBAL} por estrategia)")
    print("=" * 80)
    print(tabla_a.to_string(index=False))
    print("\n" + "=" * 80)
    print("📊 TABLA B: MATRIZ DE SENSIBILIDAD (P&L por unidad según variación del subyacente)")
    print("=" * 80)
    print(tabla_b.to_string(index=False))

    if not dry_run:
        exportar_a_google_sheets(df_maestro, loader.filas_crudas)

    # Informe de IA (con respaldo entre proveedores)
    df_ia = ranking_por_estrategia(df_maestro, config.TOP_IA)
    df_ia, _ = separar_tablas(df_ia)
    analisis = analizar_estrategias(df_ia, tasa_ref_pct)
    if analisis:
        print("\n" + "=" * 80)
        print(f"🧠 INFORME OPERATIVO ({analisis.proveedor})")
        print("=" * 80)
        print(analisis.texto)

    if dry_run:
        log.info("--dry-run: no se envía nada a Sheets ni a Telegram.")
        return

    if analisis:
        guardar_analisis(analisis.texto, analisis.proveedor)
    enviar_resumen_telegram(
        df_top,
        tasa_ref_pct,
        texto_ia=analisis.texto if analisis else None,
        proveedor_ia=analisis.proveedor if analisis else None,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="no envía a Google Sheets ni a Telegram")
    main(dry_run=parser.parse_args().dry_run)
