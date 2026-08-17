#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
backup_dir="${BACKUP_DIR:-./backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$backup_dir"
umask 077
docker compose exec -T postgres pg_dump -U ai_radar -d ai_radar -Fc \
  >"$backup_dir/ai_radar_$timestamp.dump"
find "$backup_dir" -maxdepth 1 -type f -name 'ai_radar_*.dump' \
  -mtime "+$retention_days" -delete
echo "Backup created: $backup_dir/ai_radar_$timestamp.dump"
