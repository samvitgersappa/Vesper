# Vesper — Deployment Guide

Production walkthrough for deploying the Vesper Personal Intelligence OS on a
single server (or a laptop acting as a home server). Everything runs on one
host: Hermes Agent, the Vesper API, the worker scheduler, and the data stores.

> **Audience**: you are comfortable with a terminal, Docker, and systemd
> (or a cron daemon). You do not need to read `plan.md` to deploy — this guide
> is self-contained.

---

## Table of contents

1. [Architecture recap](#1-architecture-recap)
2. [Prerequisites](#2-prerequisites)
3. [Prepare the machine](#3-prepare-the-machine)
4. [Clone + bootstrap with `start.sh`](#4-clone--bootstrap-with-startsh)
5. [Configure Hermes Agent](#5-configure-hermes-agent)
6. [Model providers & fallback](#6-model-providers--fallback)
7. [Nightly Obsidian vault backup](#7-nightly-obsidian-vault-backup)
8. [Run as a service](#8-run-as-a-service)
9. [Backups & restore](#9-backups--restore)
10. [Monitoring & logging](#10-monitoring--logging)
11. [Security hardening](#11-security-hardening)
12. [Upgrades & day-two operations](#12-upgrades--day-two-operations)
13. [Troubleshooting runbook](#13-troubleshooting-runbook)
14. [Operational reference](#14-operational-reference)

---

## 1. Architecture recap

```
        User (Telegram / web dashboard)
                 │
        ┌────────┴─────────┐
   Hermes Agent       Caddy (:80) ──▶ frontend/out (static export)
   (Telegram gateway)          │
        │                      └──▶ vesper-api (:8000, FastAPI, host process)
        │  MCP (stdin/stdout)          │
        └──▶ 8 module MCP servers ◀────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   Postgres (:5432)   Redis (:6379)    DuckDB + LanceDB (files)
   (system of record) (event bus)      (feature store / semantic index)
                          │
                    vesper-worker (host APScheduler: finance, vault push,
                                   knowledge, graph, notifications…)
```

- **Hermes Agent** runs as its own process (its own installer), on the host,
  and talks to the module MCP servers over local stdio. It does **not** run
  inside compose.
- **vesper-api** and **vesper-worker** run as **host processes** (`.venv/bin/python -m backend.main`),
  launched and supervised by `start.sh` — fewer moving parts on an 8GB VM than
  building two Docker images.
- **Caddy** runs on the host, serves the static frontend on :80, and proxies
  `/api` + `/health` to the API.
- **postgres** and **redis** run as Docker containers; the **quartz** garden
  also runs in Docker.

---

## 2. Prerequisites

> `start.sh` installs all of these automatically on Ubuntu/macOS (apt/brew,
> Docker Engine, Compose plugin, Caddy, Hermes Agent). The sections below are
> the manual equivalent for reference / unusual setups.

- **OS**: Ubuntu 22.04+/24.04 (recommended), Debian 12, macOS 13+, or any
  Linux with Docker.
- **Docker Engine 24+** and the **Docker Compose v2 plugin**.
- **Node.js 18+** (frontend build; can be installed temporarily).
- **Python 3.12+** (local venv for the Hermes MCP servers).
- **Git**.
- **Caddy** (web server / reverse proxy; apt on Ubuntu, brew on macOS).
- **Hermes Agent** installed per its own installer (needed for the cognitive
  engine and Telegram gateway). If you skip it, the data layer, API, worker,
  and web dashboard still run — you just lose the agent front-end.

### 2.1 Install Docker (Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# log out/in for the group change, or: newgrp docker
```

### 2.2 Install Node + Python (Ubuntu)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs python3 python3-venv
```

### 2.3 Install Hermes Agent

Follow Hermes Agent's official installer (see `plan.md` §0 / Phase 3). It
installs to `~/.hermes/hermes-agent/` with its own venv. It must be the
**same user** that will run `start.sh`.

---

## 3. Prepare the machine

### 3.1 Create a service user (recommended)

```bash
sudo adduser --system --group --home /opt/vesper vesper
sudo usermod -aG docker vesper
sudo mkdir -p /opt/vesper
sudo chown vesper:vesper /opt/vesper
```

Subsequent commands run as the `vesper` user:

```bash
sudo -u vesper -i   # or: sudo su -s /bin/bash vesper
```

### 3.2 Generate the secrets up front (optional but tidy)

`start.sh` generates `POSTGRES_PASSWORD` and `JWT_SECRET` automatically, but if
you want to control them:

```bash
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 32   # JWT_SECRET
```

---

## 4. Clone + bootstrap with `start.sh`

```bash
cd /opt/vesper
git clone <your-vesper-repo-url> vesper
cd vesper
./start.sh
```

`start.sh` is **idempotent** and safe to re-run (it doubles as the update/repair
path). It will:

1. Install the toolchain (apt on Ubuntu: git, python3-venv, node/npm, openssl,
   Docker + Compose, Caddy; Homebrew on macOS).
2. Install Hermes Agent via its official installer (if missing).
3. Build the frontend static export into `frontend/out/`.
4. On first run, copy `.env.example` → `.env` and prompt for:
   - OpenCode Go API key
   - Telegram bot token + your numeric Telegram user ID
   It then generates `POSTGRES_PASSWORD` / `JWT_SECRET`.
5. Create the second-brain vault folder structure fresh
   (`~/Documents/KnowledgeVault`: `00 Journal/YYYY`, `03 Knowledge`,
   `99 Assets/images`, `01 Inbox`, `02 Projects`, `index.md`) and git-init it.
6. Start `postgres` + `redis` (Docker); on first run wipe the DB to empty,
   then `alembic upgrade head` → creates **56 tables across 7 schemas**, all
   empty.
7. Initialise the DuckDB feature store (5 tables, empty) and seed the **6
   paper-trader accounts** (5 classic @ ₹5L + catalyst_swing @ ₹10L).
8. Provision Hermes Agent: write `~/.hermes/.env`, merge `~/.hermes/config.yaml`
   (provider + approvals + skills/cron external dirs), sync the 8 Vesper MCP
   servers, install the capture-router plugin, register the 6 reasoning cron
   jobs.
9. Start the API (:8000) + worker as host processes.
10. Start the Quartz garden (Docker) + Caddy on :80 (static frontend + `/api`
    proxy + `/brain`) — open to the internet so your phone can reach it.
11. Start the Hermes Telegram gateway.
12. Print stack status and handoff URLs.

### What you should see

```text
[vesper] Step 13 — health checks.
[vesper]   API /health → {"status":"ok","app_mode":"api"}
  finance strategies → 6 | alpha_tilt,arjun_etf,lowdd_multi_asset,momentum_surge,alpha_generators,catalyst_swing
[vesper]   web app up on :80
Setup complete.
  API health:   http://localhost:8000/health
  Web app:      http://localhost:80/   (internet: http://<server-ip>/)
  Brain garden: http://localhost:8081/
  Telegram:     message your bot to talk to Hermes Agent.
```

### Verify end-to-end

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/relationship/stats | head -c 200
curl -s http://localhost:8000/api/finance/portfolio | head -c 200
docker compose exec -T postgres pg_isready -U vesper
```

If `start.sh` was interrupted before Hermes was installed, re-run it after the
installer — it resumes cleanly.

---

## 5. Configure Hermes Agent

Hermes Agent is configured via `~/.hermes/config.yaml`. Vesper ships a sync
script that points it at the eight module MCP servers using **host paths**
(the venv at `<repo>/.venv/bin/python` and the module servers under
`<repo>/backend/modules/`).

### 5.1 Sync MCP servers

`start.sh` runs `hermes-config/install_hermes.py` which does all of this. To do
it manually:

```bash
cd /opt/vesper/vesper
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python hermes-config/sync_mcp.py ~/.hermes/config.yaml
# → "synced 8 Vesper MCP servers into ~/.hermes/config.yaml"
```

The script is idempotent and preserves any MCP servers you already had.

### 5.2 Skills + cron

`install_hermes.py` merges `hermes-config/hermes.config.template.yaml` into
`~/.hermes/config.yaml`, which points `skills.external_dirs` at:

```
/opt/vesper/vesper/hermes-config/skills
/opt/vesper/vesper/hermes-config/cron
```

It also registers the reasoning cron jobs with `hermes cron create`:

| Job | Schedule (IST) | Skill |
|---|---|---|
| Morning Brief | 07:30 Mon–Fri | `morning-brief` |
| Daily Journal Questionnaire | 21:30 daily | `daily-journal-questionnaire` |
| Evening Review | 21:45 Mon–Fri | `evening-review` |
| Weekly Review | 10:00 Sun | `weekly-review` |
| Monthly Review | 10:00 1st | `monthly-review` |
| Knowledge Architect | 02:30 daily | `knowledge-architect` |

Verify with `hermes cron list`.

### 5.3 Telegram gateway

The Telegram gateway is **enabled automatically** when `TELEGRAM_BOT_TOKEN` is
present in `~/.hermes/.env` (which `install_hermes.py` mirrors from the project
`.env`). `TELEGRAM_ALLOWED_USERS` is the allowlist — the bot only replies to
your numeric Telegram user ID. `start.sh` starts the gateway with
`hermes gateway run`. Notifications from Vesper itself are sent by the worker
directly via the Bot API (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS`).

### 5.4 Capture-router plugin

`install_hermes.py` installs `hermes-config/plugins/vesper-capture-router` into
`~/.hermes/plugins/` and enables it. This is the deterministic backstop that
guarantees any "remember X / save this / I spent ₹Y" utterance reaches
`knowledge.capture` even if the model never loads the capture skill (addendum §1).

### 5.5 Memory plugin

Apply `hermes-config/memory/tencentdb-agent-memory.yaml` per the TencentDB
Agent Memory plugin's documented Hermes Agent install path (L0–L3 memory).

---

## 6. Model providers & fallback

Vesper's default provider chain (plan §14) is configured in
`hermes-config/provider.yaml` and `hermes-config/model_escalation.py`:

| Priority | Model | Provider | Notes |
|---|---|---|---|
| 1 | `hy3` | opencode-go | default |
| 2 | `gpt-5.6-luna` | opencode-go | long-context + finance/study `analyze` |
| 3 | `llama3.2` | local Ollama | free fallback (profile `fallback`) |
| 4 | `llama-3.1-8b-instant` | Groq | last resort (needs `GROQ_API_KEY`) |

- Set `OPENCODE_GO_API_KEY` in `.env` for the primary path.
- Ollama is **off by default** (profile-gated) to keep steady-state RAM low.
  Start it on demand during an outage:
  ```bash
  docker compose --profile fallback up -d ollama
  ```
- Apply the provider config to Hermes after install:
  ```bash
  hermes model   # pick opencode-go / hy3
  ```

---

## 7. Nightly Obsidian vault backup

Vesper pushes your Obsidian vault to a **private GitHub repo** every night at
**00:15** (`vault_backup_publish` in the worker). This gives you "second brain
on any device" via GitHub's own app — free, private.

### 7.1 Configure (in `.env`)

```bash
GH_PAT=<github-pat-with-repo-write-scope>
VAULT_REPO_URL=https://github.com/you/vault-backup.git
# or, if you prefer a full remote URL (takes precedence):
VAULT_GIT_REMOTE=https://x-access-token:${GH_PAT}@github.com/you/vault-backup.git
```

- `HERMES_VAULT_PATH` must point at the vault (default
  `~/Documents/KnowledgeVault`).
- The vault must already be a git repo, or `start.sh`/the job will no-op.
  Initialise it once:
  ```bash
  cd ~/Documents/KnowledgeVault
  git init -b main
  git add -A && git commit -m "initial vault"
  git remote add origin <VAULT_REPO_URL with token>
  ```

### 7.2 Verify the job

```bash
# Run the job manually (host venv):
cd /opt/vesper/vesper
PYTHONPATH=. .venv/bin/python -c \
  "from backend.automation.jobs.vault_publish import vault_backup_publish; print(vault_backup_publish())"
# Expect: {'ok': True, 'git_pushed': True, 'quartz_rebuilt': False}
```

Without creds/repo the job is a successful no-op (`git_pushed: False`) — by
design; it never fails the worker.

### 7.3 Quartz digital garden (optional)

Set `QUARTZ_DIR` (a Quartz project) and `QUARTZ_OUTPUT` (a Caddy-served dir) in
`.env` and the same 00:15 job rebuilds the site. Requires `npx` on the worker
host.

---

## 8. Run as a service

### 8.1 Docker containers always-on

Compose sets `restart: unless-stopped` for postgres, redis, caddy (if used).
The **API and worker run as host processes** launched by `start.sh`
(`.venv/bin/python -m backend.main` with `APP_MODE=api` / `APP_MODE=worker`).
For a long-running VM, supervise them so they survive reboots and crashes:

### 8.2 systemd unit for the worker + API (Linux)

`/etc/systemd/system/vesper-api.service`:

```ini
[Unit]
Description=Vesper API
After=docker.service network-online.target
Wants=network-online.target

[Service]
User=vesper
WorkingDirectory=/opt/vesper/vesper
Environment=APP_MODE=api
Environment=PORT=8000
EnvironmentFile=/opt/vesper/vesper/.env
ExecStart=/opt/vesper/vesper/.venv/bin/python -m backend.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/vesper-worker.service`:

```ini
[Unit]
Description=Vesper worker (APScheduler + event subscribers)
After=vesper-api.service network-online.target
Wants=network-online.target

[Service]
User=vesper
WorkingDirectory=/opt/vesper/vesper
Environment=APP_MODE=worker
Environment=PORT=9000
Environment=VESPER_NULL_POOL=1
EnvironmentFile=/opt/vesper/vesper/.env
ExecStart=/opt/vesper/vesper/.venv/bin/python -m backend.main
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vesper-api vesper-worker
```

### 8.3 systemd unit for Hermes Agent

Wrap Hermes Agent's daemon (gateway/agent loop) in its own unit so it survives
reboots and crashes:

```ini
[Unit]
Description=Hermes Agent gateway
After=network-online.target
Wants=network-online.target

[Service]
User=vesper
WorkingDirectory=/opt/vesper/vesper
EnvironmentFile=/opt/vesper/vesper/.env
ExecStart=/home/vesper/.hermes/hermes-agent/venv/bin/hermes gateway run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> Use the real Hermes entrypoint from your install (e.g. `hermes gateway` /
> `hermes agent`); check `~/.hermes/hermes-agent` docs.

### 8.4 All services on boot

```bash
sudo systemctl enable --now vesper-api
sudo systemctl enable --now vesper-worker
sudo systemctl enable --now hermes
# Docker containers are already restart:unless-stopped
```

---

## 9. Backups & restore

### 9.1 What to back up

| Data | Where | Back up? |
|---|---|---|
| Postgres | named volume `postgres_data` | **yes — nightly** |
| Obsidian vault | `~/Documents/KnowledgeVault` | yes (already pushed to GitHub at 00:15) |
| DuckDB feature store | named volume `data_backend` (`/app/backend/data`) | yes (recreatable by finance jobs) |
| LanceDB index | named volume `data_lancedb` | optional (rebuilt nightly) |
| `.env` | `<repo>/.env` | **yes — contains secrets, not in git** |
| Hermes state | `~/.hermes/state.db` | yes (recreatable by hermes_mirror) |

### 9.2 Postgres dump

```bash
# Daily at 03:30 via systemd timer or cron:
docker compose exec -T postgres pg_dump -U vesper -d vesper \
  | gzip > /var/backups/vesper/postgres-$(date +%F).sql.gz

# Prune dumps older than 14 days:
find /var/backups/vesper -name 'postgres-*.sql.gz' -mtime +14 -delete
```

systemd timer example:

```ini
# /etc/systemd/system/vesper-pgdump.service
[Service]
User=root
Type=oneshot
ExecStart=/bin/sh -c 'docker compose -f /opt/vesper/vesper/docker-compose.yml exec -T postgres pg_dump -U vesper -d vesper | gzip > /var/backups/vesper/postgres-$(date +%%F).sql.gz'
```

```ini
# /etc/systemd/system/vesper-pgdump.timer
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now vesper-pgdump.timer
```

### 9.3 Restore

```bash
# Restore a full dump (stops nothing; runs against a fresh DB name):
docker compose exec -T postgres psql -U vesper -d postgres \
  -c "CREATE DATABASE vesper_restore OWNER vesper;"
gunzip -c /var/backups/vesper/postgres-2026-08-02.sql.gz \
  | docker compose exec -T postgres psql -U vesper -d vesper_restore

# Point .env at it, or rename:
docker compose exec -T postgres psql -U vesper -d postgres \
  -c "ALTER DATABASE vesper_restore RENAME TO vesper;"   # only if down
```

---

## 10. Monitoring & logging

### 10.1 Health

- `curl http://localhost:8000/health` → `{"status":"ok","app_mode":"api"}`.
- `docker compose ps` shows container states.
- Finance job health: `SELECT job_name, status, rows_processed, finished_at FROM finance.job_runs ORDER BY id DESC LIMIT 10;`

### 10.2 Logs

```bash
docker compose logs -f postgres       # Postgres
docker compose logs -f redis          # Redis
tail -f /tmp/vesper-api.log           # API (host process)
tail -f /tmp/vesper-worker.log        # worker: scheduler jobs + events
tail -f /tmp/vesper-caddy.log         # Caddy web proxy
tail -f /tmp/vesper-gateway.log       # Hermes gateway
journalctl -u vesper-api -f           # systemd API (if supervised)
journalctl -u vesper-worker -f        # systemd worker (if supervised)
journalctl -u hermes -f               # Hermes Agent (if supervised)
tail -f ~/.hermes/logs/agent.log      # Hermes agent log (its own path)
```

### 10.3 Job run table

Every APScheduler job run is not logged to `finance.job_runs` **except finance**
jobs (which are). A quick way to watch the worker's jobs:

```bash
docker compose exec -T postgres psql -U vesper -d vesper \
  -c "SELECT job_name, status, rows_processed, finished_at FROM finance.job_runs ORDER BY id DESC LIMIT 10;"
```

### 10.4 Alerts

Add a cron that hits `/health` and calls the Telegram bot if it fails:

```bash
#!/bin/sh
if ! curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_ALLOWED_USERS}" -d text="Vesper API down"
fi
```

---

## 11. Security hardening

1. **Postgres is bound to 127.0.0.1 only** (`127.0.0.1:5432:5432`) — keep it
   that way.
2. **Redis is bound to 127.0.0.1 only** — same. It carries the event bus, no
   auth by default, so do not expose it.
3. **`.env` is git-ignored** — never commit it. Rotate the key/token if it
   leaks.
4. Caddy serves :80 (and can do TLS on :443 with a domain via `VESPER_DOMAIN`).
   Put it (or nginx) in front of the API + dashboard and terminate TLS if
   serving over the public internet.
5. Telegram bot token lives in `.env`; `install_hermes.py`/`start.sh` never print it.
6. The vault backup uses a **fine-grained PAT scoped to that one repo**.
7. Ollama (if used) binds 127.0.0.1:11434 — do not expose.
8. Keep Docker, Node, Python, and Hermes Agent updated.

---

## 12. Upgrades & day-two operations

### 12.1 Update code

```bash
cd /opt/vesper/vesper
git pull
./start.sh          # idempotent: rebuilds images, re-runs migrations, re-syncs MCP
```

### 12.2 Migrations

`start.sh` runs `alembic upgrade head`. Manual (host venv):

```bash
cd /opt/vesper/vesper
.venv/bin/python -m alembic -c backend/db/postgres/alembic.ini upgrade head
```

### 12.3 Rebuild frontend only

```bash
cd frontend && NEXT_PUBLIC_API_BASE= npm run build && cd ..
caddy reload --config /opt/vesper/vesper/.run/Caddyfile   # or restart caddy
```

### 12.4 Re-seed the finance feature store

```bash
# Delete the DuckDB state (backend/data/metadata/quiver.duckdb) and let the
# 06:00 job rebuild it, or run the jobs manually:
cd /opt/vesper/vesper
.venv/bin/python -c \
  "import asyncio; from backend.automation.jobs.finance import update_universe; \
   asyncio.run(update_universe())"
```

### 12.5 Change the schedule

Edit `JOB_SCHEDULE` in `backend/automation/scheduler.py` and restart the worker.
Times are in the server's local timezone (IST on the reference deployment).

---

## 13. Troubleshooting runbook

### `alembic upgrade head` hangs or fails

- Postgres not healthy yet → `docker compose ps postgres`; wait for healthy.
- Wrong `.env` URL → confirm `DATABASE_URL` uses the `postgres` host (Docker)
  or `localhost` (host runner).

### API returns 404 on `/api/...`

- A stale process may hold port 8000 (`lsof -i :8000`). Kill it and restart
  `vesper-api`.

### Events not arriving (empty graph / no notifications)

- Redis unreachable from the **host** (Hermes MCP servers use
  `redis://localhost:6379/0`; the Docker services use `redis://redis:6379/0`).
- Confirm the port: `docker compose ps redis` shows `127.0.0.1:6379->6379`.
- Test: `redis-cli -h 127.0.0.1 ping` → `PONG`.

### Finance jobs report `degraded`

- yfinance unreachable (network block / no internet) → the job records a
  `degraded` run and moves on. It never fabricates data.
- Feature store empty → run `update_universe` then `fetch_equity`.

### Vault push job is a no-op

- `HERMES_VAULT_PATH` unset, vault not a git repo, or no `GH_PAT`/repo URL.
  See §7.

### `journal.complete_day` can't find today's entry

- Vault path convention: `00 Journal/YYYY/YYYY-MM-DD.md`. Old entries under
  `journal/YYYY/MM/` are still read (legacy fallback). Verify the row's
  `vault_path` points at a file that exists.

### Worker dies on boot

- Check `tail -f /tmp/vesper-worker.log`. Common cause: Redis down when the
  subscribers start — they retry; the scheduler still runs.

### Frontend blank at `http://<server-ip>/`

- `frontend/out/` missing → `cd frontend && NEXT_PUBLIC_API_BASE= npm run build`.
- Caddy serving old copy → `caddy stop && caddy start` (or re-run `./start.sh`).

### Ports already in use

- `postgres`, `redis`, `caddy`, the API bind host ports 5432/6379/80/8000.
  Change in `docker-compose.yml` / the generated Caddyfile if a conflict exists.

---

## 14. Operational reference

### Ports

| Port | Service | Binds | Purpose |
|---|---|---|---|
| 5432 | postgres | 127.0.0.1 | relational store |
| 6379 | redis | 127.0.0.1 | event bus |
| 80 | caddy (host) | all | web app + /api proxy + /brain (internet-facing) |
| 8000 | vesper-api (host) | 0.0.0.0 | REST API |
| 8081 | quartz garden | 127.0.0.1 | second-brain static site + /rebuild trigger |
| 11434 | ollama (optional) | 127.0.0.1 | local fallback model |

### Host processes (supervised by start.sh / systemd)

| Process | Role | Log |
|---|---|---|
| `backend.main` (APP_MODE=api) | REST + health on :8000 | `/tmp/vesper-api.log` |
| `backend.main` (APP_MODE=worker) | scheduler + event subscribers | `/tmp/vesper-worker.log` |
| `hermes gateway run` | Telegram gateway + agent loop | `/tmp/vesper-gateway.log` |
| `caddy run` | :80 web + /api proxy + /brain | `/tmp/vesper-caddy.log` |

### Docker containers

| Service | Restart | Role |
|---|---|---|
| postgres | unless-stopped | data |
| redis | unless-stopped | bus |
| vesper-quartz | unless-stopped | garden (static site + rebuild trigger) |
| ollama | profile `fallback` | on-demand local model |

### Environment cheat-sheet

- Host MCP servers → Postgres via `db.py` default `localhost`, Redis via
  `bus.py` default `localhost`.
- Docker services → `DATABASE_URL`/`REDIS_URL` from `.env` (in-network
  `postgres`/`redis` hosts).
- `HERMES_VAULT_PATH` is resolved to an absolute path (`HERMES_VAULT_PATH_ABS`)
  by `start.sh` and bind-mounted so DB `vault_path` rows stay consistent
  between host MCP servers and the worker.

### Reference URLs

- API health: `http://localhost:8000/health`
- Web dashboard: `http://localhost/`
- Telegram: message your bot to talk to Hermes Agent.
