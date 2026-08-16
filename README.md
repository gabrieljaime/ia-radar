# AI Radar

AI Radar es un radar personal de inteligencia tecnológica. Este vertical slice consulta fuentes RSS oficiales, normaliza y agrupa artículos en eventos, descarta ruido antes de pagar un análisis, evalúa cada evento contra tres perfiles en una sola llamada LLM, persiste el resultado y envía una única alerta crítica por Telegram.

## Alcance implementado

```text
RSS → normalize → event deduplication → prefilter
    → one structured LLM analysis (3 profiles) → deterministic scoring
    → PostgreSQL → one consolidated Telegram alert
```

FastAPI expone solamente `GET /health` y `GET /ready`. Tavily, GitHub, arXiv, digest, feedback, research agents, embeddings, dashboard y la API operacional están deliberadamente fuera de esta fase.

## Requisitos

- Python 3.12
- Docker con Compose
- Una API LLM compatible con Chat Completions y `response_format: json_schema`
- Opcional para ejecutar alertas: bot y chat de Telegram

## Configuración local

```bash
cp .env.example .env
docker compose up -d postgres
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
```

Complete en `.env`:

- `LLM_API_KEY`: obligatoria para una corrida real.
- `LLM_MODEL`: nombre de un modelo que soporte structured outputs.
- `LLM_BASE_URL`: base URL del proveedor compatible.
- `TELEGRAM_BOT_TOKEN`: necesaria para enviar alertas; se obtiene creando un bot con BotFather.
- `TELEGRAM_CHAT_ID`: chat receptor. En ausencia de ambas variables Telegram queda desactivado, pero el pipeline puede procesar y persistir.
- `DATABASE_URL`: la provista funciona con Compose; para Supabase use la URL PostgreSQL con el SSL requerido por la instancia.

No hay claves reales en el repositorio y los valores vacíos no son claves de ejemplo.

## Ejecución

```bash
python scripts/run_radar.py
```

Para una corrida real sin entregar mensajes a Telegram:

```bash
python scripts/run_radar.py --dry-run
```

El dry-run persiste normalmente y, si hay credenciales LLM, imprime cada alerta elegible entre
`WOULD_ALERT` y `END_WOULD_ALERT`. Sin credenciales procesa hasta el prefilter y deja los eventos
en estado `pending` para que una corrida posterior pueda analizarlos.

Para validar feeds sin LLM ni Telegram:

```bash
python scripts/check_feeds.py
```

Para probar exclusivamente la entrega de Telegram, sin modificar thresholds:

```bash
python scripts/test_telegram.py
```

Cada corrida registra un `run_id`. Los fallos de una fuente, un artículo, structured output o Telegram quedan aislados. Cada item recolectado tiene un `candidate_record`; los descartes se guardan como `duplicate`, `already_seen`, `too_old`, `low_relevance`, `low_trust`, `high_hype`, `invalid` o `analysis_failed` sin sobrescribir la historia del artículo original.

Para levantar únicamente los probes HTTP:

```bash
uvicorn app.main:app --reload
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## Fuentes y perfiles

- `config/sources.yaml` contiene ocho feeds oficiales configurables.
- `config/profiles/educator.yaml`, `course.yaml` y `bank.yaml` contienen temas, pesos, entidades y acciones.
- Agregar una fuente o tema no requiere cambios de código; la configuración se valida al cargarla.

## Tests y lint

Los tests no llaman servicios externos ni consumen APIs pagas. RSS, LLM y Telegram tienen fixtures/fakes o transportes HTTP mockeados.

```bash
pytest
ruff check .
ruff format --check .
```

Los fixtures reproducibles están en `tests/fixtures/`.

Los workflows `Tests`, `RSS smoke test` y `AI Radar dry-run` pueden iniciarse manualmente con
`workflow_dispatch`. El dry-run toma credenciales exclusivamente de GitHub Secrets.

## Idempotencia y entregas

- URL canónica única impide insertar dos veces el mismo artículo.
- La similitud conservadora de títulos agrupa coberturas distintas en un evento.
- Sólo los eventos nuevos llegan al LLM.
- Un constraint permite una única alerta inmediata de Telegram por evento.
- La alerta se persiste como `pending` antes del request y luego queda `sent` o `failed`; un fallo no borra su estado ni provoca reenvíos automáticos ambiguos.

Consulte la propuesta y el plan posterior en [`docs/architecture-proposal.md`](docs/architecture-proposal.md).
