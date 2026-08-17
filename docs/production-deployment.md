# AI Radar production deployment

## Server architecture

One Ubuntu host runs Docker Engine and host-level systemd timers. Docker Compose runs two
services on a private Compose network:

- `postgres`: PostgreSQL 16 with the named volume `ai_radar_postgres`; it has no published port.
- `radar`: the FastAPI health/debug process and the image used by one-shot scheduled jobs. Port
  8000 is bound only to `127.0.0.1` on the host.

The host timers invoke `docker compose run --rm radar ...`. systemd does not start another copy of
an already-active unit, `flock` provides an additional host guard, and the existing PostgreSQL
advisory lock remains the final concurrency guard for Radar runs.

## Manual server setup (Ubuntu from zero)

Run these commands as a sudo-capable administrator. Replace the repository URL and deployment
user where indicated.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Verify the real server clock before installing timers. The unit files carry an explicit Argentina
timezone, so changing the host timezone is not required:

```bash
timedatectl
timedatectl list-timezones | grep '^America/Argentina/Buenos_Aires$'
systemd-analyze calendar '*-*-* 08:00:00 America/Argentina/Buenos_Aires'
systemd-analyze calendar '*-*-* 07:30:00 America/Argentina/Buenos_Aires'
systemd-analyze calendar '*-*-* 00/2:00:00 America/Argentina/Buenos_Aires'
```

Create a dedicated host account and install the repository:

```bash
sudo adduser --system --group --home /opt/ai-radar ai-radar
sudo usermod -aG docker ai-radar
sudo -u ai-radar git clone REPLACE_WITH_REPOSITORY_URL /opt/ai-radar
cd /opt/ai-radar
sudo -u ai-radar cp .env.example .env
postgres_password="$(openssl rand -hex 32)"
sudo -u ai-radar sed -i \
  "s/replace-with-a-long-random-password/$postgres_password/g" .env
sudo -u ai-radar chmod 600 .env
sudo -u ai-radar nano .env
```

In `.env`, set at least `LLM_API_KEY`, the provider/model values, `TELEGRAM_BOT_TOKEN`, and
`TELEGRAM_CHAT_ID`. Keep the generated hex database password in both existing password positions.
Never commit `.env`.

Run the first deployment as the deployment account:

```bash
cd /opt/ai-radar
sudo -u ai-radar chmod +x scripts/deploy.sh scripts/backup_postgres.sh
sudo -u ai-radar ./scripts/deploy.sh
```

Install timers only after that succeeds:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-radar.timer ai-radar-digest.timer ai-radar-health.timer
systemctl list-timers 'ai-radar*'
```

The units must be able to access Docker. They run as root by default, while application processes
inside the container run as the unprivileged `radar` user. The repository and `.env` remain owned
by the dedicated host account.

## Initial validation without Telegram delivery

The deploy script runs the test/lint image, builds production, starts PostgreSQL without recreating
its volume, applies Alembic migrations, starts FastAPI, and verifies both probes. Then run:

```bash
cd /opt/ai-radar
docker compose ps
docker compose exec -T radar python -m alembic current
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
docker compose run --rm radar python scripts/run_radar.py --dry-run
docker compose run --rm radar python scripts/send_digest.py --dry-run
docker compose run --rm radar python scripts/check_sources.py
```

`run_radar.py --dry-run` can still call the configured LLM, but uses the dry-run alert channel and
does not deliver Telegram. The digest dry-run neither sends nor reserves a digest.

After inspecting those results, manually exercise each job if desired. The Radar and digest service
commands below are real runs and can send Telegram:

```bash
sudo systemctl start ai-radar-health.service
sudo systemctl start ai-radar.service
sudo systemctl start ai-radar-digest.service
```

## Timers and logs

- Radar: every two hours, with up to five minutes randomized delay.
- Source health: 07:30 `America/Argentina/Buenos_Aires`.
- Digest: 08:00 `America/Argentina/Buenos_Aires`.
- `Persistent=true` catches up one missed invocation after downtime.

Inspect operations with:

```bash
systemctl status ai-radar.service ai-radar.timer
systemctl status ai-radar-digest.service ai-radar-digest.timer
systemctl status ai-radar-health.service ai-radar-health.timer
journalctl -u ai-radar.service -n 200 --no-pager
journalctl -u ai-radar-digest.service -n 200 --no-pager
journalctl -u ai-radar-health.service -n 200 --no-pager
journalctl -u ai-radar.service -f
```

## Deploy command

```bash
cd /opt/ai-radar
sudo -u ai-radar ./scripts/deploy.sh
```

Use `SKIP_TESTS=1 ./scripts/deploy.sh` only when the exact commit has already passed CI. The script
uses `git pull --ff-only`, never runs `docker compose down`, and never removes volumes.

## PostgreSQL backup and restore

Create a local custom-format dump (default retention: 14 days):

```bash
cd /opt/ai-radar
sudo -u ai-radar BACKUP_DIR=/var/backups/ai-radar ./scripts/backup_postgres.sh
```

Create and secure the directory first:

```bash
sudo install -d -o ai-radar -g ai-radar -m 0700 /var/backups/ai-radar
```

To restore, stop scheduled writes, take a final backup, and restore a selected dump. This replaces
database contents, so confirm the filename first:

```bash
sudo systemctl stop ai-radar.timer ai-radar-digest.timer
cd /opt/ai-radar
sudo -u ai-radar ./scripts/backup_postgres.sh
ls -lh /var/backups/ai-radar
docker compose exec -T postgres dropdb -U ai_radar --if-exists ai_radar
docker compose exec -T postgres createdb -U ai_radar -O ai_radar ai_radar
docker compose exec -T postgres pg_restore -U ai_radar -d ai_radar --no-owner --no-acl \
  < /var/backups/ai-radar/REPLACE_WITH_BACKUP.dump
docker compose exec -T radar python -m alembic current
sudo systemctl start ai-radar.timer ai-radar-digest.timer
```

## Rollback procedure

Application rollback does not roll back the database automatically:

```bash
cd /opt/ai-radar
sudo systemctl stop ai-radar.timer ai-radar-digest.timer ai-radar-health.timer
sudo -u ai-radar ./scripts/backup_postgres.sh
git log --oneline -10
sudo -u ai-radar git switch --detach REPLACE_WITH_PREVIOUS_COMMIT
sudo -u ai-radar docker compose build radar
sudo -u ai-radar docker compose up -d postgres
sudo -u ai-radar docker compose up -d radar
curl --fail http://127.0.0.1:8000/ready
sudo systemctl start ai-radar.timer ai-radar-digest.timer ai-radar-health.timer
```

Do not run an Alembic downgrade unless the selected release explicitly documents a safe downgrade.
If a migration must be reverted, restore the pre-deploy dump using the restore procedure. To return
to normal Git tracking after recovery:

```bash
sudo -u ai-radar git switch main
```

## Security and database configuration

- PostgreSQL has a dedicated `ai_radar` database/user and no host port mapping.
- The only published application socket is `127.0.0.1:8000`; remote access requires an explicitly
  configured SSH tunnel or reverse proxy.
- Secrets live only in mode-0600 `.env`, excluded by `.gitignore`.
- The production image runs Python as the non-root `radar` container user.
- PostgreSQL data lives in the named volume `ai_radar_postgres`; deploy and rollback commands do not
  destroy or unnecessarily recreate it.
- GitHub Actions remains CI/manual smoke infrastructure. No GitHub scheduled workflow is added.
