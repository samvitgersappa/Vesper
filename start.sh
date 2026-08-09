#!/usr/bin/env bash
#
# Vesper — one-command bootstrap (plan.md Phase 1 / Phase 10, addendum §9).
#
#   git clone <repo> && cd vesper && ./start.sh
#
# This is the SINGLE file you run on a fresh machine (primary target: an
# Ubuntu 22.04/24.04 VM; also works on macOS for development). It does
# literally everything:
#
#   1. Install the toolchain (apt on Ubuntu, Homebrew on macOS): git, python3,
#      python3-venv, node/npm, openssl, curl, Docker + Compose, Caddy.
#   2. Install Hermes Agent via its official installer (--skip-setup).
#   3. Create the Python venv + install backend/requirements.txt.
#   4. npm install + build the Next.js frontend (static export → frontend/out).
#   5. Collect secrets on first run ONLY (OpenCode Go API key, Telegram bot
#      token, Telegram user ID) and generate POSTGRES_PASSWORD / JWT_SECRET.
#   6. Create the full second-brain vault folder structure from scratch
#      (~/Documents/KnowledgeVault: 00 Journal/YYYY, 03 Knowledge,
#      99 Assets/images) and git-init it.
#   7. Bring up Postgres + Redis (Docker) and wait for health.
#   8. Apply Alembic migrations + initialise the empty DuckDB feature store.
#   9. Provision Hermes Agent (hermes-config/install_hermes.py): write
#      ~/.hermes/.env, merge ~/.hermes/config.yaml, sync the 8 module MCP
#      servers, install the capture-router plugin, register the reasoning cron
#      jobs (Morning Brief, Daily Journal Questionnaire, Reviews, Knowledge
#      Architect).
#  10. Start the API (:8000) + data worker (APScheduler: market EOD for the 5
#      classic traders at 18:00 IST, catalyst pipeline 18:00-19:00 IST for the
#      6th, journal deadline, vault publish, …).
#  11. Start Caddy on :80 (serves the static frontend, proxies /api + /health
#      to the API, serves the Quartz garden at /brain) — open to the internet
#      so you can reach it from your phone.
#  12. Start the Quartz second-brain garden container.
#  13. Start the Hermes gateway (Telegram).
#  14. Health checks + final handoff URLs.
#
# Idempotent: safe to re-run at any time — it detects what's already set up
# and skips it, so it doubles as the update/repair path.
#
# Flags:
#   --rebuild   force a frontend rebuild even if frontend/out exists
#   --restart   force-restart the api/worker/web processes
#   --fresh     wipe ALL Postgres schemas/tables/types + DuckDB + vault journal
#               and re-run migrations from scratch (destructive! used to reset
#               a deployment to a brand-new empty state)
#   --no-web    skip the Caddy/web serving step
#   --no-tools  skip the apt/brew toolchain install step
#   --no-hermes skip installing/provisioning Hermes Agent
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$PWD"
# Hermes reasoning cron schedules are always expressed in India Standard Time,
# independent of the host VM timezone.
export HERMES_TIMEZONE="Asia/Kolkata"

BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'
info()  { printf "${BLUE}[vesper]${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}[vesper]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[vesper]${NC} %s\n" "$1"; }
die()   { printf "${RED}[vesper]${NC} %s\n" "$1" >&2; exit 1; }

FORCE_REBUILD=0
FORCE_RESTART=0
FRESH=0
START_WEB=1
INSTALL_TOOLS=1
INSTALL_HERMES=1
for arg in "$@"; do
  case "$arg" in
    --rebuild) FORCE_REBUILD=1 ;;
    --restart) FORCE_RESTART=1 ;;
    --fresh)   FRESH=1 ;;
    --no-web)  START_WEB=0 ;;
    --no-tools) INSTALL_TOOLS=0 ;;
    --no-hermes) INSTALL_HERMES=0 ;;
    *) warn "ignoring unknown flag: $arg" ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1; }

IS_UBUNTU=0; IS_MAC=0
if [[ "$(uname -s)" == "Darwin" ]]; then IS_MAC=1; fi
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  [[ "$ID" == "ubuntu" || "$ID" == "debian" ]] && IS_UBUNTU=1
fi

# ── 1. Toolchain install ─────────────────────────────────────────────────
if [[ "$INSTALL_TOOLS" == "1" ]]; then
  info "Step 1 — ensuring the toolchain is installed."
  if [[ "$IS_MAC" == "1" ]]; then
    need brew || die "Homebrew is required on macOS — install it first: https://brew.sh"
    for t in git python3 node openssl curl docker; do
      need "$t" || { info "  installing $t via Homebrew…"; brew install "$t" >/dev/null 2>&1 || warn "  brew install $t failed — continuing."; }
    done
    need docker || die "Docker is required — install Docker Desktop, then re-run."
    docker compose version >/dev/null 2>&1 || warn "  Docker Compose plugin not found — install it, then re-run."
  elif [[ "$IS_UBUNTU" == "1" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    need sudo || die "sudo is required on Ubuntu."
    info "  apt-get update + install base toolchain…"
    sudo apt-get update -y >/dev/null 2>&1 || true
    for t in git python3 python3-venv python3-pip nodejs npm openssl curl ca-certificates; do
      command -v "$t" >/dev/null 2>&1 || sudo apt-get install -y "$t" >/dev/null 2>&1 || true
    done
    # Docker Engine + Compose plugin
    if ! need docker; then
      info "  installing Docker Engine…"
      curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1 || die "Docker install failed — install Docker Engine manually."
      sudo usermod -aG docker "$USER" || true
    fi
    docker compose version >/dev/null 2>&1 || {
      info "  installing docker-compose plugin…"
      sudo apt-get install -y docker-compose-plugin >/dev/null 2>&1 || warn "  compose plugin install failed — check manually."
    }
    # Caddy (web server / reverse proxy) — official repo, with binary fallback.
    if ! need caddy; then
      info "  installing Caddy…"
      sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https >/dev/null 2>&1 || true
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null 2>&1 || true
      sudo apt-get update -y >/dev/null 2>&1 || true
      if ! sudo apt-get install -y caddy >/dev/null 2>&1; then
        warn "  cloudsmith install failed — downloading Caddy binary directly…"
        cd /tmp && curl -fsSLO 'https://caddyserver.com/api/download?os=linux&arch=amd64' -o caddy.tar.gz 2>/dev/null \
          && tar xzf caddy.tar.gz caddy && sudo mv caddy /usr/local/bin/ && cd "$REPO_ROOT" \
          || warn "  Caddy binary download also failed — the web app will still build, but you'll need a server."
      fi
    fi
    # Docker adds the user to the docker group, but it won't take effect until
    # the next login. Warn if the user hasn't logged out/in yet.
    if groups "$USER" 2>/dev/null | grep -qv docker 2>/dev/null; then
      warn "  Docker installed, but your user isn't in the docker group yet."
      warn "  Log out and back in (or run: newgrp docker) before re-running start.sh."
    fi
  else
    warn "  Unknown OS — please install git, python3, node/npm, docker and caddy manually."
  fi
fi

# ── 2. Hermes Agent install ──────────────────────────────────────────────
if [[ "$INSTALL_HERMES" == "1" ]]; then
  info "Step 2 — Hermes Agent."
  if need hermes; then
    ok "  hermes already installed ($(hermes --version 2>/dev/null | head -1))"
  else
    info "  installing Hermes Agent via official installer (--skip-setup)…"
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup \
      || warn "  Hermes install failed — run it manually: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
    need hermes || warn "  hermes still not on PATH — source ~/.bashrc / ~/.zshrc and re-run."
  fi
fi

# ── 3. Python venv + dependencies ────────────────────────────────────────
info "Step 3 — Python venv + backend dependencies."
if ! need python3; then die "python3 is required."; fi
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  info "  creating .venv…"
  python3 -m venv "$REPO_ROOT/.venv"
fi
PY="$REPO_ROOT/.venv/bin/python"
if ! "$PY" -c "import fastapi, sqlalchemy, alembic" >/dev/null 2>&1 || [[ "${1:-}" == "--reinstall-deps" ]]; then
  info "  installing backend/requirements.txt…"
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$PY" -m pip install -r "$REPO_ROOT/backend/requirements.txt"
fi
ok "venv + requirements ready."

# ── 4. Frontend dependencies + build ─────────────────────────────────────
info "Step 4 — frontend (static export)."
if need npm; then
  if [[ ! -d "$REPO_ROOT/frontend/node_modules" ]]; then
    info "  npm install…"
    (cd "$REPO_ROOT/frontend" && npm install)
  fi
  if [[ "$FORCE_REBUILD" == "1" || ! -d "$REPO_ROOT/frontend/out" ]]; then
    info "  building static export (frontend/out)…"
    # Empty NEXT_PUBLIC_API_BASE → relative /api paths (same-origin via Caddy).
    (cd "$REPO_ROOT/frontend" && NEXT_PUBLIC_API_BASE= npm run build)
  else
    ok "  frontend/out already present (--rebuild to force)."
  fi
else
  warn "  npm missing — skip frontend build."
fi

# ── 5. Secrets (.env), first run only ────────────────────────────────────
info "Step 5 — .env."
set_env() { # set_env KEY VALUE
  "$PY" - "$1" "$2" <<'PY'
import sys
key, val = sys.argv[1], sys.argv[2]
try:
    lines = open(".env").read().splitlines(keepends=True)
except FileNotFoundError:
    lines = []
out, found = [], False
for ln in lines:
    if ln.startswith(key + "="):
        out.append(f"{key}={val}\n"); found = True
    else:
        out.append(ln)
if not found:
    out.append(f"{key}={val}\n")
open(".env", "w").writelines(out)
PY
}
env_get() { # env_get KEY
  "$PY" - "$1" <<'PY'
import sys
key = sys.argv[1]
try:
    for ln in open(".env"):
        if ln.startswith(key + "="):
            print(ln.split("=", 1)[1].strip()); break
except FileNotFoundError:
    pass
PY
}

if [[ ! -f "$REPO_ROOT/.env" ]]; then
  FIRST_RUN=1
  info "  first run — creating .env from .env.example."
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  # Generate passwords/secrets (only on fresh install).
  set_env POSTGRES_PASSWORD "$(openssl rand -hex 16)"
  set_env JWT_SECRET "$(openssl rand -hex 32)"
  printf "  OpenCode Go API key (required for the brain): "; read -r OPENCODE_GO_API_KEY
  [[ -n "$OPENCODE_GO_API_KEY" ]] && set_env OPENCODE_GO_API_KEY "$OPENCODE_GO_API_KEY"
  printf "  Telegram bot token (required for the agent): "; read -r TELEGRAM_BOT_TOKEN
  [[ -n "$TELEGRAM_BOT_TOKEN" ]] && set_env TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN"
  printf "  Your numeric Telegram user ID (required so the bot only talks to you): "; read -r TELEGRAM_ALLOWED_USERS
  [[ -n "$TELEGRAM_ALLOWED_USERS" ]] && set_env TELEGRAM_ALLOWED_USERS "$TELEGRAM_ALLOWED_USERS"
  ok "  .env written."
else
  FIRST_RUN=0
  ok "  .env already present — skipping secret collection."
  # Back-fill generated secrets if missing (idempotent upgrade path).
  [[ -z "$(env_get POSTGRES_PASSWORD)" ]] && set_env POSTGRES_PASSWORD "$(openssl rand -hex 16)"
  [[ -z "$(env_get JWT_SECRET)" ]] && set_env JWT_SECRET "$(openssl rand -hex 32)"
fi

PGPW="$(env_get POSTGRES_PASSWORD)"; [[ -z "$PGPW" ]] && { PGPW="change-me"; set_env POSTGRES_PASSWORD "$PGPW"; }
WEB_USER="$(env_get VESPER_BASIC_AUTH_USER)"; [[ -z "$WEB_USER" ]] && { WEB_USER="vesper"; set_env VESPER_BASIC_AUTH_USER "$WEB_USER"; }
WEB_PASS="$(env_get VESPER_BASIC_AUTH_PASSWORD)"
if [[ -z "$WEB_PASS" ]]; then
  WEB_PASS="$(openssl rand -hex 24)"
  set_env VESPER_BASIC_AUTH_PASSWORD "$WEB_PASS"
fi
KEY_OK=$(env_get OPENCODE_GO_API_KEY)
[[ -z "$KEY_OK" ]] && warn "  OPENCODE_GO_API_KEY is blank — set it in .env for LLM features."
TBOT=$(env_get TELEGRAM_BOT_TOKEN)
[[ -z "$TBOT" ]] && warn "  TELEGRAM_BOT_TOKEN is blank — the bot will not answer."
TUID=$(env_get TELEGRAM_ALLOWED_USERS)
[[ -z "$TUID" ]] && warn "  TELEGRAM_ALLOWED_USERS is blank — the bot denies everyone."

# ── 6. Vault folder structure (fresh second brain) ───────────────────────
info "Step 6 — second-brain vault."
# Ubuntu server environments don't have ~/Documents by default — create it.
VAULT_PARENT="$HOME/Documents"
mkdir -p "$VAULT_PARENT" 2>/dev/null || true
VAULT_PATH="${HERMES_VAULT_PATH:-$HOME/Documents/KnowledgeVault}"
VAULT_PATH="$(eval echo "$VAULT_PATH")"
VAULT_PATH_ABS="$(cd "$(dirname "$VAULT_PATH")" 2>/dev/null && pwd)/$(basename "$VAULT_PATH")"
# PARA-style second brain. `00 Journal`, `03 Knowledge` and `99 Assets` are
# hard-coded paths in the backend modules — never rename those three.
mkdir -p "$VAULT_PATH_ABS/00 Journal/$(date +%Y)"
mkdir -p "$VAULT_PATH_ABS/01 Inbox"
mkdir -p "$VAULT_PATH_ABS/02 Projects"
mkdir -p "$VAULT_PATH_ABS/03 Knowledge"
mkdir -p "$VAULT_PATH_ABS/04 Learning"
mkdir -p "$VAULT_PATH_ABS/05 People"
mkdir -p "$VAULT_PATH_ABS/06 Finance"
mkdir -p "$VAULT_PATH_ABS/07 Health"
mkdir -p "$VAULT_PATH_ABS/08 Career"
mkdir -p "$VAULT_PATH_ABS/09 Archive"
mkdir -p "$VAULT_PATH_ABS/99 Assets/images"
# Keep the vault folders available, but do not create a home note: a fresh
# deployment must not project a synthetic note into the intelligence graph.
rm -f "$VAULT_PATH_ABS/index.md"
if [[ ! -d "$VAULT_PATH_ABS/.git" ]]; then
  git -C "$VAULT_PATH_ABS" init -b main >/dev/null 2>&1 || true
  git -C "$VAULT_PATH_ABS" add -A >/dev/null 2>&1 || true
  git -C "$VAULT_PATH_ABS" -c user.email="vesper@local" -c user.name="Vesper" commit -m "init vault" >/dev/null 2>&1 || true
fi
set_env HERMES_VAULT_PATH_ABS "$VAULT_PATH_ABS"
set_env HERMES_VAULT_PATH "$VAULT_PATH_ABS"
ok "  vault ready at $VAULT_PATH_ABS"

# ── 7. Infrastructure: Postgres + Redis (Docker) ─────────────────────────
info "Step 7 — data layer (postgres, redis)."
if ! docker compose version >/dev/null 2>&1; then
  warn "  Docker Compose unavailable — assuming Postgres/Redis are reachable on localhost."
else
  docker compose up -d postgres redis
  PGRDY=0
  for i in $(seq 1 40); do
    if docker compose exec -T postgres pg_isready -U vesper >/dev/null 2>&1; then PGRDY=1; break; fi
    sleep 2
  done
  [[ "$PGRDY" == "1" ]] || die "  Postgres did not become ready in 80s."
  ok "  postgres + redis up."
fi

# ── 8. Migrations + feature store + trader accounts ──────────────────────
info "Step 8 — schema migrations + feature store + trader accounts."

# --fresh OR first-ever setup: reset Postgres to a truly empty state (schemas,
# tables, enum types, and the alembic version row) so migrations always re-run
# from scratch. On a brand-new VM the docker volume is empty anyway — the wipe
# is a no-op safety net that also heals a partially-initialized DB.
if [[ "$FRESH" == "1" || "$FIRST_RUN" == "1" ]]; then
  warn "  resetting Postgres to empty (schemas, tables, enum types)…"
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-vesper}" -d "${POSTGRES_DB:-vesper}" -v ON_ERROR_STOP=1 <<'SQL' 2>&1 | tail -3
DROP SCHEMA IF EXISTS finance CASCADE;
DROP SCHEMA IF EXISTS graph CASCADE;
DROP SCHEMA IF EXISTS hermes CASCADE;
DROP SCHEMA IF EXISTS journal CASCADE;
DROP SCHEMA IF EXISTS relationship CASCADE;
DROP SCHEMA IF EXISTS study CASCADE;
DROP TABLE IF EXISTS public.alembic_version;
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT n.nspname, t.typname FROM pg_type t
           JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE t.typtype = 'e' AND n.nspname NOT IN ('pg_catalog','information_schema')
  LOOP EXECUTE format('DROP TYPE IF EXISTS %I.%I CASCADE', r.nspname, r.typname); END LOOP;
END $$;
SQL
  rm -f "$REPO_ROOT/backend/data/metadata/quiver.duckdb" 2>/dev/null || true
  rm -rf "$REPO_ROOT/data/lancedb" 2>/dev/null || true
  ok "  database wiped to empty."
fi

# Migrations run on the host, so they must use the generated password and the
# host-published Postgres port rather than the Docker-internal DATABASE_URL.
set -a; source "$REPO_ROOT/.env"; set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-vesper}:${POSTGRES_PASSWORD:-change-me}@localhost:5432/${POSTGRES_DB:-vesper}"
export REDIS_URL="redis://localhost:6379/0"
"$PY" -m alembic -c "$REPO_ROOT/backend/db/postgres/alembic.ini" upgrade head
ok "  migrations applied (alembic head)."
"$PY" -c "from backend.db.feature_store import ensure_schema; ensure_schema(); print('  feature store ready')"
"$PY" -m backend.modules.finance.bootstrap
ok "  6 paper-trader accounts initialized at ₹10L each."
ok "  feature store initialized empty; no starter data seeded."

# ── 9. Provision Hermes Agent ────────────────────────────────────────────
if [[ "$INSTALL_HERMES" == "1" ]] && [[ -x "$PY" ]]; then
  info "Step 9 — provisioning Hermes Agent (config, MCP, plugin, cron)."
  "$PY" "$REPO_ROOT/hermes-config/install_hermes.py"
else
  warn "  Hermes provisioning skipped (--no-hermes or hermes not installed)."
fi

# ── 10. API + worker (host processes) ────────────────────────────────────
info "Step 10 — starting API + worker."
mkdir -p "$REPO_ROOT/.run"
pid_alive() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }
port_alive() { curl -s -o /dev/null -m 2 "http://127.0.0.1:$1/health" 2>/dev/null; }

launch() { # launch APP_MODE PORT
  local mode="$1" port="$2"
  local pidfile="$REPO_ROOT/.run/$mode.pid" log="/tmp/vesper-$mode.log"
  if pid_alive "$pidfile" || { [[ "$mode" == "api" ]] && port_alive "$port"; }; then
    ok "  $mode already running (pid $(cat "$pidfile" 2>/dev/null || echo '?'))."
    if [[ "$FORCE_RESTART" == "1" ]]; then
      info "  --restart: stopping $mode…"
      kill "$(cat "$pidfile")" 2>/dev/null || true
      sleep 2
    else
      return 0
    fi
  fi
  set -a; source "$REPO_ROOT/.env"; set +a
  export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-vesper}:${POSTGRES_PASSWORD:-change-me}@localhost:5432/${POSTGRES_DB:-vesper}"
  export REDIS_URL="redis://localhost:6379/0"
  export APP_MODE="$mode"
  export PORT="$port"
  export HERMES_VAULT_PATH="$VAULT_PATH_ABS"
  export HERMES_VAULT_PATH_ABS="$VAULT_PATH_ABS"
  # The worker runs event subscribers / scheduled jobs through asyncio.run() in
  # multiple threads; each thread owns its own event loop. NullPool keeps every
  # DB acquire bound to the current loop (avoids "Future attached to a
  # different loop").
  if [[ "$mode" == "worker" ]]; then
    export VESPER_NULL_POOL=1
  fi
  nohup "$PY" -m backend.main > "$log" 2>&1 &
  echo $! > "$pidfile"
  info "  $mode started (pid $(cat "$pidfile") — log $log)."
}

launch api 8000
launch worker 9000

# ── 11. Quartz garden + Caddy (internet-facing web) ──────────────────────
if [[ "$START_WEB" == "1" ]]; then
  info "Step 11a — Quartz second-brain garden."
  if docker compose version >/dev/null 2>&1; then
    docker compose up -d vesper-quartz || warn "  quartz container failed — garden will be skipped."
    curl -s -X POST http://127.0.0.1:8081/rebuild >/dev/null 2>&1 || true
    ok "  quartz garden up (http://localhost:8081)."
  fi

  info "Step 11b — Caddy (web app + /api proxy + /brain)."
  if need caddy; then
    mkdir -p "$REPO_ROOT/.run"
    CADDYFILE_TMP="$REPO_ROOT/.run/Caddyfile"
    VESPER_DOMAIN="${VESPER_DOMAIN:-}"
    # Security: default to localhost-only unless VESPER_DOMAIN is set (the user
    # opted into internet access, e.g. via a Tailscale MagicDNS hostname).
    # Tailscale handles authentication transparently — only devices on your
    # tailnet can reach the VM when VESPER_DOMAIN points at a .ts.net hostname.
    if [[ -n "$VESPER_DOMAIN" ]]; then
      SITE_ADDR="$VESPER_DOMAIN"
    else
      SITE_ADDR="http://localhost"
      warn "  VESPER_DOMAIN not set — binding to localhost:80 only."
      warn "  Your phone won't reach it. Set VESPER_DOMAIN=vm-name.ts.net in .env"
      warn "  (requires Tailscale on both the VM and your phone), then re-run start.sh."
    fi
    WEB_HASH="$(caddy hash-password --plaintext "$WEB_PASS")"
    cat > "$CADDYFILE_TMP" <<CAD
${SITE_ADDR} {
	encode gzip
	basicauth {
		${WEB_USER} ${WEB_HASH}
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}
	handle /health {
		reverse_proxy 127.0.0.1:8000
	}
	handle_path /brain/* {
		reverse_proxy 127.0.0.1:8081
	}
	handle {
		root * $REPO_ROOT/frontend/out
		try_files {path} {path}/ /index.html
		file_server
		header X-Content-Type-Options nosniff
		header X-Frame-Options DENY
	}
}
CAD
    if [[ -f "$REPO_ROOT/.run/caddy.pid" ]] && kill -0 "$(cat "$REPO_ROOT/.run/caddy.pid")" 2>/dev/null; then
      ok "  caddy already running (pid $(cat "$REPO_ROOT/.run/caddy.pid"))."
      if [[ "$FORCE_RESTART" == "1" ]]; then
        kill "$(cat "$REPO_ROOT/.run/caddy.pid")" 2>/dev/null || true
        caddy stop >/dev/null 2>&1 || true
        sleep 1
      fi
    fi
    nohup caddy run --config "$CADDYFILE_TMP" --adapter caddyfile > /tmp/vesper-caddy.log 2>&1 &
    echo $! > "$REPO_ROOT/.run/caddy.pid"
    ok "  caddy started on :80 (pid $(cat "$REPO_ROOT/.run/caddy.pid") — log /tmp/vesper-caddy.log)."
  else
    warn "  caddy missing — run a static server for frontend/out manually."
  fi
fi

# ── 12. Hermes gateway (Telegram) ────────────────────────────────────────
if [[ "$INSTALL_HERMES" == "1" ]] && need hermes; then
  info "Step 12 — Hermes gateway (Telegram)."
  if [[ -n "$TBOT" ]]; then
    if [[ -f "$REPO_ROOT/.run/gateway.pid" ]] && kill -0 "$(cat "$REPO_ROOT/.run/gateway.pid")" 2>/dev/null; then
      ok "  gateway already running (pid $(cat "$REPO_ROOT/.run/gateway.pid"))."
    else
      set -a; source "$REPO_ROOT/.env"; set +a
      nohup hermes gateway run --replace > /tmp/vesper-gateway.log 2>&1 &
      echo $! > "$REPO_ROOT/.run/gateway.pid"
      ok "  gateway started (pid $(cat "$REPO_ROOT/.run/gateway.pid") — log /tmp/vesper-gateway.log)."
    fi
  else
    warn "  TELEGRAM_BOT_TOKEN blank — skipping gateway (set it in .env and re-run)."
  fi
fi

# ── 13. Health checks ────────────────────────────────────────────────────
info "Step 13 — health checks."
sleep 4
if curl -s -o /dev/null -m 3 "http://127.0.0.1:8000/health"; then
  ok "  API /health → $(curl -s -m 3 http://127.0.0.1:8000/health)"
else
  warn "  API not answering /health yet — check /tmp/vesper-api.log."
fi
N_STRATS="$("$PY" - <<'PY'
import json, urllib.request
try:
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/finance/strategies", timeout=5).read())
    s = d.get("strategies", [])
    print(len(s), "|", ",".join(x["trader_id"] for x in s))
except Exception as e:
    print("ERROR:", e)
PY
)"
echo "  finance strategies → $N_STRATS"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:80/" 2>/dev/null; then
  ok "  web app up behind Caddy on :80/:443 (Basic Auth enabled)"
else
  warn "  web app not yet answering on :80 — check /tmp/vesper-caddy.log."
fi

printf "\n"
printf "${GREEN}Setup complete.${NC}\n"
printf "  API health:   http://localhost:8000/health\n"
if [[ -n "${VESPER_DOMAIN:-}" ]]; then
  printf "  Web app:      https://${VESPER_DOMAIN}/   (Caddy HTTPS + Basic Auth)\n"
else
  printf "  Web app:      http://localhost:80/   (localhost-only + Basic Auth)\n"
fi
printf "  Brain garden: http://localhost:8081/\n"
printf "  Telegram:     message your bot to talk to Hermes Agent.\n"
printf "  Logs:         /tmp/vesper-api.log · /tmp/vesper-worker.log · /tmp/vesper-caddy.log · /tmp/vesper-gateway.log\n"
printf "\n"
printf "${YELLOW}Phone access (Tailscale):${NC}\n"
printf "  1. Install Tailscale on the VM and your phone: https://tailscale.com/download\n"
printf "  2. On the VM: tailscale up\n"
printf "  3. Set VESPER_DOMAIN=<your-vm>.ts.net in .env, then re-run ./start.sh\n"
printf "  4. Your phone opens https://<your-vm>.ts.net through the tailnet\n"
printf "  Tailscale keeps the site private; Caddy still requires Basic Auth.\n"
printf "\n"
printf "${YELLOW}Recommended hardening (Ubuntu):${NC}\n"
printf "  sudo ufw enable; sudo ufw allow ssh; sudo ufw allow in on tailscale0\n"
printf "  sudo ufw default deny incoming; sudo ufw default allow outgoing\n"
printf "  This blocks all non-Tailscale inbound traffic at the OS level.\n"
printf "  Also consider a swap file on low-RAM VPSes:\n"
printf "  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile\n"
printf "  sudo mkswap /swapfile && sudo swapon /swapfile\n"
