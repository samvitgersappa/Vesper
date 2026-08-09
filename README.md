# Vesper — Personal Intelligence Operating System

One folder (`vesper/`) containing a complete personal-intelligence system: a
Relationship OS, a Finance OS, and a Knowledge OS, unified behind a single
cognitive engine — **Hermes Agent** (NousResearch/hermes-agent). Hermes Agent is
installed via its own installer; it is never vendored into this repo. It plans
and calls capabilities over **MCP**, and each module ships as an MCP server
holding its own business logic. Hermes contains no domain logic.

```
┌────────────────────────────  Hermes Agent (separate process) ────────────────────────────┐
│  Telegram gateway · skills · cron (Morning Brief, Daily Journal, Reviews)                │
│  ── MCP ──▶ 8 module servers  ·  model escalation (hy3 → gpt-5.6-luna → Ollama → Groq)  │
└───────────────────────────────────┬──────────────────────────────────────────────────────┘
                                    │ MCP (stdin/stdout)
      ┌─────────────────────────────┴──────────────────────────────┐
      │                      vesper/ (this repo)                   │
      │  modules/ (journal, relationship, knowledge, finance,      │
      │           study, calendar, hobbies, graph — each an MCP     │
      │           server + logic/)                                  │
      │  events/ (Redis pub/sub bus)     automation/ (APScheduler)  │
      │  db/ (Postgres schemas, DuckDB feature store, LanceDB)      │
      │  api/ (FastAPI)  frontend/ (Next.js static)  caddy (proxy)  │
      └─────────────────────────────────────────────────────────────┘
```

## What this is

Vesper unifies three existing codebases into one Personal Intelligence OS:

- **Relationship OS** (from ProjectVesper): CRM, force-graph, network science,
  journal, study, hobbies, calendar, reminders.
- **Finance OS** (from Quiver): live data pipeline, DuckDB feature store,
  5 paper-trading strategies, 8 model portfolios, backtest tooling.
- **Knowledge OS / Universal Inbox** (from VesperAIOS, via Hermes Agent):
  vault (Obsidian) search, entity Q&A, Telegram/voice via Hermes Agent's
  native gateway, automatic capture routing.

## Repository layout

```
vesper/
├── docker-compose.yml        # postgres, redis, caddy, vesper-api, vesper-worker, vesper-quartz
├── Caddyfile                 # web app + /api proxy + Quartz garden, behind Tailscale
├── start.sh                  # one-command idempotent bootstrap
├── .env.example              # every environment variable the code reads
├── plan.md                   # architecture authority (read this first)
├── ADDENDUM_SECOND_BRAIN.md  # second-brain / vault / questionnaire decisions
├── INVENTORY.md              # Phase 0 inventory of the three source repos
├── backend/
│   ├── main.py               # single FastAPI app; APP_MODE=api|worker
│   ├── modules/<name>/       # one MCP server per module + logic/ (ported logic)
│   │   ├── activity/         # live feed of real writes (hermes, journal, finance, …)
│   │   ├── graph/            # universal graph: write adapter + self-healing backfill
│   │   └── ipo/              # IPO calendar (curated sample until a live feed lands)
│   ├── events/               # Redis pub/sub bus + event catalog (bus.py, catalog.py)
│   ├── automation/           # plain-data job scheduler (scheduler.py + jobs/)
│   ├── db/                   # Postgres schemas, alembic, DuckDB, LanceDB
│   │   ├── postgres/         # SQLAlchemy models + alembic migrations
│   │   ├── feature_store.py  # DuckDB price/factor persistence
│   │   ├── duckdb_client.py  # embedded DuckDB client (rw + read-only)
│   │   └── lancedb_client.py # semantic vault index (local TF-IDF embedder)
│   ├── api/routers.py        # REST surface for the web dashboard
│   ├── notification/         # Telegram-only notification triage + delivery
│   └── config/               # settings.yaml, secrets.env.example
├── quartz/                   # Vesper Second Brain — Quartz v5 private garden
│   ├── Dockerfile            # node:24 image with the Quartz v5 template baked in
│   ├── quartz.config.yaml    # graph, search, backlinks, explorer (private, no analytics)
│   ├── rebuild.sh            # vault sync + frontmatter sanitize + build
│   ├── server.mjs            # POST /rebuild trigger + static server
│   └── sanitize.sh           # fixes `[[key]]:` frontmatter in the build copy only
├── hermes-config/            # configures the adopted Hermes Agent (NOT its source)
│   ├── mcp_servers.json      # 8 module MCP servers (host-path template)
│   ├── sync_mcp.py           # merges the template into ~/.hermes/config.yaml
│   ├── provider.yaml         # hy3 (opencode-go) + gpt-5.6-luna/Ollama/Groq fallback
│   ├── model_escalation.py   # plan §14 escalation (long-context / finance·study analyze)
│   ├── skills/               # ask/search/people/portfolio/journal/study/calendar
│   ├── cron/                 # Morning Brief, Daily Journal Questionnaire (+questions YAML),
│   │                         # Evening/Weekly/Monthly Review, Knowledge Architect
│   └── memory/               # TencentDB Agent Memory plugin config (L0–L3)
├── frontend/                 # Next.js 15 app — static export served by Caddy
│   ├── app/                  # overview, graph, people, journal, finance, spending, ipo,
│   │   └─                     # study, calendar (+ live activity feed on the dashboard)
│   ├── components/           # Nav, PageHeader, LiveActivity
│   └── out/                  # build output (git-ignored; produced by start.sh)
├── tests/                    # Phase 10 integration tests (pytest, needs the stack up)
└── backend/data/raw/         # ind_nifty500list.csv — the bundled Nifty-500 universe
```

## Architecture invariants

Read `plan.md` for the full architecture. The non-negotiable rules:

1. **Hermes is the single cognitive engine; modules hold business logic. Hermes never does.**
2. **Finance MCP server is read-only, no exceptions** — the worker/scheduler is the only Finance writer (plan §16).
3. **Event bus (Redis pub/sub) for module-to-module decoupling**; Hermes sits *outside* that graph, at the edges only (plan §0/§6).
4. **Journal is vault-backed** — content lives in the Obsidian vault at `00 Journal/YYYY/YYYY-MM-DD.md`; `diary_entries` is metadata only (plan §8.3).
5. **Notifications are Telegram-only** (addendum §11 — no ntfy); the worker triages and sends via the Bot API.
6. **Daily Journal Questionnaire** (addendum §2): 21:30 IST cron skill; `journal.complete_day` publishes `DailyJournalCompleted`; Evening Review is event-driven off it with a scheduled fallback; the 23:55 IST worker job guarantees a record exists before midnight.

## The data stores

| Store | Technology | Purpose |
|---|---|---|
| Postgres | `postgres:16` | System of record — relationship, journal metadata, finance accounts/trades, study, hermes, graph (7 schemas, 56 tables) |
| Redis | `redis:7` | Event bus (pub/sub), ephemeral |
| DuckDB | `quiver.duckdb` | Analytical feature store — `equity_daily`, `macro_series`, `factor_features`, `index_membership`, `symbol_mapping` |
| LanceDB | `data/lancedb` | Semantic index over the Obsidian vault (local TF-IDF, no external embedding API) |
| Obsidian vault | `~/Documents/KnowledgeVault` | Source of truth for journal + knowledge notes (`00 Journal/`, `03 Knowledge/`, …) |
| Quartz | `vesper-quartz` container | Builds the vault into a private static garden (graph, search, backlinks) served at `/brain` |
| Hermes state | `~/.hermes/state.db` | Hermes Agent's own SQLite (tool-call/usage mirror source) |

## Scheduled jobs (APScheduler worker)

| Job | Schedule (IST) | What it does |
|---|---|---|
| `fetch_equity` | 06:00 daily | Pulls the Nifty-500 universe from yfinance into `equity_daily` |
| `compute_factors` | 06:30 daily | Computes 7 factors per symbol into `factor_features` |
| `fetch_macro` | 07:00 daily | Pulls 8 macro series (Nifty, VIX, USD/INR, crude, gold, …) |
| `update_universe` | 07:30 daily | Refreshes `index_membership` from the bundled Nifty CSV |
| `paper_trade_eod` | 18:00 Mon–Fri | End-of-day mark-to-market for the 5 classic paper traders → `paper_nav_history` |
| `knowledge_architect_pass` | 02:30 daily | Vault re-org / consolidation pass |
| `graph_analytics_pass` | 03:00 daily | Community detection + relationship analytics → `graph_snapshots` |
| `graph_projection_backfill` | 03:05 daily | Rebuilds `graph_nodes`/`edges` from the real source tables (also runs once at worker startup) |
| `index_vault_semantic` | 03:15 daily | Rebuilds the LanceDB semantic index from the vault |
| `crm_followups_sweep` | every 1h | Due reminder follow-up sweep |
| `rss_process` | 06:45 Mon | Routes RSS feeds through `knowledge.capture` |
| `journal_questionnaire_deadline` | 23:55 daily | Guarantees a journal record exists before midnight |
| `vault_backup_publish` | 00:15 daily | Pushes the Obsidian vault to a private GitHub repo + triggers the Quartz garden rebuild |
| `hermes_mirror` | every 5m | Mirrors Hermes tool-calls/usage into the `hermes` Postgres schema |
| `notification_sweep_morning` | 08:00 daily | Morning Telegram digest |
| `notification_sweep_evening` | 18:05 daily | Evening Telegram digest (fires after paper_trade_eod to show fresh NAV) |
| `fetch_catalyst_bhavcopy` | 18:00 Mon–Fri | NSE Common Bhavcopy delivery data → `delivery_stats` |
| `fetch_fii_dii` | 18:05 Mon–Fri | NSE provisional FII/DII net flows → `market_sentiment_daily` |
| `fetch_index_pcr` | 18:07 Mon–Fri | Nifty/BankNifty index option-chain PCR → `index_options_sentiment` |
| `fetch_sector_indices` | 18:10 Mon–Fri | yfinance sector indices → `sector_scores_daily` |
| `compute_market_breadth` | 18:15 Mon–Fri | A/D, % > 50DMA/200DMA, 52w highs/lows from `equity_daily` |
| `catalyst_screen` | 18:20 Mon–Fri | Layer 1/2/3 multiplicative scoring → `catalyst_scores` + watchlist funnel |
| `catalyst_llm` | 18:40 Mon–Fri | Capped DeepSeek V4 Flash catalyst analysis over the top of the funnel |
| `catalyst_risk` | 18:50 Mon–Fri | Exits-only risk pass: ATR/trailing stops, rank, negative-catalyst, time |
| `catalyst_paper_trade` | 19:00 Mon–Fri | Catalyst Swing entries (cost-gated) + NAV snapshot |

Every finance job logs to `finance.job_runs` and degrades honestly (records a
`degraded` run) instead of failing the worker or fabricating data. The catalyst
swing trader is the 6th strategy (`catalyst_swing`) and is funded on a **₹10L
(1,000,000) paper account** — position sizing scales off account equity, so the
funnel, cost gate and swing engine are exercised at meaningful notional sizes.

## Module MCP servers (67 tools)

| Server | Tools | Purpose |
|---|---|---|
| journal | 12 | `write_entry`, `get_entry`, `complete_day`, expense logging, spending summaries, workout logging, streak, resolve… |
| relationship | 18 | people CRUD, interactions, reminders, introductions, gift ideas, health, search, stats, draft_message |
| knowledge | 7 | `capture` (routing), vault search, unified recall (vault + LanceDB + journal), notes edit/delete |
| finance | 9 | portfolio, trades, signals, nav + catalyst_scores, catalyst_candidates, catalyst_positions, catalyst_usage, catalyst_cost_gate (read-only) |
| study | 8 | tests, readiness, percentiles, study plan |
| calendar | 3 | birthdays, events, on_this_day |
| hobbies | 5 | activity tracking |
| graph | 5 | nodes, edges, analytics, community |

The Finance server is strictly read-only; the worker/scheduler is the only writer to the
`finance` schema (plan §16).

## Quick start

### Requirements

- macOS or Linux
- Docker + Docker Compose plugin
- Node.js 18+ (for the frontend build)
- Python 3.12+ (for the local venv used by Hermes MCP servers)
- A Hermes Agent install (optional but recommended)

### One command

```bash
./start.sh
```

`start.sh` is the **single entrypoint for a fresh machine** (Ubuntu VM or
macOS). It does literally everything:

1. **Toolchain** — installs git, python3, node/npm, openssl, Docker + Compose,
   and Caddy via `apt` (Ubuntu) or Homebrew (macOS).
2. **Hermes Agent** — installs it via the official installer (`--skip-setup`).
3. **Frontend** — builds the Next.js static export into `frontend/out`.
4. **Secrets** — on first run only, asks for the **OpenCode Go API key**, the
   **Telegram bot token**, and your **numeric Telegram user ID** (the bot only
   replies to you); generates `POSTGRES_PASSWORD` + `JWT_SECRET`.
5. **Second-brain vault** — creates `~/Documents/KnowledgeVault` fresh
   (`00 Journal/YYYY`, `03 Knowledge`, `99 Assets/images`, `01 Inbox`,
    `02 Projects`) and git-inits it. No synthetic notes are created.
6. **Data layer** — starts postgres + redis (Docker); on first run wipes the DB
   to empty, then runs `alembic upgrade head` (56 tables across 7 schemas,
   personal tables empty), initialises empty DuckDB/LanceDB stores, and creates
   only the **6 paper-trader accounts**, each funded with ₹10L. No people,
   journal entries, expenses, notes, graph rows, holdings, or trades are seeded.
7. **Hermes provisioning** — writes `~/.hermes/.env`, merges `~/.hermes/config.yaml`
   (provider + fallbacks, approvals, skills/cron external dirs), syncs the 8
   module MCP servers, installs the capture-router plugin, and registers the 6
   reasoning cron jobs (Morning Brief 07:30, Daily Journal Questionnaire 21:30,
   Evening/Weekly/Monthly Review, Knowledge Architect 02:30).
 8. **Backend** — starts the localhost-only API (:8000) and data worker.
 9. **Web** — starts the Quartz garden and authenticated Caddy proxy. Set
    `VESPER_DOMAIN` to a hostname for automatic HTTPS; Caddy is the only public
    entry point.
10. **Gateway** — starts the Hermes Telegram gateway.

Idempotent: re-running preserves existing data. `--fresh` wipes all Vesper
Postgres schemas, DuckDB/LanceDB data, and the vault home note, then re-migrates.
It recreates only the six ₹10L paper accounts required by the finance roster.

### Security — Tailscale (recommended)

By default the web app binds to **localhost only** — no public internet access.
To reach it from your phone, use Tailscale (free, encrypted tailnet):

```
# On the VM and your phone: https://tailscale.com/download
tailscale up
echo "VESPER_DOMAIN=<your-vm>.ts.net" >> .env
./start.sh   # Caddy now serves on your tailnet-only domain
UFW firewall (Ubuntu):
sudo ufw enable && sudo ufw allow ssh
sudo ufw allow in on tailscale0 && sudo ufw default deny incoming
```

Now your phone opens `http://<your-vm>.ts.net` through the encrypted tailnet.
No ports are exposed to the public internet.

### Manual alternative

```bash
cp .env.example .env            # fill in secrets
docker compose up -d            # postgres + redis + caddy + vesper-api
docker compose up -d --build vesper-worker   # worker runs the scheduler
```

### Pointing Hermes Agent at this repo

`start.sh` automates all of this via `hermes-config/install_hermes.py`. To do it
manually:

1. Install Hermes Agent with its standard installer (plan.md §0 / Phase 3).
2. Merge the Vesper config template + provider chain:
   ```bash
   .venv/bin/python hermes-config/install_hermes.py   # config, MCP, plugin, cron
   ```
   or step-by-step: set `hermes model` → `opencode-go` / `hy3`, then
   `.venv/bin/python hermes-config/sync_mcp.py ~/.hermes/config.yaml`.
3. Apply `hermes-config/provider.yaml` (fallback chain) and
   `hermes-config/model_escalation.py` per plan §14.
4. `hermes-config/install_hermes.py` installs the `vesper-capture-router`
   plugin (deterministic second-brain capture routing) and registers the 6
   reasoning cron jobs.
5. Configure the Telegram gateway with `TELEGRAM_BOT_TOKEN` +
   `TELEGRAM_ALLOWED_USERS` in `~/.hermes/.env` (the gateway auto-enables
   Telegram when the token is present), then `hermes gateway run`.

Hermes Agent connects to `vesper/`'s module MCP servers over the local network /
stdin-stdout — it never imports anything from this repo.

## Configuration reference (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `OPENCODE_GO_API_KEY` | OpenCode Go provider key (hy3 primary, gpt-5.6-luna fallback) | (empty — required) |
| `TELEGRAM_BOT_TOKEN` | Bot token for notifications | (empty) |
| `TELEGRAM_ALLOWED_USERS` | Your numeric Telegram ID (recipient) | (empty) |
| `TELEGRAM_HOME_CHANNEL` | Optional group/channel chat ID; falls back to `TELEGRAM_ALLOWED_USERS` | (empty) |
| `VESPER_BASIC_AUTH_USER` / `_PASSWORD` | Public dashboard/API Basic Auth credentials | generated |
| `POSTGRES_USER` / `_PASSWORD` / `_DB` | Postgres credentials | `vesper` / generated / `vesper` |
| `DATABASE_URL` | Docker-internal URL; host MCP servers receive a generated localhost URL automatically | `postgresql+asyncpg://…@postgres:5432/vesper` |
| `REDIS_URL` | Docker-internal URL; host MCP servers receive `redis://localhost:6379/0` automatically | `redis://redis:6379/0` |
| `JWT_SECRET` | Dashboard JWT signing key | generated |
| `HERMES_VAULT_PATH` | Obsidian vault root | `~/Documents/KnowledgeVault` |
| `HERMES_STATE_DB` | Hermes Agent SQLite state | `~/.hermes/state.db` |
| `GH_PAT` / `VAULT_REPO_URL` | Vault backup to a private GitHub repo (addendum §7) | (empty — optional) |
| `VAULT_GIT_REMOTE` | Full git remote URL (overrides `VAULT_REPO_URL` + `GH_PAT`) | (empty) |
| `QUARTZ_DIR` / `QUARTZ_OUTPUT` | Optional Quartz digital-garden rebuild | (empty) |
| `RSS_FEEDS` | Comma-separated RSS feed URLs for `rss_process` | (empty) |
| `CATALYST_LLM_BASE_URL` | Catalyst LLM OpenAI-compatible base URL | `https://api.deepseek.com/v1` |
| `CATALYST_LLM_API_KEY` | Catalyst LLM key (falls back to `OPENCODE_GO_API_KEY`) | (empty — catalyst LLM stage degrades to `signal=none`) |
| `CATALYST_LLM_MODEL` | Catalyst LLM model | `deepseek-v4-flash` |
| `CATALYST_TRADER_MAX_LLM_CALLS_PER_DAY` | Daily catalyst LLM call budget | `65` |

## Tests

```bash
VESPER_TESTING=1 .venv/bin/python -m pytest tests/   # needs the stack up
```

34 integration tests cover relationship stats/search, journal streak +
`complete_day` round-trip, the 23:55 deadline job, the graph write adapter,
LanceDB index + search, scheduler registration, the finance feature store +
universe refresh, notification triage, the REST API, the event catalog, and the
catalyst swing trader. Tests that need the live market-data pipeline (the
DuckDB feature store is empty on a fresh install until the 06:00–07:30 jobs run)
skip cleanly rather than fail, mirroring the worker's honest degraded mode.

## Web dashboard

The Phase 8 Next.js dashboard is served by Caddy at `http://localhost/` (static
export in `frontend/out/`). Pages: Dashboard, Graph OS, People, Journal,
Finance, Study, Calendar. The API lives at `http://localhost:8000` (`/health`,
`/api/relationship/*`, `/api/journal/*`, `/api/study/*`, `/api/finance/*`,
`/api/graph/*`, `/api/calendar/*`, `/api/hobbies`).

## Deployment

See **[`DEPLOYMENT.md`](DEPLOYMENT.md)** for a full production walkthrough:
server provisioning, Docker deployment, Hermes Agent install + config, the
nightly vault-backup push, backups/restores, monitoring, and operational
runbooks.

## Status

Phases 0–8 and 10 of `coding_prompt.md` are implemented and verified end-to-end
(inventory, data layer, Hermes config, module MCP servers, gateway + skills,
notification, automation, web frontend, integration tests). Phase 12 automation
is fully live with a real yfinance finance pipeline. See `INVENTORY.md` for the
RAM-spike numbers and `plan.md` for the architecture.
