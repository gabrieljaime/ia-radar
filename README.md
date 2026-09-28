# AI Radar

**English** | [Español](README.es.md)

A configurable radar that discovers relevant changes in artificial intelligence and turns them into actionable signals. It pulls from public sources, normalizes articles and groups them into events, discards noise before calling the LLM, evaluates each event against configurable profiles, stores the results, and can send a consolidated alert via Telegram.

The project is ready to run locally or on a Linux server. It contains no real credentials: keys and tokens are read exclusively from environment variables.

<p align="center">
  <img src="docs/images/ai-radar-infographic.svg" alt="AI Radar infographic: 55 public sources are collected, normalized, deduplicated and prefiltered before an LLM analyzes each event; results are scored per profile and delivered as Telegram alerts, a daily digest and a web dashboard." width="100%">
  <br><sub>Architecture overview (infographic in Spanish).</sub>
</p>

## Project status

This repository contains a working vertical slice. The FastAPI dashboard, collectors, scoring pipeline, PostgreSQL storage, and Telegram alerts are implemented. Tavily, feedback, research agents, embeddings, and a write-capable operational API are out of the current scope.

## What it does

```text
sources → normalize → event deduplication → prefilter
    → one structured LLM analysis (all active profiles) → deterministic scoring
    → PostgreSQL → one consolidated Telegram alert
```

FastAPI serves the operator dashboard, plus `GET /health` and `GET /ready`.

## Requirements

| What | Used for | Required |
| --- | --- | --- |
| [Git](https://git-scm.com/downloads) | Downloading the repository | Yes |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine + Compose plugin (Linux) | PostgreSQL and, optionally, the whole app | Yes |
| [Python 3.12](https://www.python.org/downloads/) | Only for option B (running the app outside Docker) | No |
| An API key for an LLM provider compatible with OpenAI Chat Completions and `response_format: json_schema` (e.g. OpenAI) | Analyzing and scoring events | For real runs |
| A Telegram bot and a chat ID | Receiving alerts and digests | No |

Without an API key the radar still collects and prefilters news; without Telegram it processes and stores everything but sends no messages.

## Step-by-step installation

### 1. Clone the repository

```bash
git clone https://github.com/gabrieljaime/ia-radar.git
cd ia-radar
```

### 2. Create the `.env` file

Linux / macOS:

```bash
cp .env.example .env
```

Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

### 3. Fill in `.env`

Open `.env` in any editor and set:

1. **Database password.** Replace `replace-with-a-long-random-password` with a long random
   password. It appears **twice** (in `POSTGRES_PASSWORD` and inside `DATABASE_URL`) and both must
   be identical. Use only letters and digits so nothing needs escaping in the URL. To generate one:
   - Linux / macOS: `openssl rand -hex 32`
   - Windows (PowerShell): `-join ((48..57)+(97..102) | Get-Random -Count 32 | % {[char]$_})`
2. **LLM** (needed to analyze events):
   - `LLM_API_KEY`: your provider key.
   - `LLM_MODEL`: a model that supports structured outputs (default `gpt-4.1-nano`).
   - `LLM_BASE_URL`: the provider's base URL (defaults to OpenAI).
   - `LLM_INPUT_COST_PER_MILLION_USD` / `LLM_OUTPUT_COST_PER_MILLION_USD`: optional, only used to
     estimate costs in the dashboard.
3. **Telegram** (optional):
   - `TELEGRAM_BOT_TOKEN`: talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and copy
     the token it returns.
   - `TELEGRAM_CHAT_ID`: send any message to your bot, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates`; the number in `"chat":{"id": ...}` is the
     chat ID.
   - If both are left empty, Telegram is disabled.
4. `OUTPUT_LANGUAGE`: language of the generated content (`es` by default; set `en` for English).
   Technical names, APIs, frameworks, and proper nouns are kept in their original language.

All other variables have sensible defaults. `.env` is listed in `.gitignore`: never commit it.

Then choose **one** of the two options below.

### 4A. Option A: everything in Docker (recommended)

No Python installation needed. With Docker Desktop running:

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm radar python -m alembic upgrade head
docker compose up -d radar
```

Open <http://localhost:8000> to see the dashboard. To check that it responds:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

First test run (analyzes with the LLM, stores results, and does **not** send Telegram messages):

```bash
docker compose run --rm radar python scripts/run_radar.py --dry-run
```

Any other script from the [Usage](#usage) section runs the same way, prefixed with
`docker compose run --rm radar`. For example:

```bash
docker compose run --rm radar python scripts/run_radar.py
docker compose run --rm radar python scripts/send_digest.py --dry-run
```

To stop everything: `docker compose down` (data is kept in the `ai_radar_postgres` volume;
`docker compose down -v` deletes it).

After updating the code (`git pull`), rebuild and apply migrations:

```bash
docker compose build
docker compose run --rm radar python -m alembic upgrade head
docker compose up -d radar
```

### 4B. Option B: local Python + PostgreSQL in Docker (development)

PostgreSQL runs in Docker and is exposed only on `127.0.0.1:5432` through
`docker-compose.dev.yml`; the app runs in a Python virtual environment.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres
```

Create the virtual environment and install dependencies:

Linux / macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

> If PowerShell blocks activation, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Create the tables and start the dashboard:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. In another terminal (with the virtual environment activated), do a
first test run:

```bash
python scripts/run_radar.py --dry-run
```

### 5. Schedule runs (optional)

The radar does not schedule itself: each execution of `scripts/run_radar.py` performs one pass.
For a Linux server there are ready-made systemd timers in `deploy/systemd/` and a full guide in
[`docs/production-deployment.md`](docs/production-deployment.md). Elsewhere you can use cron or
Windows Task Scheduler to run the command for your chosen option.

### Troubleshooting

- **`set POSTGRES_PASSWORD in .env`**: `.env` is missing or the variable is empty; see step 3.
- **`password authentication failed`**: the two passwords in `.env` don't match, or the password
  was changed after the database was created. On a fresh install you can start over with
  `docker compose down -v` (deletes the data).
- **`connection refused` in option B**: PostgreSQL is not running, or it was started without
  `-f docker-compose.dev.yml`, so port 5432 is not exposed.
- **`ports are not available ... 5432`, or `password authentication failed` in option B even though
  the passwords match**: another PostgreSQL is already using port 5432 on your machine (common on
  Windows). Add `POSTGRES_HOST_PORT=5433` to `.env`, change `:5432/` to `:5433/` in `DATABASE_URL`,
  and start PostgreSQL again with the option B command.
- **Port 8000 is already in use**: stop the other service using it, or in option B run
  `uvicorn app.main:app --reload --port 8001`.
- **Events stay `pending`**: `LLM_API_KEY` is missing; complete step 3 and run again.

For Supabase or another managed PostgreSQL, put its URL in `DATABASE_URL` (with whatever SSL the
instance requires) and use option B without starting the `postgres` container.

Never put real values in `.env.example`, workflows, fixtures, or documentation.

## Security and privacy

- Do not commit `.env`, tokens, LLM keys, database credentials, or private identifiers.
- If a credential ever appears in a tracked file or a shared log, revoke it and issue a new one;
  deleting the file does not remove it from Git history.
- GitHub Actions credentials must be configured as GitHub Secrets. The PostgreSQL test values in
  the workflows are ephemeral and only used inside the runner.
- The configured sources are public URLs. Review `config/sources.yaml` before adding internal
  endpoints or access-restricted feeds.

## Usage

The commands in this section assume option B (virtual environment activated). With option A,
prefix each `python scripts/...` with `docker compose run --rm radar`.

```bash
python scripts/run_radar.py
```

For a real run without delivering Telegram messages:

```bash
python scripts/run_radar.py --dry-run
```

A dry-run persists normally and, if LLM credentials are set, prints each eligible alert between
`WOULD_ALERT` and `END_WOULD_ALERT`. Without credentials it processes up to the prefilter and leaves
events in `pending` state so a later run can analyze them.

To validate feeds without the LLM or Telegram:

```bash
python scripts/check_feeds.py
```

To validate all RSS, `web_changelog`, and `web_articles` sources together, including HTTP status,
entry count, latest date, and parsing status, without calling the LLM:

```bash
python scripts/check_sources.py
```

To inspect and calibrate the latest persisted run, without LLM calls or external services:

```bash
python scripts/show_latest_run.py
python scripts/show_latest_run.py --details
```

You can also pick a run with `--run-id <UUID>` or limit the output with `--limit`.

To inspect the raw evidence of a `candidate_record` and tell collector, dedupe, or analysis errors
apart, without external calls:

```bash
python scripts/show_candidate.py <candidate-record-uuid>
```

To preview the digest without sending Telegram messages or reserving a delivery:

```bash
python scripts/send_digest.py --dry-run
```

To send it using only already-persisted analyses:

```bash
python scripts/send_digest.py
```

During development, `--force` bypasses the duplicate-delivery guard:

```bash
python scripts/send_digest.py --force
```

The digest also accepts `--hours 48` and `--run-id <UUID>`. It does not fetch feeds, does not
recompute scores, and makes zero LLM calls; the only external access of a real send is Telegram.

To test Telegram delivery alone, without changing thresholds:

```bash
python scripts/test_telegram.py
```

Every run records a `run_id`. Failures of a single source, article, structured output, or Telegram
delivery are isolated. Every collected item gets a `candidate_record`; discards are stored as
`duplicate`, `already_seen`, `too_old`, `low_relevance`, `low_trust`, `high_hype`, `invalid`, or
`analysis_failed` without overwriting the original article's history.

To start only the HTTP probes:

```bash
uvicorn app.main:app --reload
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## Sources and dynamic profiles

- `config/sources.yaml` groups configurable sources by type: `rss`, `web_changelog`,
  `web_articles`, `github_releases`, and `huggingface_models`.
- `rss` consumes structured feeds; `web_changelog` extracts releases or technical changes from an
  official page; `web_articles` extracts only the visible cards of an editorial index. A stable
  official RSS/Atom feed is always preferred over an HTML parser.
- The current selection covers official labs and changelogs, safety and alignment research on
  arXiv, the International AI Safety Report, and secondary analysis from WIRED and Normal
  Technology. It also includes institutional research from Google and Amazon, NIST standards,
  education adoption, AI infrastructure and economics, science, and markets. Books and individual
  articles used as references are not treated as feeds: their original publications are covered
  by the corresponding live channels.
- Each RSS feed processes at most its 100 most recent entries per run (configurable with `limit`)
  to avoid re-ingesting the full history of very large feeds.
- `web_changelog` sources use small, source-specific HTML parsers; each entry becomes an
  independent `Candidate`, and the existing canonical URL keeps runs idempotent.
- To add an RSS source, add an entry under `rss`. For a changelog, add it under `web_changelog`
  with `parser`, `enabled`, `trust_level`, `is_primary`, and, when applicable,
  `requires_primary_verification`.
- Each `web_articles` parser receives HTML and a base URL and returns a uniform list of
  `ArticleIndexItem(title, url, published_at, summary)`. To add one, implement a specific function
  in `app/collectors/web_articles.py`, register it in `PARSERS`, add local fixtures for both a
  valid and a changed structure, and enable the source only after `check_sources.py` passes. The
  collector makes one request to the index and never downloads individual article bodies.
- `github_releases` uses the official GitHub API, ignores drafts, and does not inspect commits, PRs,
  or tags. `huggingface_models` queries the public API per organization and uses `model id` and
  `createdAt`; later README or metadata changes keep the same identity.
- Secondary evidence is stored with `requires_primary_verification`, and later primary evidence
  updates the same event. The immediate-alert policy keeps the existing logic for now:
  automatically telling secondary coverage apart from an author's original analysis requires an
  explicit editorial signal and is left for a later iteration; original analysis is not blocked
  just because it was published by an expert source.
- Each YAML file in `config/profiles/` defines a profile with `slug`, `name`, `icon`,
  `description`, free signals, and `enabled`.
- Adding a source or topic requires no code changes; the configuration is validated on load.

To temporarily disable a profile without deleting its historical scores:

```yaml
slug: bank_risk
name: Bank Risk Intelligence
icon: "🏦"
enabled: false
```

To add a new interest, just create another YAML file:

```yaml
slug: my_profile
name: My Profile
icon: "🔎"
enabled: true
description: News relevant to this interest.
topics:
  relevant_topic: 1.0
```

All active profiles are automatically included in the same LLM call per event. A disabled profile
does not take part in the prompt, scoring, alerts, digest, or current views, but its historical
records remain in PostgreSQL.

## Tests and linting

Tests never call external services or paid APIs. RSS, the LLM, and Telegram use fixtures/fakes or
mocked HTTP transports.

```bash
pytest
ruff check .
ruff format --check .
```

Reproducible fixtures live in `tests/fixtures/`.

The `Tests`, `RSS smoke test`, and `AI Radar dry-run` workflows can be started manually with
`workflow_dispatch`. The dry-run takes credentials exclusively from GitHub Secrets.

## Idempotency and delivery

- A unique canonical URL prevents inserting the same article twice.
- Conservative title similarity groups different coverage of the same news into one event.
- Only new events reach the LLM.
- A database constraint allows a single immediate Telegram alert per event.
- An alert is persisted as `pending` before the request and then marked `sent` or `failed`; a
  failure never erases its state or triggers ambiguous automatic resends.

See the design proposal and follow-up plan in
[`docs/architecture-proposal.md`](docs/architecture-proposal.md) (Spanish).

## Production on a Linux server

The stable deployment uses Docker Compose for `postgres` and `radar`, and host systemd timers for
the radar, the digest, and source health checks. GitHub Actions does not schedule production runs.
See [`docs/production-deployment.md`](docs/production-deployment.md) for an Ubuntu install from
scratch, validation without Telegram, operations, backups, restore, and rollback.

## License

© 2026 [gabrieljaime](https://github.com/gabrieljaime). Released under the [MIT License](LICENSE).
You may use, copy, modify, and redistribute the code, including in commercial projects, as long as
you keep the copyright notice and the license.
