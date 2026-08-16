# Etapa 1.6 — preparación del smoke test de integración real

## Estado

La implementación está preparada, pero esta etapa **no se declara finalizada**: el checkout no
tiene remote Git ni token de GitHub, por lo que no fue posible disparar GitHub Actions ni observar
una ejecución verde. El proxy del sandbox también bloquea PyPI y todos los destinos HTTPS.

## Ejecuciones manuales preparadas

- `Tests`: instala Python 3.12 y `.[dev]`, luego ejecuta obligatoriamente `pytest -q`,
  `ruff check .` y `ruff format --check .`.
- `RSS smoke test`: ejecuta `python scripts/check_feeds.py` sin secretos.
- `AI Radar dry-run`: crea PostgreSQL, migra y ejecuta `python scripts/run_radar.py --dry-run`.
  Sólo inyecta `LLM_API_KEY`, `LLM_MODEL` y `LLM_BASE_URL` desde GitHub Secrets.

## Criterio para cerrar la etapa

1. ejecutar manualmente `Tests` y confirmar estado verde;
2. guardar la salida tabular real de los ocho feeds;
3. ejecutar dry-run con precios configurados y registrar eventos, tokens, costo y errores;
4. ejecutar `scripts/test_telegram.py` desde un host seguro y confirmar el mensaje de prueba.

Hasta completar esos cuatro puntos, cualquier cantidad de entradas RSS, fecha reciente, tokens,
costo o entrega Telegram permanece como “no verificado”, no como cero ni PASS.
