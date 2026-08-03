# Vesper — Phase 0 Inventory

> Generated during Phase 0 of the Vesper build. Documents the **actual** structure of the
> three read-only source repos, resolves the 3-vs-4-trader question, flags every place where
> the repos drift from what `coding_prompt.md`/`plan.md` assumed, and records the Phase 0.5
> Hermes Agent RAM spike with a go/no-go recommendation.
>
> **Layout note (drift):** `plan.md`/`coding_prompt.md` assume `/vesper-system/quiver`,
> `/vesper-system/VesperAIOS`, and `/vesper-system/ProjectVesper`. The actual checkout is:
>
> | Prompt expects | Actual path |
> |---|---|
> | `quiver/` | `Quiver/Quiver/` (repo nested one level deeper under `Quiver/`) |
> | `VesperAIOS/` (the "hermes-ui" prototype) | `hermes-os/` (contains `hermes-ui/` frontend) |
> | `ProjectVesper/` | `ProjectVesper/` |
>
> All paths below are relative to the repo root, not to `/path/to/source-repository/`.

---

## 1. Quiver (`Quiver/Quiver/`) — Finance OS

Stack: Python 3 (FastAPI) backend + Next.js 16.2.10 frontend. **No APScheduler at runtime** —
scheduling is a single systemd timer firing one linear pipeline. State lives in SQLite
(`backend/data/metadata/quiver_state.sqlite`) + DuckDB (`backend/data/metadata/quiver.duckdb`).

### 1.1 Backend API surface
- `backend/api/server.py` (1489 lines) — main FastAPI app: `/api/health`, macro, regime,
  sectors, IPOs, mode, portfolios, all `/api/paper_trade/*` routes, equity history,
  `/api/paper_fno`, tournament (6 endpoints), F&O results, `/api/reports/generate`.
- `backend/api/ai_router.py` — `/api/ai/insight`, Groq-backed (llama-3.3-70b → fallback
  8b-instant), 1h TTL cache.
- `backend/api/phase5_router.py` — `/api/dashboard`, `/api/risk`, `/api/platform/health`,
  `/api/meta_portfolio`, `/api/research_db`, `/api/production_gate`,
  `/api/reports/institutional`, `/api/freeze_registry`, `/api/strategy_stats`.
- `backend/api/phase6_router.py` — `/api/models`, `/api/datasets`, `/api/attribution`,
  `/api/divergence`, `/api/notebook`, `/api/audit`.
- **`backend/api/screener.py` does NOT exist.** Screener logic lives as MCP tool
  `quiver_get_screener` in `backend/mcp_server.py`. **Flag.**

### 1.2 Data layer
- `backend/data/equity_fetcher.py` — `fetch_universe_data(size=500)` (yfinance, Nifty 500),
  used by EOD; batch size 50, retry with backoff, 12h cache.
- `backend/data/fetcher.py` — `fetch_macro_series()`, `fetch_single(symbol)`; macro tickers:
  VIX, USD/INR, crude, Nifty 50.
- `backend/data/macro_fetcher.py` — macro series fetch.
- `backend/data/universe.py` — NSE Nifty 500 membership CSV (`ind_nifty500list.csv`).
- `backend/data/duckdb_client.py` — read-only/write-capable embedded DuckDB client;
  **feature store data model is DuckDB/Parquet, unchanged for the port.** DuckDB file:
  `backend/data/metadata/quiver.duckdb` (tables `index_membership`, `symbol_mapping`).
- `backend/data/sqlite_client.py` — SQLite state; **full schema in §1.6**.
- `backend/data/cache/` holds parquet caches (`universe_*.parquet`, macro files);
  `backend/data/raw/`, `features/`, `signals/` are **empty** (feature store is written to
  `features_dir` at pipeline runtime). **Drift from README's assumed layout.**

### 1.3 Execution
- `backend/execution/cost_engine.py` — full Indian cost model (STT 0.1%, stamp 0.015%,
  NSE 0.00345%, SEBI, GST 18%, DP ₹15.50).
- `backend/execution/tax_engine.py` — FIFO STCG/LTCG engine (365-day boundary).

### 1.4 Portfolio
- `backend/portfolio/sizer.py` — PositionSizer, 5 modes (equal / score_tilt cap 0.15 floor
  0.02 / inverse_vol / kelly cap 0.25 rfr 0.07 / half_kelly cap 0.35).
- `backend/portfolio/rebalancer.py` — DriftRebalancer.
- `backend/portfolio/capital_router.py` — two-layer capital routing + hysteresis.
- `backend/portfolio/correlation_filter.py` — correlation intercept (generalized).
- `backend/portfolio/position_sizing.py` — **present but deprecated** in favor of `sizer.py`;
  confirm unused, do not port. **Confirmed still present.**

### 1.5 Paper trading — THE 3-vs-4-TRADER QUESTION
**Resolved: Quiver currently runs 5 paper traders, not 4.** The roster expanded from 4 to 5
in CHANGELOG 1.3 (2026-08-01) when `alpha_eq` was retired; docs (`README`, `CHANGELOG.md`)
now uniformly say **5**.

- `backend/paper/trader.py` (937 lines) — `PaperTrader`: T+1 settlement, mark-to-market,
  volume slippage, FIFO tax lots, SQLite persistence, dedup guard + health checks.
- `backend/paper/multi_trader_manager.py` — `MultiTraderManager.run_all_eod()` iterates
  **all configured traders** (`for t_id, trader in self.traders.items()`). Confirmed in code.
- `backend/config/paper_traders.yaml` — the **5 live traders**:
  1. `alpha_tilt` (Quiver Alpha — Score Tilt, `quiver_alpha`, score_tilt)
  2. `arjun_etf` (Arjun-Style ETF Rotation, `arjun_etf_rotation`, kelly)
  3. `lowdd_multi_asset` (Low-Drawdown Multi-Asset, `lowdd_multi_asset`, strategy_native)
  4. `momentum_surge` (Momentum Surge, `momentum_surge`, strategy_native, top-15)
  5. `alpha_generators` (Alpha Generators, `momentum_alpha`, strategy_native, top-20)
- `backend/config/paper_trading.yaml` — legacy config, `enabled: false`; **not the live config**.
- `backend/api/server.py::run_paper_trade_eod_all` (`POST /api/paper_trade/run_eod_all`)
  builds per-trader targets (alpha→DTW quiver_alpha; arjun→ArjunETFRotation;
  lowdd→LowDrawdownMultiAsset; momentum pair→`get_live_momentum_targets` n=15/20) and calls
  `manager.run_all_eod(...)`. **All 5 traders executed.**
- `alpha_eq` still present in the DB (`paper_account`) but retired per README.
- **Phase 7 implication:** port all 5 traders; `paper_trade_eod` moves to 17:00 IST weekdays
  and must cover all 5 explicitly (per `coding_prompt.md`, which says "all 4" — this is the
  drift to correct in the port).

### 1.6 SQLite schema (`sqlite_client.py` / `quiver_state.sqlite`) — 15 tables
`paper_account` (trader_id PK), `paper_holdings` (**composite PK (trader_id, ticker)**),
`paper_trades` (trader_id, symbol; tax_type), `paper_nav_history` (**composite PK
(trader_id, date)**; unrealized_stcg/ltcg), `job_runs`, `dashboard_summary`,
`experiments_index`, `research_experiments`, `freeze_versions`, `model_registry`,
`model_history`, `dataset_registry`, `audit_log`, `notebook_entries`, `divergence_metrics`.
These map to Postgres schema `finance` in Phase 2, preserving composite keys.

### 1.7 Research / strategies / ML
- `backend/research/backtester.py` — FIFO PnL backtester.
- `backend/research/validation.py` — validation pipeline (score ≥70 gate).
- `backend/research/strategies/momentum.py` — `get_live_momentum_targets(closes, n_stocks)`;
  also `momentum_library.py` (13612W, vol-adj, residual).
- `backend/research/strategies/etf_rotation.py` — `ArjunETFRotation.get_target_allocations()`.
- `backend/research/strategies/lowdd_multi_asset.py` — `LowDrawdownMultiAssetStrategy`.
- `backend/research/filters/liquidity_filter.py` — ADV gate (min ₹50 crore for stocks).
- `backend/strategies/s1_multifactor.py` — `build_quiver_alpha(closes)` → holdings/alpha.
- `backend/strategies/portfolio_builder.py` — 8 model portfolios with `portfolio_type` labels.
- `backend/strategies/regime/voting_engine.py` — `VotingEngine` with 0.65/0.35 hysteresis
  (implemented; COMPLETION.md's P0#1 was completed).
- `backend/strategies/regime/plugins/*` — 9 regime plugins (breadth, trend, VIX, HMM, etc.).
- `backend/ml/hmm_regime.py` — HMM regime model.

### 1.8 Scheduler — CONFIRMED: single pipeline, systemd-triggered
- **No APScheduler in the running system.** `backend/scheduler.py` is a single linear
  `run_pipeline()`: update_index_membership → fetch macro → fetch equity → compute factors
  (momentum_252d, volatility_21d, liquidity_21d) → build dashboard summary → **HTTP-trigger
  `run_eod_all`** → record success in `job_runs`.
- Trigger: systemd `quiver-daily.timer` at **20:30 UTC (02:00 IST)** → `python -m
  backend.scheduler`.
- README documents a 5-job IST schedule (06:00 fetch_equity, 06:30 compute_factors,
  07:00 fetch_macro, 07:30 update_universe, 18:00 paper_trade_eod) but the **code does not
  implement that split** — the README is aspirational. **Flag; Phase 7 will implement the
  real per-job schedule (with paper_trade_eod at 17:00 IST weekdays).**

### 1.9 COMPLETION.md — what Phase 4 UI work is unfinished
Read fully. All P0/P1 items are marked **[COMPLETED]** (regime hysteresis, monthly rebalance
guard, momentum library, `_round_floats`, risk_tier, typography, bracket tags, typewriter AI,
command palette, loading states). **Remaining P2/nice-to-have (not done):**
- AI-1: research report auto-generation after backtest (`GET /api/experiments/{id}/report`).
- AI-2: AI provider routing (Groq fast / Claude deep / local batch).
- Overseas cap monitor, macro overlay generalization, FinBERT sentiment overlay (0.5 weight).
- Command palette **is implemented** (`frontend/src/components/CommandPalette.tsx` confirmed).

### 1.10 Frontend
- Next.js 16.2.10 (App Router), routes: `/`, `/dashboard`, `/paper-trade`, `/portfolios`,
  `/research`, `/sectors`, `/ipos`, `/stats`. 15 components. React Query 5 for server state;
  zustand declared but **unused**.
- `src/lib/api.ts` — `API_BASE` default `localhost:8000/api`.
- Screener is SSE-streaming (client calls vesper-api directly in Phase 8).

### 1.11 MCP server
- `backend/mcp_server.py` — stdio MCP, **20 tools**, read-only default; `quiver_run_eod`
  requires explicit `EXECUTE` confirmation. Screener lives here.

---

## 2. VesperAIOS / "hermes-ui" prototype (`hermes-os/`) — Knowledge/CRM/Trading prototype

Stack: Python 3.12 FastAPI + Next.js 14 + SQLite (WAL) + LanceDB. Branded "Vesper". All
queries flow through **VesperBrain** → `POST /api/v1/chat`. **Behavior-only reference** for
the Hermes Agent adoption (its agent loop replaces VesperBrain entirely).

### 2.1 VesperBrain (`app/brain/`) — WHAT it decides to do (behavior only)
- `IntentType` enum: `KNOWLEDGE, CRM, TRADING, MULTI, CONVERSATION, SYSTEM`.
- Flow (`brain.py::chat`): `IntentClassifier.classify` (3-tier: keyword ~40% / overlap
  prototypes ~35% / LLM ~25%; confidence ≥0.80 short-circuits; multi-intent detection) →
  `Planner.create_plan` (knowledge→`search`; crm→`contacts`+`due`; trading→`portfolio`+
  `trades`; empty→default knowledge search) → `ModuleExecutor.execute` (asyncio.to_thread;
  no-dep steps parallel, `depends_on` sequential) → `ContextAssembler.assemble` (dedupe,
  successes-first) → `PromptBuilder.build` (history `[-6:]`) → `llm.chat` (temp 0.3,
  max_tokens 500) → `ResponseFormatter.format` (3 fallback strings).
- Provider: opencode-go / `deepseek-v4-flash` (base `https://opencode.ai/zen/go/v1`);
  fallback ollama `qwen3.5:4b`. **These match the Hermes Agent provider config already.**

### 2.2 Telegram bridge (`app/services/telegram_bridge.py`, 250 lines) — **the Phase 5 skill spec**
`VesperTelegramBot` reads `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS`; 8 CommandHandlers +
1 MessageHandler; sync `requests` against `localhost:8000`. **Per-command spec:**

| Command | Call | Output format | Becomes skill |
|---|---|---|---|
| `/start` | — | Welcome + command list | — |
| `/help` | — | Command list | — |
| `/search <q>` | `GET /api/v1/search?q=&top_k=5` | `🔍 Found N results:` + `content[:120]` + `📄 path`; empty→"No results found."; 4000-char cap | `search.skill` |
| `/people` | `GET /api/crm/contacts` | `👥 Contacts:` + `• name — company [category]` (max 10); empty→"No contacts in CRM." | `people.skill` |
| `/portfolio` | `GET /api/v1/portfolio` | `📈 Portfolio: ₹{total:,.0f}` + `P&L: ±₹…` + per-position `• SYM: qty @ avg → ±₹pnl` | `portfolio.skill` |
| `/ask <q>` | `POST /api/v1/chat` → `content` + `modules_used`; fallback vault search → direct LLM | Prefix `🧠 Vesper Brain (via mods)` | `ask.skill` |
| `/journal` | `GET /api/v1/journal/{today}` | `📅 YYYY-MM-DD` + `content[:3000]`; `exists=false`→"No journal entry…" | `journal.skill` |
| `/note <title>` | `GET /api/v1/notes?limit=200` filter → `GET /api/knowledge/note-content?path=` | `📄 title` + `content[:500]` (up to 3) | `search.skill` (notes) |
| free text | `POST /api/knowledge/search {q}` (fire-and-forget) | Usage-hint reply | — |

Parity additions in Phase 5: `study.skill` (Study module) and `calendar.skill` (Calendar
module) — the original bridge had neither.

### 2.3 Vault indexing / search — embedding approach
- Two overlapping paths: `modules/knowledge/vault_ingestor.py` (`FullVaultIngestor`) and
  `sync_vault.sh` (direct `memory_events`/`notes_index` inserts).
- Pipeline (`wiring.py` on `BackgroundJobRunner`): capture → classify → extract →
  resolve (5-stage EntityResolver) → evaluate → dedup (NEW/CONFIRMING/SIMILAR/CONTRADICTING)
  → route → store facts → generate notes → write (atomic) → chunk (512/64/20) → embed →
  crosslink → ingest.
- **Embeddings:** `BAAI/bge-m3`, dim 1024, backend auto (sentence-transformers / MLX /
  numpy fallback); **LanceDB** `data/vectors.lance`. Search: `SearchOrchestrator.search`
  hybrid vector + entity graph + journal/episodes, mode auto, top_k 10.
- **Decision for the port:** LanceDB remains the module-entity semantic store (plan §8.5);
  the conversational pyramid is TencentDB Agent Memory (separate layer, doesn't compete).

### 2.4 Modules (`modules/` — only crm, knowledge, trading exist)
All follow `Module(Service)` pattern with `module.yaml` manifests (validated at boot).

**Knowledge v1.0.0** — API `/api/knowledge/search|stats|note-content`; MCP tools
`knowledge_search`, `knowledge_capture`; scheduler `knowledge_ingest_vault`, `episode_detect`,
`lint_vault`, `daily_summary`; 9 worker handlers; 2 event subscriptions.

**CRM v1.0.0** — API `/api/crm/contacts?q&limit`, `/person/{name}`, `/stats`, `/due`,
`/graph`, `/suggested`; MCP tools `crm_get_person`, `crm_search_contacts`, `crm_get_stats`,
`crm_get_due_today`. `Person` model has 24 fields (nickname, hobbies, city, country,
relation_type, contact_frequency_days, twitter_handle, github_username, anniversary, …).
`intelligence.py`: vault person-mention scanning with `_is_person_context` heuristic
(`_PERSON_DIRS={00 Journal,01/02 Daily,03 Areas}`, `_PROJECT_DIRS={04 Projects,Projects}`).
`services.py`: `CRMGraphService`, `CRMMeetingPrep`.
**⚠️ Flag:** ORM (`CRMRepository`) writes 24 columns but the actual SCHEMA table
`crm_persons` has 15; several MCP/ORM writes would fail "no such column". This prototype's
CRM is *basic* (8 contacts, no graph) — per plan §8.1 it is **dropped** in favor of
ProjectVesper wholesale; the schema/ORM mismatch is therefore irrelevant to the port, but
recorded for completeness.

**Trading v2.0.0** — API `/api/trading/portfolio|trades|signals`; MCP tools
`trading_get_portfolio`, `trading_get_trades`, `trading_get_performance` (**stub {}**),
`trading_get_regime` (**stub {"regime":"neutral"}**), `trading_get_risk_metrics`
(**stub {}**); scheduler `trading_fetch_equity`, `trading_compute_factors` (off),
`trading_fetch_macro` (on), `trading_update_universe` (on), `trading_paper_trade_eod` (off).
`PaperTrader(initial_capital=100_000)` + RiskEngine; `multi_trader.py` = `TraderState`
(cash 500k) + 4 strategies (Momentum 20d top15, ETFRotation [1,3,6,12] top3, QuiverAlpha,
LowDD). **Note:** this Trading module is a *different, thinner* implementation than Quiver —
per plan §8.2 Finance OS = Quiver wholesale, so this module is reference only for its MCP
tool names (`trading_get_portfolio` etc.), not ported.

### 2.5 hermes-ui frontend
Next.js 14 App Router, 12 routes (`/`, `/knowledge`, `/knowledge/note`, `/crm`,
`/crm/[name]`, `/trading`, `/timeline`, `/search`, `/ai`, `/settings`, + loading/error/404).
TanStack Query, dark-first, shadcn-style. Timeline page is **static mock data**. Command
palette (Cmd+K) exists in layout (`components/layout/command-palette`), notifications MOCK.
**Primarily a design/behavior reference for Phase 8; not wholesale-ported.**

### 2.6 Other
- `app/core/bootstrap.py` — `HermesRuntime` 6-phase startup: discovery → validation → deps →
  load → register → lifecycle. **Behavioral reference only** (Hermes Agent replaces it).
- `config/base.yaml` — master config; loose module names (telegram/memory/search/voice/mcp/
  reranker have no packages — aspirational). `*_ref` env keys (bot_token_ref etc.).
- Live DB `data/hermes.db` — 20 tables (memory_events 64, notes_index 62, crm_persons 8,
  trading_portfolio 5, …).

---

## 3. ProjectVesper (`ProjectVesper/`) — Relationship OS (the real CRM)

Stack: React 19 + TS | FastAPI 0.111 + SQLAlchemy 2.0 **async** | SQLite (dev) /
Supabase PostgreSQL (prod). No Alembic — hand-rolled `init_db()` migrations. **This is the
source for Relationship OS wholesale (plan §8.1).**

### 3.1 SQLAlchemy models — **21 tables, not 19/20** (`backend/app/models.py`)
The prompt/README say "19 tables"; the actual ORM defines **21**. Extra vs. the assumed list:
**`person_field_history`** (field_name/old_value/new_value/changed_at). All 20 named tables
exist. Table list:
`clusters`, `persons`, `interactions`, `group_interactions`, `relationships`, `introductions`,
`person_field_history` (EXTRA), `relationship_scores`, `reminders`, `tags`, `person_tags`,
`notes`, `life_events`, `gift_ideas`, `push_subscriptions`, `rss_entries`,
`health_snapshots`, `diary_entries`, `tests`, `mock_tests`, `cron_runs`.

**`diary_entries` columns (exact, confirmed):** `id` (str PK), `title`, `category` (enum
STUDY/HOBBY/GENERAL, indexed), **`content` (Text, NOT NULL — confirmed)**, `mood` (String(10),
nullable emoji), `tags` (JSON), `word_count`, `entry_date` (DateTime, indexed), `is_pinned`,
`created_at`, `updated_at`.
**→ Phase 2 port:** `diary_entries` gets a new `vault_path` column and **loses `content`**
(plan §8.3); content lives in the vault. Mood/streak: **no stored streak column** — diary
streaks are computed on the fly in `GET /diaries/stats` (distinct `entry_date` walk); contact
streaks ARE stored on `persons.streak_weeks` + `streak_last_updated`.

`persons` is very wide (~45 cols) incl. `streak_weeks`, `betweenness_score`,
`community_id`, `fx/fy/fz`, `cluster_id`, `introduced_by_id`, `important_events` JSON.

### 3.2 Graph endpoints + network science
- `backend/app/routers/graph.py` — `GET /graph/data` (nodes = non-archived persons with
  birthday/anniversary/fx/fy/fz/betweenness/community_id; links = active relationships,
  each enriched with **composite score** via `gather_relationship_score_inputs()` +
  `calculate_composite_score()`: recency 0.30 / frequency 0.20 / sentiment 0.15 / mutuality
  0.15 / trust 0.20); `GET /graph/path?from=&to=` (BFS shortest path via `collections.deque`);
  clusters CRUD; relationships CRUD.
- **Replay endpoints (same file):** `GET /relationships/{id}/history` (weekly_scores +
  interaction_dates + introduction_dates), `GET /network/history?from_date=&to_date=`
  (relationship_scores grouped by week).
- `backend/app/services/network_science.py` — NetworkX + python-louvain:
  `build_networkx_graph` (STRONG=1.0/MEDIUM=0.6/WEAK=0.3), `compute_betweenness`
  (`nx.betweenness_centrality`, ≤3 nodes→0), `detect_communities` (Louvain
  `community_louvain.best_partition`), `find_structural_holes` (O(n²) pair scan, score =
  len(shared)/min(deg_a,deg_b)).
- `backend/app/routers/network.py` — `/network/bridge-score`, `/network/communities`,
  `/network/introduction-candidates`, `/network/dormant-valuable`, `/network/health`.

### 3.3 AI endpoints (`backend/app/routers/ai.py`) — LLM provider wiring
- `POST /ai/parse-contact`, `POST /ai/starters`, `POST /ai/summarise`, `GET /ai/health-insights`,
  `GET /ai/weekly-digest`, `POST /ai/suggest-topics`, `POST /ai/meeting-prep`.
- **Provider:** `AI_PROVIDER` env: `"groq"` (default) or `"ollama"`. Groq via raw httpx
  OpenAI-compatible endpoint (`https://api.groq.com/openai/v1/chat/completions`),
  `GROQ_MODEL_FAST`=`llama-3.1-8b-instant`, `GROQ_MODEL_SMART`=`llama-3.3-70b-versatile`;
  only `relationship_health_insights` uses `fast=False`. Ollama: `mistral`, non-streaming.
  No openai/langchain SDK — raw HTTP.
- **Phase 8/10 note:** these AI endpoints move behind Hermes Agent skills / module MCP tools;
  the Groq wiring is a reference for cost/behavior, not ported verbatim.

### 3.4 Import/export (`backend/app/routers/integrations.py`)
- `POST /import/csv` (upsert by email then name; DD/MM/YYYY preferred; auto-derived
  important_events; unarchives on re-import), `POST /import/vcard` (vobject),
  `GET /export/json`, `GET /export/csv` (22 fields), `GET /export/obsidian` (ZIP of Markdown).
- Same router: tags/notes/life-events/gifts/RSS endpoints + webhooks (`POST /webhooks/interaction`,
  `/webhooks/contact`) — **unauthenticated** webhook posts (no `get_current_user`).

### 3.5 Cron jobs + resilience (`backend/app/services/scheduler.py`, `cron.py`)
- APScheduler `AsyncIOScheduler(timezone=Asia/Kolkata)`; 6 jobs:
  `daily_reminders` (08:00), `push_dispatcher` (every 15 min), `health_updater` (03:00),
  `network_science_updater` (03:30), `rss_fetcher` (Sunday 06:00),
  `relationship_snapshot_job` (Sunday 02:00).
- `CronRun` model (`job_name` PK, `last_run_at`) + `register_job` + `_ensure_job` +
  `run_overdue_jobs()`. Catch-up: if `CronRun` row absent, seed `last_run_at = now − 30 days`;
  compute `next_time = schedule_fn(last_run)`; if `next_time <= now` → run, update, commit;
  exception → log + rollback. `push_dispatcher` is **intentionally NOT in the catch-up
  registry** (interval job). Triggered on FastAPI lifespan startup and via unauthenticated
  `POST /api/v1/cron/ensure` (external cron-job.org ping every 30 min).
- **This pattern generalizes in Phase 7 to cover the new data jobs.**

### 3.6 Full API surface — **100 endpoints (99 HTTP + 1 WS), not 106**
README claims "106 total"; the actual decorated route count is 100. **Flag.** Routers:
persons (11), interactions (8), graph (11), network (5), reminders (5), stats (4), push (5),
ai (7), integrations (25), diaries (7), tests (5), introductions (2), ws (1), app-level (4).
Auth: JWT HS256, single admin user, all except `/auth/login`, `/health`, `/cron/ensure`,
`/webhooks/*`, and public push config/keys.

### 3.7 Frontend — design-system constraints (to preserve in Phase 8)
- **TanStack Router v1** (file-based `src/routes` → `routeTree.gen.ts`); Zustand v5 + Immer
  (`stores/graphStore.ts`, `stores/uiStore.ts`); TanStack Query v5 (staleTime 30s).
- Pages: `/` (Graph OS flagship, full-screen), `/login`, `/dashboard`, `/people/`,
  `/people/$personId`, `/diary`, `/study`, `/hobbies`, `/calendar`, `/stats`, `/settings`.
- **Tailwind CSS v4** (`@import "tailwindcss"` + `@theme` in `index.css`) — **no
  `tailwind.config.*` file**; shadcn `components.json`: style `new-york`, baseColor `slate`,
  cssVariables true.
- **No indigo default — confirmed.** Theme is dark copper/amber: `--primary: 22 56% 52%`
  (#C9793F), gradient `#C9793F→#DB8E52`, accent slate-blue `#5B7C99`, teal `#14b8a6`.
- **No DiceBear — confirmed replaced.** `lib/identityGlyph.ts` generates local SVG identicons
  (djb2 hash, mirrored 5×5 grid, 6-color palette, data-URI).
- **Glassmorphism IS present** (`.glass`/`.glass-strong`, backdrop-blur 24px). **Bento-grid
  IS present** (`.bento-grid` 6-col, used by Dashboard). (The prompt assumed neither — both
  exist as CSS utilities.)
- Graph rendering: `react-force-graph-2d` (canvas) — the 3D `react-force-graph-3d`/Three.js
  was **rewritten away after bugs**; `three`/GLSL shaders still ship but are inactive.
  **Phase 8 decision point:** plan.md says keep `react-force-graph-3d` + Three.js for Graph OS
  — the actual source uses 2D; verify what to port (flag open).
- PWA: `vite-plugin-pwa`, `sw.js`, offline capture queue (`lib/captureQueue.ts` via idb-keyval).
- Backend DB: SQLAlchemy async; dev/SQLite (`data/personanet.db`), prod Supabase Postgres
  via asyncpg.

---

## 4. Phase 0.5 — Hermes Agent RAM Spike

### 4.1 Environment
- Box: **local macOS (Apple Silicon, 16GB)**, not yet a 4–8GB VPS. Hermes Agent v0.18.2
  already installed via git (`~/.hermes/hermes-agent/`,
  Python 3.11.15, install method git) — the standard installer path, so measurements are
  representative of the runtime, not of a bespoke build.
- **Provider status:** configured against opencode-go / `deepseek-v4-flash` (matches the plan).
  A live call returned **HTTP 403: "The latest version of this model is only available hosted
  in China and requires explicit opt in: https://opencode.ai/workspace/.../go"** — a
  workspace-level opt-in gate, not a config error. For the RAM measurement we used the
  working ollama provider (`qwen3.5:4b`) to exercise the agent loop; the 403 is flagged for
  Phase 3/5 to resolve (user must opt in at opencode.ai for deepseek-v4-flash, or the
  provider.yaml fallback must be relied on).

### 4.2 Method
- Added a toy stdio **echo MCP server** (`echo_mcp.py`, single `echo` tool) registered in
  Hermes Agent's `mcp_servers`. Confirmed `hermes mcp test echo-mcp` connects, lists 1 tool.
- Ran `hermes gateway run`; measured RSS via `ps` for the gateway tree.
- Ran `hermes chat -Q -q "<use echo tool>"` with the echo MCP attached; measured the
  in-flight conversation process peak.

### 4.3 Numbers (process breakdown)
| Scenario | RSS |
|---|---|
| **Baseline** (no gateway) | 0 (nothing running) |
| **Gateway idle** (running, no active conversation; gateway + stdio watchdog) | **~64–72 MB** |
| Echo MCP subprocess (watchdog + python stdio server) | **~16 MB** |
| **Active conversation** (chat worker peak, in-flight, echo tool called) | **~164 MB** |
| Local ollama `llama-server` (loaded model for local inference) | 3.6 GB — **artifact of local inference, NOT applicable** (target is API-only, plan §14: no always-on models) |

### 4.4 Comparison vs. plan.md §15 budget (4GB floor / 8GB ceiling)
Steady-state budget for the other always-on services: postgres ~350–450MB + redis
~130–160MB + caddy ~25–40MB + vesper-api ~400–600MB ≈ **~0.9–1.3 GB**. Adding Hermes Agent
gateway idle at **~70MB** (plus MCP subprocesses, which are per-module stdio servers at
~10–30MB each) leaves a huge margin. Even a full conversation burst at **~164MB** is
negligible against the 4GB floor.

### 4.5 Recommendation
**GO.** Hermes Agent's real runtime footprint (idle ~70MB, single-conversation burst ~165MB,
per-MCP subprocess ~10–30MB) fits the 4–8GB VPS budget **comfortably**, with >2.5GB of headroom
below even the 4GB floor after the rest of the stack. No need to evaluate OpenClaw or fall
back to a from-scratch capability registry on RAM grounds. Proceed to Phase 1 assuming Hermes
Agent as the cognitive engine. **Caveats carried forward:**
1. The opencode-go 403 (model opt-in) must be resolved before Phase 5 live Telegram tests.
2. These numbers are from a local 16GB Mac, not the target Ubuntu VPS; the Phase 10 resource
   audit re-measures with `docker stats` on real modules.

---

## 5. Cross-cutting flags / decisions carried into the build

| # | Flag | Decision |
|---|---|---|
| 1 | Layout drift: `Quiver/Quiver/`, `hermes-os/` (not `quiver/`, `VesperAIOS/`) | Paths in INVENTORY use actual locations; build artifacts never reference them at runtime |
| 2 | **5 paper traders, not 4** | Phase 7 `paper_trade_eod` at 17:00 IST covers all 5 (`alpha_tilt`, `arjun_etf`, `lowdd_multi_asset`, `momentum_surge`, `alpha_generators`) |
| 3 | Quiver scheduler is a single pipeline (systemd 02:00 IST), not 5 APScheduler jobs | Phase 7 implements the real split (06:00/06:30/07:00/07:30 + EOD) as plain data jobs |
| 4 | `backend/api/screener.py` absent; screener = MCP tool `quiver_get_screener` | Port screener as a Finance MCP tool (read-only) |
| 5 | ProjectVesper has **21 tables** (extra `person_field_history`), **100 endpoints** (not 106) | Port 21 models; record real endpoint count |
| 6 | `diary_entries` has `content` (NOT NULL) and no stored streak | Phase 2: drop content (vault-backed), add `vault_path`; streaks stay computed |
| 7 | ProjectVesper AI = Groq (raw httpx) / ollama fallback | AI endpoints become Hermes skills/module tools; Groq wiring = reference only |
| 8 | ProjectVesper frontend: Tailwind v4 (no config file), copper/amber theme (no indigo), identicons (no DiceBear), glassmorphism + bento-grid PRESENT, graph is 2D | Preserve design constraints in Phase 8; confirm 2D vs 3D graph choice |
| 9 | VesperAIOS trading MCP tools are stubs (`{}`, `neutral`); its CRM schema/ORM mismatch | Finance = Quiver wholesale; CRM = ProjectVesper wholesale; VesperAIOS is behavior reference only |
| 10 | VesperAIOS Telegram bridge = the exact Phase 5 skill spec (see §2.2 table) | Skills: ask/search/people/portfolio/journal + new study/calendar |
| 11 | Hermes Agent RAM spike: **GO** (idle ~70MB, convo burst ~165MB) | Hermes Agent is the foundation; skip OpenClaw/from-scratch fallback |
| 12 | Hermes Agent opencode-go model 403 (China opt-in gate) | Resolve before Phase 5 live tests; rely on fallback until then |

---

## 6. Phase 3 — Configure Hermes Agent: discrepancies logged (not fixed)

Phase 3 is complete and verified (provider.yaml + fallback chain, model-escalation rule,
echo MCP verified end-to-end, TencentDB Agent Memory plugin installed & live-verified,
command-approval gate enabled & verified, `auxiliary.vision` → Kimi K2.5 via OpenCode Go
configured & resolved). Two plan.md assumptions turned out to be
**out of date against current upstream**; both were resolved deliberately and are recorded
here as intentional divergences — not drift to undo.

### 6.1 plan.md §7 "zero external API dependency" is no longer true upstream

plan.md §7 described TencentDB Agent Memory as a lightweight, fully local plugin:
**"zero external API dependency, local SQLite + sqlite-vec only."**

Current upstream (`TencentCloud/TencentDB-Agent-Memory`) has evolved into a v3 **team memory
hub**. The Hermes plugin still exists at
`MemoryCore/hermes-plugin/memory/memory_tencentdb/` (plugin.yaml: name `memory_tencentdb`
v1.0.0, hooks `on_memory_write`/`on_session_end`), but it now requires:

- a **Node.js Gateway sidecar** (`src/gateway/server.ts`, spawned/supervised by the Python
  provider via `MEMORY_TENCENTDB_GATEWAY_CMD` or auto-discovery), and
- **LLM credentials** for the L1/L2/L3 extraction pipeline (`MEMORY_TENCENTDB_LLM_*` /
  `TDAI_LLM_*`).

**Resolution (local-first preserved):** the Gateway runs in `standalone` mode
(`deployMode: standalone`, `stateBackend: local`) with a **local SQLite** store
(`~/.memory-tencentdb/memory-tdai/vectors.db`, BM25 FTS, embedding disabled) and points its
LLM at the **Hermes API provider** via `TDAI_LLM_*` env vars, so the running system makes
**zero external-API calls beyond the agent's own provider** — the *mechanism* changed (Node
sidecar + API LLM instead of pure in-process sqlite-vec), the *architecture* intent is
unchanged.

**LLM wiring (final):** the Gateway resolves its LLM from `TDAI_LLM_*` in `~/.hermes/.env`
(not a hardcoded model), so it follows the Hermes provider config on any box:
- VPS/API: `TDAI_LLM_BASE_URL=https://opencode.ai/zen/go/v1`,
  `TDAI_LLM_MODEL=deepseek-v4-flash`, `TDAI_LLM_API_KEY=<OPENCODE_GO_API_KEY>`.
- Local dev fallback: `TDAI_LLM_BASE_URL=http://127.0.0.1:11434/v1` + a local model.

Install footprint (recorded for the Phase 10 resource audit):
- Gateway checkout: `~/.memory-tencentdb/tdai-memory-openclaw-plugin/` (auto-discovery path)
  with `tdai-gateway.yaml` (standalone, sqlite, env-driven LLM). `npm install` needed for `tsx`.
- Hermes provider: symlinked at `<hermes-agent>/plugins/memory/memory_tencentdb` (bundled
  plugin dir; discovery confirmed via `discover_memory_providers()` → `available=True`).
- Config: `~/.hermes/config.yaml` → `memory.provider: memory_tencentdb`;
  `~/.hermes/.env` → `MEMORY_TENCENTDB_GATEWAY_CMD` + `TDAI_LLM_*`.

**Verification notes (local, on Ollama):** the full L0→L1 pipeline was verified live with a
local model — a real Hermes CLI conversation was captured to L0 and extracted to L1
(`extracted=1, stored=1`, scene `数学题解`). The Gateway was then re-pointed at the API
provider (`deepseek-v4-flash`) and confirmed to boot cleanly, resolve the right model, and
fail only on the known China RegionError / weekly-limit (both transient, resolved by the
§4.1 opt-in + Monday reset) — no config errors. L2/L3 (scene/persona) run on the same LLM
path and were exercised locally; tool-calling quality depends on the model used.

**2026-08-03 — Part A divergence closed (recall now semantic/hybrid):** `tdai-gateway.yaml`
`memory.embedding` was upgraded from `provider: "none"` to a working remote provider pointed
at local Ollama, and `memory.recall.strategy` flipped `keyword` → `hybrid`:
`provider: "openai"` (any non-`local` value selects `OpenAIEmbeddingService`),
`baseUrl: http://127.0.0.1:11434/v1`, `apiKey: ollama` (placeholder — the plugin requires a
non-empty key; Ollama ignores it), `model: nomic-embed-text` (768-dim, pulled via
`ollama pull nomic-embed-text`), `dimensions: 768`, `sendDimensions: false` (Ollama's
OpenAI-compatible `/v1/embeddings` already returns 768 and accepts-but-ignores `dimensions`).
Verified end-to-end on this box with the Gateway started under local LLM overrides
(`TDAI_LLM_*` → `http://127.0.0.1:11434/v1` + `llama3.2:latest`): L1 extraction wrote a test
memory with `dims=768, norm=1.0000`; both `POST /search/memories` and `POST /recall`
return `strategy: "hybrid"` with `code=0`, and the semantic query "what is my favorite way
to make coffee" correctly recalled "用户喜欢做 pour-over 咖啡" from a stored pour-over
coffee conversation. The earlier "hybrid requires an EmbeddingService and errors code
10001" limitation (recorded above) no longer applies — embeddings are on. Note: on boot the
store auto-dropped the vec0 tables (existing L1 rows predated any embedding config) and
re-created them at 768-dim; new captures dual-write BM25 + vector. Standing caveat: the
Hermes journal is English but `memory.bm25.language` remains `"zh"` — BM25 (FTS) matching
for English queries is suboptimal, so hybrid recall leans on the vector leg; a future
change could set `bm25.language: "en"`.

### 6.2 plan.md §14 "every tier is an API call" — intentional fallback tier

plan.md §14 says **"no always-on large models in memory, every tier is an API call."**
The configured default (`deepseek-v4-flash` via opencode-go) is currently **unusable**:
every opencode-go model returns `GoUsageLimitError` ("Weekly usage limit reached. Resets in
1 day" — until ~Mon 2026-08-03), and `deepseek-v4-flash` additionally returns a `RegionError`
(China opt-in required at `https://opencode.ai/workspace/wrk_01KYFJEYCDNKK4RV0ZXD0B7RXA/go`).

**Resolution (deliberate, local-first):** a `fallback_providers` chain was added to
`~/.hermes/config.yaml`:

1. `ollama/llama3.2` @ `http://127.0.0.1:11434/v1` (local, zero cost) — primary fallback.
   Updated from `qwen3.5:4b` per plan §14: `qwen3.5:4b` is a reasoning model that leaves
   `content` empty on extraction-style calls, so `llama3.2` is the correct text-completion
   fallback. The `ollama-launch` provider entry in config.yaml was updated to match.
2. `groq/llama-3.1-8b-instant` (`key_env: GROQ_API_KEY`) — cloud fallback (key not yet set)

This is **not** drift toward an always-on local model per §14 (the 3.6GB Ollama llama-server
is transient local inference, same artifact class already excluded in §4.3). It is a
temporary, rate-limit-driven fallback tier: the configured default remains
`deepseek-v4-flash` on opencode-go, and the plan's model-escalation rule
(`vesper/hermes-config/model_escalation.py`) still treats every memory tier as an API call.
**Re-verify after the opencode-go weekly limit resets (~Mon 2026-08-03);** if the China
RegionError persists, decide whether to opt in at the opencode.ai workspace link above.

### 6.3 Follow-ups carried forward (from ADDENDUM_SECOND_BRAIN.md)

- **Before Phase 4:** add one additive Alembic migration on top of `c2525e68347f` for
  `journal.workouts`, `journal.spending`, `hermes.capture_routing_log` (addendum §1, §2.4).
  Phase 2 is complete and verified — do not re-run.
- **Still Phase 3, when convenient:** ~~add `auxiliary.vision` to `provider.yaml` → Kimi K2.5
  via OpenCode Go (addendum §8). Safe while rate-limited; works once the limit resets.~~ **DONE**
  (see §6.4).
- Phase 4 (next): Knowledge/Journal MCP servers gain six tools — `capture`,
  `recall_everything`, `update_note`, `delete_note`, `log_expense`, `log_workout`
  (addendum §1, §3, §4).
- Phase 5: `capture.skill` + `daily_journal_questionnaire` skill + questions config
  (addendum §2) — the single biggest new piece of work.
- Phase 7: two new automation rows — Daily Journal Questionnaire (21:30 IST, retries, 23:55
  hard deadline) and Vault Backup & Publish (00:15 IST); Evening Review trigger changes from
  scheduled to event-driven off `DailyJournalCompleted` (addendum §2.7, §7).
- Phase 1/10 low priority: `start.sh` one-command bootstrap (addendum §9).

### 6.4 `auxiliary.vision` → Kimi K2.5 via OpenCode Go (addendum §8) — DONE

Configured in `vesper/hermes-config/provider.yaml` and mirrored into `~/.hermes/config.yaml`
(`auxiliary.vision`): `provider: custom`, `model: kimi-k2.5`,
`base_url: https://opencode.ai/zen/go/v1`, `api_key: ${OPENCODE_GO_API_KEY}` (expands from
`~/.hermes/.env` at config load — verified the 67-char key resolves under hermes' normal
startup, dotenv loaded). **OpenCode Go is the only vision endpoint used** — no `api_key_env`
shortcut, no other provider. Hermes' auxiliary resolver reads `api_key` literally, so the
`${VAR}` form is the correct one (a bare `api_key_env` key is ignored by
`agent/auxiliary_client._resolve_task_provider_model`).

**Verification (no API call needed):** `resolve_vision_provider_client()` returns
`provider=custom, model=kimi-k2.5, client=OpenAI, base_url=https://opencode.ai/zen/go/v1/` —
exactly the intended endpoint. Works once the opencode-go weekly limit resets (~Mon
2026-08-03). Matches the addendum's §8.2 caveat: the main model (`deepseek-v4-flash`) is
text-only, so the auxiliary text-description path is the desired route regardless.

### 6.5 Phase 4 — Event Bus + Module MCP Servers — DONE

All eight module MCP servers exist under `vesper/backend/modules/<name>/` (logic +
`mcp_server.py`), register their tools, and follow the short-name contract.

**Key contract discovery (fixed this phase):** hermes-agent exposes MCP tools to the model as
`mcp__<server>__<tool>` (see `tools/mcp_tool.py::mcp_prefixed_tool_name`). Skills call
`server.tool`, so tool names must be the SHORT form (`search`, not `knowledge_search`; no
`_tool` suffix). All modules were re-verified against this after an initial mismatch
(`relationship_search`/`list_tests_tool` → corrected).

**DB session pattern:** SQLAlchemy 2.0 `async_sessionmaker` is NOT an async context manager.
The working form is `async with session_factory()() as db:` (double parens). Fixed across
study/hobbies/relationship; `common.get_session()` was removed in favor of `open_session()`.

**Modules (tool lists verified via `mcp.list_tools()`):**
- `study` — add_mock_test, create_test, delete_mock_test, delete_test, list_tests,
  mock_tests, percentiles, readiness
- `hobbies` — add, get, list_all, remove, set (over `persons.hobbies` JSON column)
- `calendar` — birthdays, events (aggregates birthdays/interactions/reminders/life
  events/study exams; `events` tool uses `ArgTransform(name="from")` since `from` is a keyword)
- `knowledge` — capture, delete_note, link_entity, note_content, recall_everything, search,
  update_note (capture-routing rules 1–8 per plan §4.1)
- `journal` — get_entry, get_mood_streak, log_expense, log_workout, read_entry, resolve,
  update_entry, write_entry (vault-backed; `vault.py` does atomic file I/O under
  `HERMES_VAULT_PATH`; verified round-trip against a temp vault)
- `relationship` — 17 tools incl. search, person_detail, create_interaction, graph, suggested
- `finance` — nav, portfolio, signals, trades. **READ-ONLY** (plan §16): SELECT-only, no
  commit/insert/update/delete, no broker API. Audited by listing tool schemas.
- `graph` — analytics, community, edges, nodes, snapshot (universal graph, plan §10; networkx
  + python-louvain over `graph_nodes`/`graph_edges`; verified on a synthetic graph)

**Not yet wired:** `mcp_servers.json` points at `/app/backend/...` Docker paths (correct for
deployment); live registration into hermes' MCP config is the final Phase 4 finishing
item once the stack runs. Event wiring is DONE: `publish()` calls are live at write points
in knowledge (5× `KnowledgeIndexed`), relationship (`PersonUpdated`×3, `InteractionLogged`),
and journal (`write_entry` → `JournalCreated`); `journal/vault_sync.py` is implemented
(subscribes `KnowledgeIndexed`, upserts `diary_entries` metadata from frontmatter, emits
`JournalCreated`, verified against a temp vault with mood/tags extraction). Each module now
carries an `events.yaml` manifest (plan §6). Finance/Calendar/Study/Graph emit no events —
Finance is read-only (plan §16) and the others aggregate/read only.

### 6.6 Phase 5 — Wire Hermes Agent to Modules + Skills — IN PROGRESS

**MCP registration (5.1) — DONE.** All 8 module servers registered in `~/.hermes/config.yaml`
`mcp_servers` (local venv paths + `PYTHONPATH`/`cwd`), toy `echo-mcp` disabled. Every server
verified to launch and serve tools over real MCP stdio (probed with the `mcp` Python client:
knowledge 7, relationship 17, journal 8, study 8, hobbies 5, calendar 2, finance 4, graph 5).
All 8 pass hermes' `validate_mcp_server_entry` security checks (no exfiltration/exfiltration-
shaped flags).

**Critical discovery — skill file format.** Hermes discovers skills ONLY as
`<dir>/<name>/SKILL.md` (frontmatter YAML + markdown body), NOT the `*.skill` flat files the
original plan specified (`tools/skills_tool.py::_find_all_skills` scans `iter_skill_index_files(..,
"SKILL.md")`). Converted all 12 skills (7 command + 5 cron) from `*.skill` → `<name>/SKILL.md`
and registered both `hermes-config/skills/` and `hermes-config/cron/` under
`skills.external_dirs`. Verified via `skills_list()`: all 12 discoverable; `skill_view()` loads
content/metadata/tags.

**Skill ↔ tool contract (5.2) — DONE.** Programmatic cross-check: every `server.tool(...)`
reference in all 12 SKILL.md files resolves to a real registered tool with matching arg names
against the live FastMCP schemas. All pass. (The `*.skill` extension is now retired in favor of
`SKILL.md`; update any plan/coding-prompt references accordingly.)

**5.3–5.5 (voice-note, Telegram gateway, approval re-confirm)** — require the live stack +
a real Telegram account. Config touched: `approvals: mode: manual`,
`destructive_slash_confirm: true` (Phase 3, unchanged); Finance read-only already enforced at
the server (Phase 4). To run: `docker compose up` for postgres/redis, point `~/.hermes` at the
stack, then send a real message / voice note and inspect hermes' MCP audit trail.

---

*Phase 0 complete. `COMPLETION.md` (Quiver) read fully. Phase 0.5 gate passed (GO). Phase 2
data layer verified. Phase 3 (Hermes Agent configuration) complete and verified —
two upstream divergences recorded above as intentional resolutions. Phase 4 module MCP
servers built, tool-verified, and event-wired (see §6.5). Phase 5 module registration +
skills wired into hermes (see §6.6); live gateway verification pending the running stack.*

---

## Build status addendum (2026-08-02) — Phases 6–8 & 10 complete

Phase 0 inventory and Phase 1–5 remain as documented above. This addendum
records what landed in the final build pass against `plan.md` + `ADDENDUM_SECOND_BRAIN.md`.

### Phase 6 — Notification "what matters"
- `backend/notification/__init__.py`: Telegram-only delivery (`send_telegram` via Bot API;
  no ntfy per addendum §11 decision). `triage()` runs NAV-drop (≤ −4%), birthday-tomorrow,
  and due-contact rules; event-driven `notify_event` for `ReminderDue` / incomplete
  `DailyJournalCompleted`. Anti-nagging: undated reminders deferred to Weekly Review.

### Phase 7 — Automation
- `backend/automation/scheduler.py`: APScheduler, IST schedules — `fetch_equity` 06:00,
  `compute_factors` 06:30, `fetch_macro` 07:00, `update_universe` 07:30, `paper_trade_eod`
  17:00 Mon–Fri, `knowledge_architect_pass` 02:30, `graph_analytics_pass` 03:00,
  `index_vault_semantic` 03:15, `crm_followups_sweep` hourly, `rss_process` Mon 06:45,
  `journal_questionnaire_deadline` 23:55, `vault_backup_publish` 00:15, `hermes_mirror` 5 min,
  notification sweeps 08:00/18:00. Event subscribers: graph write adapter, notification.
- Job modules in `backend/automation/jobs/`: `finance.py`, `graph_analytics.py`,
  `knowledge_architect.py`, `crm_followups.py`, `rss.py`, `lancedb.py`, `journal_deadline.py`,
  `vault_publish.py`, `hermes_mirror.py`.

### Addendum §2 — Daily Journal Questionnaire (plan §12.1)
- `hermes-config/cron/daily_journal_questionnaire/SKILL.md` (21:30 IST cron skill).
- `hermes-config/cron/daily_journal_questions.yaml` — versioned fixed question set (Q1–Q9),
  turn groups, quick mode, retry slots, §2.4 decomposition map.
- `backend/modules/journal/logic/complete_day()` + `journal.complete_day` MCP tool — marks
  `diary_entries.complete`, publishes `DailyJournalCompleted`.
- `backend/automation/jobs/journal_deadline.py` — 23:55 IST hard-deadline placeholder
  (a record always exists before midnight).
- Evening Review (`hermes-config/cron/evening_review/SKILL.md`) trigger changed to
  event-driven off `DailyJournalCompleted` + scheduled fallback (§2.7).

### §10 — Universal graph write adapter
- `backend/modules/graph/write_adapter.py`: `graph_subscriber(event, payload)` upserts
  deterministic-md5 graph nodes/edges on `PersonUpdated` / `InteractionLogged` /
  `KnowledgeIndexed`. Populates the previously-empty `graph.graph_nodes`/`graph_edges`.

### §13 — Semantic layer
- `backend/db/lancedb_client.py`: embedded LanceDB `vault` table; deterministic local
  token-hash TF-IDF embedder (no external embedding API; degraded-recall per plan §7).
  `backend/automation/jobs/lancedb.py` rebuilds nightly (03:15 IST).
- `knowledge_recall_everything` fans out vault + LanceDB + capture-routing log + journal.

### Phase 8 — Web frontend
- `frontend/` (Next.js 15, static-exported via `output: "export"`, served by Caddy):
  Dashboard, Graph OS (force-graph), People, Journal, Finance (portfolio/trades/signals/nav),
  Study, Calendar. Talks to `backend/api/routers.py` REST surface (`/api/...`).

### Phase 10 — Integration tests
- `tests/test_integration.py` (pytest, 11 tests): relationship/journal/study logic,
  journal complete-day + deadline job, graph adapter upsert, LanceDB index+search,
  scheduler registration, notification triage, API endpoints, event catalog. Run:
  `.venv/bin/python -m pytest` (needs the stack up). `VESPER_TESTING=1` uses a NullPool so
  the asyncpg engine doesn't pin connections to a closed test event loop.

### Misc
- `backend/api/routers.py` — `/study/readiness` now defaults `test_id` to the newest test.
- `start.sh` — idempotent one-command bootstrap (addendum §9); `.env.example` added.
- `docker-compose.yml` — `vesper-worker` command fixed to `python -m backend.main`.
- `hermes-config/model_escalation.py` + `provider.yaml` synced to hy3 / gpt-5.6-luna
  (deepseek-v4-flash is region-gated; opencode-go weekly cap resets ~2026-08-03).
