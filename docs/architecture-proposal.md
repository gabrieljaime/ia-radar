# AI Radar — propuesta de arquitectura del MVP

> **Alcance de esta etapa:** este documento define la solución; no implementa funcionalidades. La prioridad es validar si el radar encuentra pocas novedades realmente valiosas con una operación simple, trazable y menor a USD 5/mes.

## 1. Arquitectura propuesta

Se propone un **monolito modular asíncrono** en Python. FastAPI, los comandos manuales y los workflows de GitHub Actions serán tres adaptadores de entrada al mismo servicio de aplicación; ninguno contendrá lógica de negocio. Un único despliegue y un único PostgreSQL evitan colas, caches y coordinación distribuida.

```text
GitHub Actions / CLI / FastAPI
              │
              ▼
      RadarApplicationService
              │ crea un pipeline_run y coordina
              ▼
 collect → normalize → deduplicate → prefilter → verify → analyze → score
              │                                           │
              └──────── repositories / unit of work ──────┘
                                  │
                              PostgreSQL
                                  │
                          alert / daily digest
                                  │
                           Telegram Bot API

Puertos externos: Collector, WebSearchProvider, LLMProvider, AlertChannel
Adaptadores iniciales: RSS/GitHub/arXiv/Tavily/proveedor LLM/Telegram
```

### Límites de módulos

- **Domain:** modelos y políticas puras (canonicalización, deduplicación, scoring, elegibilidad de alertas). No conoce FastAPI, SQLAlchemy ni proveedores.
- **Application/pipeline:** casos de uso y orden de etapas; opera con puertos y una unidad de trabajo. Cada etapa recibe y devuelve estructuras tipadas.
- **Infrastructure:** SQLAlchemy, clientes HTTP, collectors, proveedor LLM, Tavily y Telegram.
- **Entrypoints:** durante las etapas 0 y 1, FastAPI sólo ofrece `/health` y `/ready`; el
  script manual ejecuta el caso de uso. La API operacional se posterga explícitamente.
- **Configuration:** settings secretos desde variables de entorno; fuentes, consultas y perfiles versionados en YAML y validados con Pydantic al arrancar.

No se necesita una cola en el MVP: cada corrida procesa un volumen acotado, con concurrencia limitada mediante `asyncio`. Un bloqueo asesor de PostgreSQL evita dos ejecuciones solapadas. Los fallos por fuente se aíslan y registran sin abortar la corrida completa.

## 2. Árbol definitivo del proyecto

```text
ai-radar/
├── app/
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── schemas.py
│   │   └── routes.py
│   ├── application/
│   │   ├── radar_service.py
│   │   ├── digest_service.py
│   │   └── feedback_service.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── enums.py
│   │   ├── scoring.py
│   │   └── policies.py
│   ├── pipeline/
│   │   ├── types.py
│   │   ├── normalize.py
│   │   ├── deduplicate.py
│   │   ├── prefilter.py
│   │   ├── verify.py
│   │   ├── analyze.py
│   │   ├── score.py
│   │   └── orchestrator.py
│   ├── collectors/
│   │   ├── base.py
│   │   ├── rss.py
│   │   ├── web_search.py
│   │   ├── github.py
│   │   └── arxiv.py
│   ├── profiles/
│   │   ├── loader.py
│   │   └── models.py
│   ├── search/
│   │   ├── base.py
│   │   └── tavily.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── schemas.py
│   │   ├── prompts.py
│   │   └── provider.py
│   ├── alerts/
│   │   ├── base.py
│   │   ├── telegram.py
│   │   ├── formatting.py
│   │   └── digest.py
│   ├── db/
│   │   ├── models.py
│   │   ├── repositories.py
│   │   ├── session.py
│   │   └── unit_of_work.py
│   ├── cost/
│   │   ├── governor.py
│   │   └── pricing.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── http.py
│   │   └── exceptions.py
│   └── main.py
├── config/
│   ├── sources.yaml
│   ├── queries.yaml
│   └── profiles/
│       ├── educator.yaml
│       ├── course.yaml
│       └── bank.yaml
├── migrations/
│   ├── versions/
│   └── env.py
├── scripts/
│   ├── run_radar.py
│   └── send_digest.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── conftest.py
├── docs/
│   └── architecture-proposal.md
├── .github/workflows/
│   ├── radar.yml
│   └── tests.yml
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── .dockerignore
├── .env.example
├── pyproject.toml
└── README.md
```

La diferencia principal respecto del árbol sugerido es explicitar `domain`, `application` y `unit_of_work`: esto evita que el orquestador, la API o los adaptadores acumulen reglas y facilita sustituir proveedores sin adoptar un framework adicional.

## 3. Modelo de datos

Se adopta **evento como entidad visible** desde el inicio. Simplificarlo a un `event_hash` dentro de `articles` haría difícil representar múltiples fuentes y podría exigir una migración destructiva justo al validar el producto.

### Entidades

#### `sources`

`id UUID PK`, `name`, `source_type`, `base_url`, `trust_level SMALLINT CHECK 0..100`, `is_primary`, `enabled`, `created_at`; único `(source_type, base_url)`. Los valores YAML se sincronizan por clave natural.

#### `events`

`id UUID PK`, `event_hash`, `title`, `summary`, `what_happened`, `why_it_matters`, `what_changed`, `status`, `novelty_score`, `credibility_score`, `confidence`, `hype_probability`, `primary_source_verified`, `primary_source_url`, `first_seen_at`, `last_seen_at`, `created_at`, `updated_at`.

- `event_hash` es único y representa la mejor identidad determinística disponible.
- Checks: scores `0..100`; probabilidades/confidence `0..1`.
- Un evento conserva el análisis consolidado; los artículos conservan evidencia y procedencia.

#### `articles`

`id UUID PK`, `event_id FK NULL`, `source_id FK`, `external_id NULL`, `canonical_url`, `normalized_title`, `title`, `summary_raw`, `content_excerpt`, `published_at NULL`, `discovered_at`, `content_hash`, `metadata JSONB`, `status`, `created_at`, `updated_at`.

- Único por `canonical_url`; único parcial por `(source_id, external_id)` cuando existe.
- Índices en `content_hash`, `normalized_title`, `published_at`, `event_id` y `status`.
- `metadata` sólo aloja datos específicos de GitHub/arXiv (autores, categorías, tag), no datos centrales sin esquema.
- `discard_reason` registra de forma explícita `duplicate`, `too_old`, `low_relevance`,
  `low_trust`, `high_hype`, `already_seen`, `invalid`, `analysis_failed` o un equivalente
  futuro controlado.

#### `profiles`

`id UUID PK`, `slug UNIQUE`, `name`, `enabled`, `config_hash`, `created_at`, `updated_at`. El YAML es la fuente de verdad; la fila entrega identidad referencial y registra la versión evaluada.

#### `candidate_records`

Auditoría append-only de cada item emitido por un collector, aun cuando ya exista o sea
inválido. Vincula opcionalmente artículo/evento y registra `status` y `discard_reason`; de
este modo un intento `already_seen` no altera el motivo ni la procedencia del artículo original.

#### `event_scores`

`id UUID PK`, `event_id FK`, `profile_id FK`, `relevance_score CHECK 0..100`, `relevance_reason`, `suggested_action NULL`, `related_topics JSONB`, `related_classes JSONB`, `profile_config_hash`, `created_at`, `updated_at`; único `(event_id, profile_id, profile_config_hash)`. Se puntúa el evento, no cada artículo duplicado.

#### `alerts`

`id UUID PK`, `event_id FK`, `alert_type`, `channel`, `content_fingerprint`, `sent_at NULL`, `delivery_status`, `provider_message_id NULL`, `error_code NULL`, `created_at`; único `(event_id, alert_type, channel, content_fingerprint)`. No lleva `profile_id`: una notificación consolida todos los perfiles. Los perfiles incluidos pueden reconstruirse desde `event_scores`.

#### `feedback`

`id UUID PK`, `event_id FK`, `profile_id FK NULL`, `feedback_type`, `provider_callback_id UNIQUE NULL`, `created_at`; check/enum para `relevant`, `not_relevant`, `more_like_this`, `saved`, `investigate`. `investigate` se persiste pero aún no dispara un agente.

#### `pipeline_runs`

`id UUID PK` (también `run_id` de logs), `trigger`, `status`, contadores, `started_at`, `finished_at NULL`, `error_summary JSONB NULL`. Permite observabilidad y auditoría sin plataforma externa.

#### `usage_records`

`id UUID PK`, `run_id FK`, `provider`, `operation`, `quantity`, `input_tokens NULL`, `output_tokens NULL`, `estimated_cost_usd NUMERIC`, `occurred_at`. Índice por fecha; el consumo mensual se calcula en SQL. Es preferible un ledger a un contador mutable.

### Relaciones e idempotencia

```text
source 1──N article N──1 event 1──N event_score N──1 profile
                              ├──N alert
                              └──N feedback
candidate_record N──0..1 article / event
pipeline_run 1──N usage_record
```

Las claves únicas son la última barrera de idempotencia. Un `upsert` de artículo ocurre antes del trabajo pagado; el evento se asigna por coincidencia exacta o aproximada. La alerta se reserva en estado `pending` con su `content_fingerprint` antes de enviarla, y se marca `sent` después. Un reintento no crea otra alerta. Para recuperarse de una caída entre envío y confirmación existe un pequeño riesgo inevitable sin idempotency key de Telegram; se registra `provider_message_id` y los `pending` ambiguos no se reenvían automáticamente.

## 4. Flujo end-to-end

1. **Inicio:** se valida configuración, se crea `pipeline_run/run_id` y se intenta adquirir un advisory lock.
2. **Collect:** cada collector devuelve `CollectedItem`; timeouts, retries con backoff y concurrencia limitada por host. Un fallo queda asociado a la fuente y no cancela las demás.
3. **Normalize:** se limpian texto/fechas, se normaliza título y URL (host en minúscula, fragmentos y tracking params eliminados, query params relevantes preservados) y se calculan hashes.
4. **Deduplicate exacto:** se busca `external_id`, URL canónica, hash de contenido y título normalizado. Se hace `upsert`; elementos ya procesados terminan aquí salvo que su contenido haya cambiado.
5. **Deduplicate aproximado / evento:** entre eventos recientes y temáticamente plausibles, RapidFuzz compara títulos y entidades/tokens significativos. Umbral alto agrupa; zona gris crea evento separado para evitar falsos merges. Las fuentes adicionales no elevan por sí solas el score.
6. **Prefilter gratuito:** reglas de recencia, idioma/texto mínimo, keywords de perfiles, confianza de fuente y ruido reducen candidatos antes del LLM. Genera prioridad preliminar, no el score final.
7. **Verify condicional:** sólo si el candidato preliminar es importante, nació en fuente secundaria y el presupuesto lo permite. Construye una búsqueda acotada de fuente primaria, valida dominio/concordancia y adjunta la evidencia; no hace crawling profundo.
8. **Analyze:** un único llamado LLM por evento produce `ArticleAnalysis` completo para los tres perfiles. Pydantic valida rangos/esquema; hay un solo reintento de reparación estructurada. Prompt versionado y contenido delimitado mitigan prompt injection.
9. **Score:** reglas determinísticas combinan evaluación del LLM, novedad, credibilidad, recencia, aplicabilidad, verificación y penalización de hype. El LLM aporta señales; el código decide categoría y elegibilidad. La fórmula y pesos serán configurables/versionados y testeables.
10. **Persist:** en una transacción se guardan evento, artículos, análisis, scores y usage. Estados permiten reanudar un evento fallido sin repetir etapas exitosas.
11. **Alert:** si el máximo score de perfiles es `>=90` y confidence `>=0.75`, se genera una sola alerta consolidada y segura para Telegram. La unicidad impide repetición.
12. **Digest:** una ejecución separada selecciona eventos `75..89`, no incluidos ya en alerta inmediata y no enviados con el mismo fingerprint; ordena por score, recencia y confidence.
13. **Cierre:** se agregan métricas/costos, se marca la corrida y se emite un log resumen con `run_id`.

## 5. Decisiones técnicas principales

- **Monolito modular y puertos tipados:** suficiente separación sin costo operativo de microservicios.
- **Async sólo en I/O:** `httpx.AsyncClient` compartido; scoring y heurísticas permanecen funciones sincrónicas puras.
- **SQLAlchemy 2 + psycopg 3 + Alembic:** PostgreSQL estándar, compatible con Supabase usando URL/SSL adecuados y sin extensiones obligatorias.
- **UUID generados por aplicación y UTC:** simplifica futuras migraciones; datetimes timezone-aware.
- **Protocols propios:** `Collector`, `WebSearchProvider.search/extract`, `LLMProvider.analyze_article` y `AlertChannel`. Los DTOs Pydantic son neutrales al proveedor.
- **Structured output real:** JSON Schema derivado de Pydantic v2 y validación local obligatoria; nada de parseo heurístico de texto.
- **Scoring híbrido:** el LLM explica/clasifica y una política determinística aplica pesos, umbrales y penalización de hype. Evita delegar decisiones operativas enteras al modelo.
- **Una llamada LLM por evento:** incluye los tres perfiles; reduce costo y mantiene comparabilidad.
- **PostgreSQL como coordinación:** constraints, transacciones y advisory lock; no Redis.
- **JSONB sólo para listas/metadata flexible:** campos consultados o con integridad requerida siguen normalizados.
- **Logging JSON con biblioteca estándar + formatter liviano:** contexto `run_id`, etapa y fuente; jamás secretos o contenido completo.
- **Retries selectivos:** sólo errores transitorios (`429`, `5xx`, timeout), con pocos intentos y jitter. No circuit breaker hasta observar una necesidad.
- **API de ejecución protegible:** en local funciona; en despliegue `POST /radar/run` deberá requerir un token administrativo. Los health endpoints no lo requieren.

## 6. Simplificaciones recomendadas para el MVP

1. **Entregar primero el slice RSS → PostgreSQL → LLM → Telegram.** Valida el supuesto central antes de integrar tres canales adicionales.
2. **Clustering aproximado sólo por títulos, ventana temporal y entidades/tokens.** RapidFuzz es barato y explicable; embeddings no justifican infraestructura ni costo inicial.
3. **Una única evaluación conjunta para tres perfiles.** Menos precisión aislada que tres prompts especializados, pero aproximadamente un tercio de llamadas y contexto común.
4. **Extractos, no scraping general.** RSS/Tavily proveen suficiente texto para validar utilidad; extracción arbitraria trae bloqueos, copyright y mantenimiento.
5. **Verificación binaria asistida por reglas.** Confirmar anuncio y dominio primario; no hacer fact-check exhaustivo ni investigación multi-hop.
6. **Digest Telegram sin newsletter HTML.** Un solo canal prueba alertas y feedback.
7. **Callbacks de feedback básicos.** Persistir la señal, pero no reentrenar ni reajustar automáticamente hasta reunir datos útiles.
8. **Costos por tabla de precios configurable.** Estimación contable, no conciliación de facturas en tiempo real.
9. **Sin scheduler dentro del proceso.** Actions y scripts manuales evitan workers siempre encendidos; el horario solicitado corresponde aproximadamente a `11,15,19,23 UTC` (Argentina UTC−3), sujeto a demoras propias de Actions.
10. **Inglés/español sin traducción separada.** El LLM resume en el idioma configurado dentro de la misma llamada.

## 7. Riesgos técnicos y de costos

| Riesgo | Impacto | Mitigación MVP |
|---|---|---|
| Presupuesto de USD 5 incompatible con alto volumen | Alto | Prefilter gratuito, una llamada/evento, límites diarios/mensuales, modelo económico configurable y parada de operaciones pagas |
| Precios/free tiers cambian | Alto | Tarifas configurables, ledger real de tokens y no asumir gratuidad en código |
| Falsos merges o duplicados de eventos | Alto | Umbral conservador, ventana temporal, evidencia de agrupación y posibilidad futura de reasignar artículos |
| Structured output inválido/alucinaciones | Alto | Schema estricto, reintento único, scoring determinístico, evidencia y confidence separados |
| Fuente primaria mal identificada | Medio/alto | Allowlist/dominio de organización cuando exista; guardar URL y no declarar verificado sólo por similitud textual |
| Prompt injection en artículos | Medio | Tratar contenido como datos delimitados, prompt fijo, sin tool execution desde el modelo |
| Cron de Actions no puntual y runners limitados | Medio | Horarios aproximados, ejecución idempotente y scripts manuales; considerar cron externo sólo si se vuelve relevante |
| Secretos/exposición de endpoint de ejecución | Alto | GitHub Secrets/.env, redacción de logs y auth administrativa antes de exponer públicamente |
| Duplicado Telegram tras caída ambigua | Medio | Outbox simplificada, fingerprint único y revisión de `pending`; aceptar raras omisiones antes que spam |
| Límites/bloqueos GitHub, arXiv, RSS, Tavily | Medio | User-Agent claro, caching lógico, ETag/Last-Modified futuro, backoff y aislamiento por fuente |
| Retención de extractos y términos de fuentes | Medio | Guardar extractos mínimos y links; no PDFs ni copias completas |
| PostgreSQL en GitHub Actions | Alto operativo | Actions no debe depender de DB efímera: requiere Supabase u otro PostgreSQL accesible; Compose queda para local |

El governor tendrá bandas `<60%`, `60–80%`, `80–95%` y `>95%`. Degradará primero búsquedas abiertas, luego verificaciones no críticas y finalmente todas las llamadas pagas. RSS, GitHub y arXiv continúan, pero sus candidatos quedan pendientes de análisis si éste requiere costo.

## 8. Dependencias externas necesarias

### Runtime Python

- `fastapi`, `uvicorn`: API/OpenAPI.
- `pydantic`, `pydantic-settings`, `PyYAML`: schemas y configuración.
- `sqlalchemy`, `psycopg[binary]`, `alembic`: persistencia/migraciones.
- `httpx`, `feedparser`: HTTP y RSS/Atom.
- `rapidfuzz`: similitud local.
- SDK del proveedor LLM sólo si aporta structured output fiable; en caso contrario, adaptador HTTP con `httpx`.

### Desarrollo

- `pytest`, `pytest-asyncio`, `respx`: tests y mocks HTTP.
- `ruff`: lint y formato.
- Opcionalmente `mypy` sólo después del MVP; no es necesario para el criterio inicial.

### Servicios

- PostgreSQL 15+ local por Docker Compose; PostgreSQL/Supabase accesible para ejecuciones remotas.
- Tavily para búsqueda/verificación (API key y límites configurados).
- Un proveedor LLM con JSON Schema/structured outputs y reporte de tokens.
- Telegram Bot API.
- GitHub API (token recomendado para rate limits) y API/feed público de arXiv.
- GitHub Actions para schedule/CI.

No se incorporarán LangChain, LangGraph, Redis, Qdrant, Kafka, Kubernetes ni base vectorial.

## 9. Preparado pero no implementado todavía

- Interfaz `SemanticDeduplicator` detrás de la implementación RapidFuzz, para embeddings futuros.
- Estado/acción `investigate` y método de aplicación `request_investigation(event_id)`, sin research agent.
- `AlertChannel` para email, Slack, WhatsApp o newsletter; sólo Telegram inicialmente.
- Versiones (`prompt_version`, `profile_config_hash`, `scoring_version`) para reevaluar sin perder trazabilidad.
- Modelo evento/artículo y reasignación, preparado para clustering mejorado y fuentes independientes.
- Cursor/paginación de API y filtros, suficientes para un futuro dashboard Next.js.
- Usage ledger extensible a nuevos proveedores y reportes semanales.
- Feedback acumulado para personalización offline; no modifica pesos automáticamente.
- Campos/servicios para tendencias, topic velocity y weekly intelligence report, pero sin jobs ni tablas prematuras específicas.
- Hook de extracción del buscador y metadata flexible, sin crawler general.

## 10. Plan de implementación por etapas

### Etapa 0 — contrato y cimientos

- Crear packaging, settings, logging, Docker/PostgreSQL, modelos/Alembic y configuración YAML validada.
- Definir DTOs, Protocols y fixtures; health/readiness.
- Criterio de salida: aplicación arranca, migración funciona y configuración inválida falla de forma clara.

### Etapa 1 — vertical slice que valida el producto

- RSS → normalize → deduplicate exacto/aproximado → prefilter → analyze → score → persist → Telegram.
- Tres perfiles, structured output, alertas consolidadas, `run_id`, scripts manuales.
- Tests unitarios de parsing, URLs, deduplicación, schemas, scoring, alertas e idempotencia.
- Criterio: dos ejecuciones con el mismo fixture generan un evento, una evaluación por perfil y como máximo una alerta.

### Etapa 2 — digest, feedback y API operativa

- Digest diario, callbacks Telegram y tabla feedback.
- Endpoints requeridos, paginación mínima y auth para operaciones mutantes si se despliega.
- Criterio: digest no repite alertas y callbacks son idempotentes.

### Etapa 3 — ampliar cobertura gratuita

- GitHub releases/tags/repos configurables y arXiv por consultas/categorías, sin PDFs.
- Robustez por fuente, rate limits y actualización incremental.
- Criterio: fallar una fuente no detiene otras y no duplica eventos existentes.

### Etapa 4 — búsqueda, verificación y gobierno de costos

- Tavily detrás de `WebSearchProvider`, queries YAML, verificación condicional.
- Usage ledger, tarifas, bandas de degradación y `GET /cost`.
- Criterio: ninguna operación paga ocurre sobre el límite; collectors gratuitos continúan.

### Etapa 5 — endurecimiento y automatización

- Suite completa con APIs mockeadas, integración PostgreSQL, Ruff, revisión de typing/secretos/logs.
- Dockerfile/Compose, Actions de tests y cron `11,15,19,23 UTC`, más digest diario.
- README operacional y prueba manual controlada end-to-end.
- Criterio final: `pytest` y lint pasan; `python scripts/run_radar.py` cumple el flujo acordado con costo registrado.

### Orden explícitamente postergado

Dashboard, embeddings, agentes de investigación, tendencias, aprendizaje automático por feedback y canales adicionales sólo se priorizarán después de medir durante varias semanas precisión, duplicados, costo por evento útil y tasa de interacción. La métrica principal del MVP será **eventos considerados útiles por el usuario / alertas y elementos de digest enviados**, acompañada por costo mensual y tasa de duplicados.
