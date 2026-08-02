#!/usr/bin/env bash
#
# Vesper — one-command bootstrap (addendum §9, plan.md Phase 1/Phase 10).
#
#   git clone <repo> && cd vesper && ./start.sh
#
# Idempotent: safe to re-run at any time — detects what's already set up and
# skips it, so it doubles as the update/repair path. The only interactive input
# is secrets that can't be generated: LLM provider key, Telegram bot token +
# your Telegram user ID, and (skippable) the GitHub token/repo for the §7 vault
# backup. Everything else is generated automatically.
set -euo pipefail

cd "$(dirname "$0")"

BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${BLUE}[vesper]${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}[vesper]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[vesper]${NC} %s\n" "$1"; }

# ── 1. Preflight: Docker + Compose ──────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker not found. Install it, then re-run ./start.sh."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  warn "Docker Compose plugin not found."
  exit 1
fi

# ── 2. Secrets, collected once on first run only ───────────────────────
# Resolve the vault to an absolute host path for Docker bind mounts (the `~` in
# .env must not leak into compose). Host MCP servers and the worker must agree
# on the absolute path so DB vault_path rows stay consistent.
HERMES_VAULT_PATH_ABS="$(eval echo "${HERMES_VAULT_PATH:-~/Documents/KnowledgeVault}")"
HERMES_VAULT_PATH_ABS="$(cd "$HERMES_VAULT_PATH_ABS" 2>/dev/null && pwd || echo "$HERMES_VAULT_PATH_ABS")"
export HERMES_VAULT_PATH_ABS

if [[ ! -f .env ]]; then
  info "First run — setting up .env."
  cp .env.example .env

  read -r -p "LLM provider API key (OpenCode Go): " OPENCODE_GO_API_KEY
  sed -i.bak "s|^OPENCODE_GO_API_KEY=.*|OPENCODE_GO_API_KEY=$OPENCODE_GO_API_KEY|" .env

  read -r -p "Telegram bot token: " TELEGRAM_BOT_TOKEN
  sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN|" .env

  read -r -p "Your Telegram user ID (allowlist): " TELEGRAM_ALLOWED_USERS
  sed -i.bak "s|^TELEGRAM_ALLOWED_USERS=.*|TELEGRAM_ALLOWED_USERS=$TELEGRAM_ALLOWED_USERS|" .env

  # Vault backup (addendum §7) is optional — skippable.
  read -r -p "GitHub PAT for vault backup? (enter to skip, set up later): " GH_PAT
  if [[ -n "$GH_PAT" ]]; then
    read -r -p "Vault repo URL (e.g. git@github.com:you/vault.git): " VAULT_REPO_URL
    sed -i.bak "s|^GH_PAT=.*|GH_PAT=$GH_PAT|" .env
    sed -i.bak "s|^VAULT_REPO_URL=.*|VAULT_REPO_URL=$VAULT_REPO_URL|" .env
    ok "Vault backup enabled."
  else
    warn "Vault backup skipped — enable later by filling GH_PAT/VAULT_REPO_URL in .env."
  fi

  # Generated automatically, never asked for.
  sed -i.bak "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
  sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env
  rm -f .env.bak
  ok ".env written."
else
  ok ".env already present — skipping secret collection."
fi

# ── 3. Frontend build (Caddy serves ./frontend/out) ──────────────────────
if [[ ! -d frontend/out ]]; then
  info "Building the web frontend (Next.js static export)…"
  if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm ci >/dev/null 2>&1 || npm install) && npm run build
  else
    warn "npm not found — skipping frontend build. Caddy will serve an empty site until frontend/out exists."
  fi
else
  ok "Frontend already built (frontend/out present)."
fi

# ── 4. Data layer: postgres + redis + caddy ─────────────────────────────
info "Starting data layer (postgres, redis, caddy)…"
docker compose up -d postgres redis caddy
docker compose exec -T postgres pg_isready -U "$(sed -n 's/^POSTGRES_USER=//p' .env | head -1 || echo vesper)" >/dev/null 2>&1 || \
  for i in $(seq 1 30); do
    docker compose exec -T postgres pg_isready -U vesper >/dev/null 2>&1 && break
    sleep 2
  done

info "Running DB migrations…"
docker compose run --rm -T vesper-api sh -c "alembic -c backend/db/postgres/alembic.ini upgrade head"
ok "Migrations applied."

info "Initialising the DuckDB feature store (empty-but-ready schema)…"
docker compose run --rm -T vesper-api python -c "from backend.db.feature_store import ensure_schema; ensure_schema(); print('feature store ready')"
ok "Feature store ready."

# ── 5. Module layer: api + worker ───────────────────────────────────────
info "Starting vesper-api and vesper-worker…"
docker compose up -d --build vesper-api vesper-worker

# ── 6. Hermes Agent: install + configure ────────────────────────────────
if [[ ! -d "$HOME/.hermes/hermes-agent" ]]; then
  info "Installing Hermes Agent (Phase 3)…"
  warn "Run the official Hermes Agent installer now, then re-run ./start.sh to finish config."
  exit 0
else
  ok "Hermes Agent already installed at ~/.hermes/hermes-agent."
fi

# Sync Vesper MCP servers into Hermes' config.yaml (host venv paths, resolved
# from this checkout). Idempotent; preserves non-Vesper servers.
if command -v "$PWD/.venv/bin/python" >/dev/null 2>&1; then
  info "Syncing Vesper MCP servers into ~/.hermes/config.yaml…"
  "$PWD/.venv/bin/python" "$PWD/hermes-config/sync_mcp.py" "$HOME/.hermes/config.yaml"
  ok "MCP servers synced."
else
  warn "Vesper venv missing — create it with: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
fi

# Skills + cron config are consumed directly from this checkout via Hermes'
# `skills.external_dirs` (points at vesper/hermes-config/skills + /cron).
ok "Skills/cron config served from vesper/hermes-config."

# ── 7. Health check + handoff ───────────────────────────────────────────
ok "Vesper stack is up. Checking health…"
docker compose ps --format "table {{.Service}}\t{{.Status}}"
printf "\n"
printf "${GREEN}Setup complete.${NC}\n"
printf "  API health:  %s\n"  "http://localhost:8000/health"
printf "  Web app:     %s\n"  "http://localhost/ (Caddy → frontend/out)"
printf "  Next step:   message your bot on Telegram to get started.\n"
