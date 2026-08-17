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
- `OUTPUT_LANGUAGE`: idioma del contenido generado (`es` por defecto); nombres técnicos, APIs,
  frameworks y nombres propios se conservan en su idioma original.
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

Para validar juntas todas las fuentes RSS, `web_changelog` y `web_articles`, incluyendo estado HTTP,
cantidad de entradas, fecha más reciente y estado de parsing, sin llamar al LLM:

```bash
python scripts/check_sources.py
```

Para inspeccionar y calibrar la última corrida persistida, sin consumir llamadas LLM ni acceder
a servicios externos:

```bash
python scripts/show_latest_run.py
python scripts/show_latest_run.py --details
```

También se puede seleccionar una corrida con `--run-id <UUID>` o limitar la salida con `--limit`.

Para inspeccionar la evidencia cruda de un `candidate_record` y distinguir errores de collector,
dedupe o análisis, sin llamadas externas:

```bash
python scripts/show_candidate.py <candidate-record-uuid>
```

Para revisar el digest sin enviar Telegram ni crear una reserva de envío:

```bash
python scripts/send_digest.py --dry-run
```

Para enviarlo utilizando exclusivamente análisis ya persistidos:

```bash
python scripts/send_digest.py
```

Durante el desarrollo, `--force` permite ignorar la protección contra duplicados:

```bash
python scripts/send_digest.py --force
```

El digest admite además `--hours 48` y `--run-id <UUID>`. No consulta RSS, no recalcula
scores y realiza cero llamadas al LLM; el único acceso externo de un envío real es Telegram.

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

## Fuentes y perfiles dinámicos

- `config/sources.yaml` agrupa fuentes configurables por tipo: `rss`, `web_changelog`,
  `web_articles`, `github_releases` y `huggingface_models`.
- `rss` consume feeds estructurados; `web_changelog` extrae releases o cambios técnicos de una
  página oficial; `web_articles` extrae solamente las tarjetas visibles de un índice editorial.
  Siempre se prefiere un RSS/Atom oficial y estable al parser HTML.
- Las fuentes `web_changelog` usan parsers HTML pequeños y específicos; cada entrada se convierte
  en un `Candidate` independiente y la URL canónica existente conserva la idempotencia entre corridas.
- Para agregar una fuente RSS se agrega una entrada bajo `rss`. Para un changelog se agrega bajo
  `web_changelog` con `parser`, `enabled`, `trust_level`, `is_primary` y, cuando corresponda,
  `requires_primary_verification`.
- Cada parser de `web_articles` recibe HTML y URL base y devuelve una lista uniforme de
  `ArticleIndexItem(title, url, published_at, summary)`. Para agregar uno, implementar una función
  específica en `app/collectors/web_articles.py`, registrarla en `PARSERS`, añadir fixtures locales
  de estructura válida y cambiada, y habilitar la fuente sólo después de `check_sources.py`.
  El collector hace una petición al índice y nunca descarga el cuerpo de cada artículo.
- `github_releases` consume la API oficial de GitHub, ignora drafts y no inspecciona commits, PRs
  ni tags. `huggingface_models` consulta la API pública por organización y usa `model id` y
  `createdAt`; cambios posteriores de README o metadata conservan la misma identidad.
- La evidencia secundaria se persiste con `requires_primary_verification` y una evidencia primaria
  posterior actualiza el mismo evento. La política de alerta inmediata conserva por ahora la lógica
  existente: distinguir automáticamente cobertura secundaria de análisis original del autor requiere
  una señal editorial explícita y queda para una iteración posterior; no se bloquean análisis propios
  sólo por publicarse en una fuente experta.
- Cada YAML dentro de `config/profiles/` define un perfil con `slug`, `name`, `icon`,
  `description`, señales gratuitas y `enabled`.
- Agregar una fuente o tema no requiere cambios de código; la configuración se valida al cargarla.

Para desactivar temporalmente un perfil sin borrar sus scores históricos:

```yaml
slug: bank_risk
name: Bank Risk Intelligence
icon: "🏦"
enabled: false
```

Para agregar un interés nuevo, alcanza con crear otro YAML:

```yaml
slug: my_profile
name: My Profile
icon: "🔎"
enabled: true
description: Novedades relevantes para este interés.
topics:
  relevant_topic: 1.0
```

Todos los perfiles activos se incorporan automáticamente a la misma llamada LLM por evento. Un
perfil deshabilitado no participa del prompt, scoring, alerta, digest ni visualización actual, pero
sus registros históricos permanecen en PostgreSQL.

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

## Producción en servidor Linux

El deployment estable usa Docker Compose para `postgres` y `radar`, y timers systemd del host para
Radar, digest y health de fuentes. GitHub Actions no programa ejecuciones de producción. Consulte
[`docs/production-deployment.md`](docs/production-deployment.md) para instalación Ubuntu desde cero,
validación sin Telegram, operación, backups, restore y rollback.
