# Etapa 1.5 — validación y hardening

Fecha de validación: 2026-08-16 (UTC).

## CI

El checkout entregado no tiene un remote Git configurado y `gh pr status` no puede autenticarse
porque no existe `GH_TOKEN`. Por lo tanto, desde este entorno no es posible consultar el estado
remoto del workflow del PR. Se revisó localmente `.github/workflows/tests.yml`: usa Python 3.12,
instala `.[dev]` antes de ejecutar `ruff check`, `ruff format --check` y `pytest`. Se agregó
`.python-version` para que las herramientas locales seleccionen también Python 3.12.

En el runner local, `uv sync --extra dev` seleccionó correctamente Python 3.12 pero el proxy
bloqueó PyPI al resolver `pydantic-settings`. En consecuencia, `pytest` no pudo iniciar porque
SQLAlchemy no está preinstalado. Esto es una limitación comprobable del entorno, no un resultado
PASS: el workflow remoto debe considerarse la fuente de verdad una vez que exista un remote/token.
Ruff, format, compileall y la validación YAML sí se ejecutaron localmente.

## Smoke test de RSS

Se intentó descargar cada URL con redirects y timeout de 12 segundos. El proxy del entorno
rechazó todos los túneles HTTPS con `CONNECT 403`; `curl` reportó status de origen `000` y exit
code 56. Esto significa que **no se alcanzó ninguno de los servidores de origen**: el 403 no es
una respuesta de los feeds y no demuestra que estén rotos. Por esa razón no se modificó
silenciosamente ninguna fuente.

| Fuente | URL | HTTP de origen | Parse RSS/Atom | Entradas | Más reciente |
|---|---|---:|---|---:|---|
| OpenAI News | `https://openai.com/news/rss.xml` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| Google AI Blog | `https://blog.google/technology/ai/rss/` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| Google DeepMind | `https://deepmind.google/discover/blog/rss.xml` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| Microsoft AI Blog | `https://blogs.microsoft.com/ai/feed/` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| AWS Machine Learning Blog | `https://aws.amazon.com/blogs/machine-learning/feed/` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| NVIDIA AI Blog | `https://blogs.nvidia.com/blog/category/deep-learning/feed/` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |
| Apple Machine Learning Research | `https://machinelearning.apple.com/rss.xml` | no alcanzado (`000`; proxy `CONNECT 403`) | no evaluable | n/d | n/d |

La primera ejecución en un host con salida a Internet debe repetir esta tabla antes de confiar
en el seed. Sólo se debe reemplazar una URL después de verificar una alternativa publicada por
el mismo dominio oficial.

## Evento existente con una fuente posterior de mayor calidad

### Comportamiento actual

Un artículo posterior con URL nueva se persiste y se vincula al evento por hash de contenido o
similitud de título. Queda auditado como `duplicate`; el evento no vuelve al LLM y conserva el
análisis, confidence y scores originales. Por eso una fuente primaria posterior mejora la
trazabilidad del evento, pero todavía no mejora su análisis ni puede disparar una alerta que el
primer artículo no justificó.

La arquitectura no bloquea el reanálisis: la relación evento-artículos conserva todos los
orígenes, `Source` conserva `trust_level/is_primary`, y los estados de evento están separados de
los registros de candidatos.

### Política mínima futura propuesta (`needs_reanalysis`)

Sin implementarla en esta etapa, una política futura debería marcar el evento cuando un artículo
nuevo cumpla al menos una condición verificable:

1. pasa de no tener fuente primaria a tener una fuente primaria;
2. aumenta el máximo `trust_level` del evento en un umbral (por ejemplo, 15 puntos);
3. aporta contenido sustancialmente distinto, no sólo otro título o URL;
4. el análisis anterior falló o tenía confidence bajo.

Un job posterior tomaría eventos `needs_reanalysis`, haría como máximo una nueva llamada con el
mejor conjunto de evidencia y guardaría la versión del análisis. Debe mantener la unicidad de
alerta, permitiendo una actualización sólo si el nuevo contenido supera un fingerprint/versionado
definido. Antes de implementarlo habrá que agregar estado/versiones mediante una migración, no una
nueva entidad o infraestructura.

## Revisión del prefilter

Se confirmó un falso negativo evidente: las reglas sólo buscaban frases exactas derivadas de los
topics YAML. Un producto con nombre nuevo y un anuncio como “Acme unveils Zeta, a new multimodal
model” podía descartarse aunque proviniera de un feed primario con trust 100.

La corrección es deliberadamente acotada: si no coincide ningún topic, sólo se conserva el item
cuando la fuente es primaria, tiene trust `>=95` y contiene una señal amplia de IA (`AI`, `LLM`,
`model`, `agent`, `multimodal`, etc.). Fuentes secundarias o de menor confianza mantienen el filtro
estricto. Esto reduce el falso negativo sin convertir el prefilter en un pase libre.
