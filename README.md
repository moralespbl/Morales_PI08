# BYMA Options Quantitative Engine (versión corregida)

Descarga la cadena de opciones de BYMA, calcula estructuras de 5 familias, las **rankea por
estrategia**, manda un informe a una IA (con respaldo entre proveedores) y publica el resultado en
Telegram y Google Sheets.

## Puesta en marcha

```bash
pip install -r requirements.txt
cp .env.example .env      # completar tokens/keys (NUNCA subir .env a git)
python main.py --dry-run  # calcula y muestra, sin enviar nada
python main.py            # corrida completa
pytest                    # tests (pip install -r requirements-dev.txt)
```

Si no aparece ninguna estructura, corré `python diagnostico.py`: muestra cuántas salen con tu
configuración y qué pasa al relajar cada filtro (slippage, sincronía, operaciones mínimas, probabilidad).

## Qué datos trae el feed

El JSON de `tablero.bymaeduca.com.ar/d/op.json` trae solo el **último operado** (`ultimo`, `cant_ops`,
`hora`), **sin bid/ask**. Por eso el modo de precio por defecto es `last`, con estos controles de calidad:

- `SLIPPAGE_PCT` (2%): se compra a último×(1+s) y se vende a último×(1−s), para aproximar el spread.
- `OPS_MIN` (1): la opción debe haber operado en la rueda; si no, su "último" puede estar viejo.
- `SINCRONIA_MAX_MIN` (30): las patas deben haber operado con menos de 30 minutos de diferencia.
- `EDAD_MAX_MIN` (0 = apagado): cada pata debe haber operado a lo sumo N minutos antes del último
  operado del subyacente (evita mezclar precios de la mañana con un spot de la tarde).

## Cómo se rankea

1. **Precios**: último operado ± slippage (o ask/bid si algún día el feed trae puntas). Nunca se usa el
   precio teórico: en el feed viene calculado a partir del propio último, así que no aporta información.
2. Cada estructura se define como lista de patas (call/put/spot, compra/venta). El payoff, la pérdida y
   ganancia máximas, los break-even y los escenarios salen de ahí, de forma exacta.
3. **Probabilidad y valor esperado**: el subyacente al vencimiento se modela lognormal con deriva =
   tasa libre del vencimiento y **volatilidad histórica**. Es decir, no hay sesgo direccional: se mide
   si las primas de mercado "regalan" algo respecto de la volatilidad realizada.
4. `Prob. Éxito (%)` = probabilidad de superar la tasa libre. `Score Cuanti` = exceso de TNA esperada
   sobre la tasa libre (en puntos).
5. Se descartan las estructuras con valor esperado <= tasa libre o con probabilidad < `PROB_EXITO_MIN`.
6. **El ranking es por `Estrategia`** (Iron Condor Vendido, Bull Call Spread, Collar, ...): cada una
   compite solo contra las de su mismo tipo. Tabla A = top 3 de cada una.

## Qué se corrigió respecto de la versión anterior

| Problema | Corrección |
|---|---|
| Token de Telegram, API key de Gemini y credenciales de Google en el código/zip | Todo por variables de entorno; `.gitignore`; **rotar las credenciales viejas** |
| Las estrategias pedían `"ultimo"` (no existe) y caían siempre al precio teórico | Usan el último operado real (+ slippage, operaciones mínimas, sincronía); el teórico no se usa |
| Reversión: fórmula sin strike, signos mal, escenarios absurdos | Reescrita; test de payoff constante |
| Iron Condor Comprado: débito con signo invertido y payoff incorrecto | Definido como espejo exacto del vendido |
| Score no comparable (multiplicadores ×1000, ×500...), R/R fijo en Volatilidad | Un solo criterio, ranking por estrategia |
| La IA recibía `head(12)` (dejaba afuera familias) y columnas inexistentes | Recibe las filas completas con las columnas reales |
| Mensajes de Telegram >4096 caracteres eran rechazados | División genérica por líneas + conversión Markdown→HTML |
| Tasas distintas (29.62 / 35 / 40) e ignoraba la curva del loader | Se usa la tasa de cada vencimiento |
| `except: continue` ocultaba errores | `logging.exception` con contexto |
| `dias_vto or 30` (0 días contaba como 30) | Se omiten los vencimientos del día |
| Código duplicado en 5 archivos; `analytics.py`, `ai_reporter.py` y `test_loader.py` sin uso | Núcleo común en `strategies/base.py`; archivos muertos eliminados |
| `requirements.txt` vacío | Completo |

## Límites conocidos (no modelados)

- Con precios de último operado, un "arbitraje" puede ser solo una diferencia de horario entre patas o
  contra el spot: confirmalo siempre contra el libro de órdenes antes de operar.
- Las opciones de BYMA son **americanas**: hay riesgo de ejercicio anticipado en las patas vendidas.
- No se descuentan comisiones ni derechos de mercado, ni costos de la venta en corto (reversión).
- El payoff se evalúa al vencimiento (no hay valuación intermedia).
- El score favorece estructuras baratas con ventaja esperada: una probabilidad mínima más alta
  (`PROB_EXITO_MIN=0.4`, por ejemplo) las vuelve más conservadoras.
- Esto es una herramienta de análisis, no asesoramiento financiero.
