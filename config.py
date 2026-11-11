"""Configuración central.

Los secretos (tokens, API keys, credenciales) se leen SOLO de variables de
entorno o de un archivo .env local (que NO debe subirse a git).
Ver .env.example para la lista completa.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _env_float(nombre: str, defecto: float) -> float:
    try:
        return float(os.getenv(nombre, defecto))
    except (TypeError, ValueError):
        return float(defecto)


def _env_lista(nombre: str, defecto: str) -> list:
    return [x.strip() for x in os.getenv(nombre, defecto).split(",") if x.strip()]


# ----------------------------------------------------------------------------
# Secretos y destinos (solo desde el entorno)
# ----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Google Sheets: ID de la planilla + credenciales de la service account.
# Se puede pasar el JSON completo en GOOGLE_CREDENTIALS_JSON (ideal para
# GitHub Actions) o la ruta de un archivo en GOOGLE_CREDENTIALS_FILE.
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credenciales.json")

# ----------------------------------------------------------------------------
# Proveedores de IA (se prueban en el orden de IA_PROVEEDORES; se saltean los
# que no tengan API key). Casi todos usan el formato compatible con OpenAI.
# Los nombres de modelo cambian seguido: se pueden pisar con variables de entorno.
# ----------------------------------------------------------------------------
PROVEEDORES_IA = {
    "gemini": {
        "tipo": "gemini",
        "modelo": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
    },
    "groq": {
        "tipo": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "modelo": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "api_key": os.getenv("GROQ_API_KEY", ""),
    },
    "openrouter": {
        "tipo": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "modelo": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
    },
    "cerebras": {
        "tipo": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "modelo": os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
        "api_key": os.getenv("CEREBRAS_API_KEY", ""),
    },
    "mistral": {
        "tipo": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "modelo": os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
        "api_key": os.getenv("MISTRAL_API_KEY", ""),
    },
}
IA_PROVEEDORES = _env_lista("IA_PROVEEDORES", "gemini,groq,openrouter")

# ----------------------------------------------------------------------------
# Datos de mercado
# ----------------------------------------------------------------------------
BYMA_URL = os.getenv("BYMA_URL", "https://tablero.bymaeduca.com.ar/d/op.json")

# Solo se usa si el feed no trae la tasa libre de un vencimiento.
TASA_LIBRE_DEFAULT_PCT = _env_float("TASA_LIBRE_DEFAULT_PCT", 35.0)

# ----------------------------------------------------------------------------
# Precios de ejecución
#   "last"   : ÚLTIMO OPERADO del día (es lo único que trae el JSON de BYMA Educa).
#              - SLIPPAGE_PCT aproxima el costo de cruzar el spread: se compra a
#                último*(1+s) y se vende a último*(1-s).
#              - OPS_MIN: la pata debe haber operado al menos esa cantidad de veces
#                en la rueda (descarta precios viejos o sin operaciones).
#              - SINCRONIA_MAX_MIN: las patas deben haber operado con menos de esa
#                diferencia horaria entre sí.
#              - EDAD_MAX_MIN (0 = desactivado): cada pata debe haber operado a lo
#                sumo esa cantidad de minutos antes del último operado del subyacente
#                (evita mezclar precios de la mañana con un spot de la tarde).
#   "bid_ask": solo si algún día el feed trae puntas (hoy NO las trae):
#              ask para comprar, bid para vender.
# NUNCA se usa el precio teórico para calcular una estrategia.
# ----------------------------------------------------------------------------
MODO_PRECIO = os.getenv("MODO_PRECIO", "last")
SLIPPAGE_PCT = _env_float("SLIPPAGE_PCT", 0.02)
OPS_MIN = _env_float("OPS_MIN", 1)
SINCRONIA_MAX_MIN = _env_float("SINCRONIA_MAX_MIN", 30)
EDAD_MAX_MIN = _env_float("EDAD_MAX_MIN", 0)
SPREAD_REL_MAX = _env_float("SPREAD_REL_MAX", 0.5)  # solo modo bid_ask: (ask-bid)/mid máximo

# ----------------------------------------------------------------------------
# Ranking
#   Cada estrategia (Iron Condor Vendido, Bull Call Spread, ...) se rankea por
#   separado por "Score Cuanti" = exceso de retorno esperado (TNA, en puntos)
#   sobre la tasa libre.
# ----------------------------------------------------------------------------
PROB_EXITO_MIN = _env_float("PROB_EXITO_MIN", 0.25)  # prob. mínima de superar la tasa libre
EXIGIR_SUPERAR_TASA = True  # descarta estructuras con valor esperado <= tasa libre
TOP_LOCAL = 5     # mejores por (ticker, vencimiento, estrategia)
TOP_GLOBAL = 3    # mejores por estrategia en todo el mercado (Tabla A)
TOP_IA = 2        # filas por estrategia que se le mandan a la IA

# Escenarios de la Tabla B (variación % del subyacente al vencimiento)
ESCENARIOS_PCT = [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]

# Arbitrajes: solo strikes a menos de este % del spot
ARB_DISTANCIA_STRIKE_MAX = 0.05
