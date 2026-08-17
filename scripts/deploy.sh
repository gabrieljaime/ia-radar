#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example, set secrets, and chmod 600 .env." >&2
  exit 1
fi

git pull --ff-only

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  docker build --target test -t ai-radar:test .
  docker run --rm ai-radar:test pytest -q
  docker run --rm ai-radar:test ruff check .
  docker run --rm ai-radar:test ruff format --check .
fi

docker compose build radar
docker compose up -d postgres
docker compose run --rm radar python -m alembic upgrade head
docker compose up -d --wait radar
docker compose ps
docker compose exec -T radar python -m alembic current
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/ready

echo
echo "Deployment complete. Initial dry-run commands are documented in docs/production-deployment.md."
