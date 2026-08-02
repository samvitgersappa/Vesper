# Vesper — Personal Intelligence Operating System
## Architecture Plan (v2.1 — incorporates the "adopt, don't build, Hermes" pivot)

This is not a merge of three apps. It is one Personal Intelligence Operating System,
built by reading three existing codebases as reference material and porting only
what earns a place in the new architecture. **Hermes is the single cognitive engine.
Modules hold business logic. Hermes never does.**

Source material (read-only reference during the build, never the final home for code):

| Folder | What it contributes |
|---|---|
| `/vesper-system/quiver` | Finance OS: data pipeline, feature store, backtester, 4 paper-trading strategies, 8 model portfolios |
| `/vesper-system/VesperAIOS` | The existing `hermes-ui` prototype — VesperBrain orchestration pattern, dynamic-module-loader (`module.yaml`), a **working Telegram bridge** (`/ask /search /people /portfolio /journal`), Obsidian vault indexing |
| `/vesper-system/ProjectVesper` | Vesper's real Relationship OS: force-graph, Replay, network science, journal, study, hobbies, calendar, push notifications, 106 endpoints |

Final output: **one folder**, e.g. `/vesper-system/vesper`, containing the whole system. The three source folders are never edited and never become part of the shipped tree — see `coding_prompt.md` for exact build mechanics.

---

## 0. Adopt vs. Build — the single biggest change in this revision

Everything below was originally written assuming Hermes (the classifier → planner →
capability-registry → context-assembler → LLM-manager pipeline in the original §5)
would be built from scratch in Phase 3. That assumption is now the one open question
worth re-litigating before writing any of that code, because a very close match
already exists, open-source, MIT-licensed, and mature:

**[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)** — "the
self-improving AI agent built by Nous Research." 223k stars, 43k forks, Python-native
(Python 3.11, `pyproject.toml`, `uv`-managed). It already does, out of the box:

- **Universal Inbox, essentially built-in.** A single gateway process serving Telegram,
  Discord, Slack, WhatsApp, Signal, and CLI, with voice memo transcription and
  cross-platform conversation continuity — this is §4's Universal Inbox + voice
  pipeline, already shipped.
- **Memory, close to §7's four layers.** A closed learning loop: agent-curated memory
  with periodic nudges, autonomous skill creation after complex tasks, skills that
  self-improve during use, FTS5 session search with LLM summarization for cross-session
  recall, and Honcho-based dialectic user modeling (persona-building from conversation,
  the same shape as §7's persistent/semantic layers and §9's Knowledge Architect).
- **Automation Engine, built-in.** A cron scheduler with delivery to any connected
  platform — natural-language scheduled jobs, no APScheduler needed for the
  agent-reasoning half of §12.
- **Capability transport, exactly as anticipated.** MCP client support — "connect to
  any MCP server for extended tool capabilities." §5 of the original plan already said
  capabilities "may be transported over MCP under the hood" as a hedge; this makes that
  the primary path rather than a hedge.
- **Delegation.** Isolated subagents for parallel workstreams — relevant if a single
  voice note needs to fan out across several modules concurrently (§4's worked example).
- **Security primitives already built.** Command approval, DM pairing, and container
  isolation — a direct implementation surface for §16's hard rule ("Hermes never gets a
  capability that executes a trade, sends a message, or performs a destructive
  relationship-graph write without explicit confirmation").

**[TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)**
(MIT, ~9k stars) is the concrete memory implementation that plugs into this: a 4-tier
pipeline — **L0 Conversation → L1 Atom → L2 Scenario → L3 Persona** — with hybrid
BM25 + vector + RRF recall, a local SQLite + sqlite-vec backend (zero external API
dependency), and every intermediate layer stored as inspectable Markdown/SQLite rather
than opaque vector blobs. It has a documented, first-class installation path for
**Hermes Agent specifically** (`hermes-plugin/memory/memory_tencentdb`), not just for
its other host, OpenClaw.

**A naming note, unrelated to the architecture:** you named your reasoning engine
"Hermes" independently — this is a coincidence, not a case of your design having been
based on theirs. Worth knowing so future docs/searches don't conflate the two.

**Sibling project, worth knowing about even though Hermes Agent is the recommendation:**
**[OpenClaw](https://github.com/openclaw/openclaw)** — the non-profit-governed
predecessor Hermes Agent can auto-migrate settings from (`hermes claw migrate`). Same
category (personal AI assistant, local-first, Markdown memory, MIT), broader channel
list (30+ platforms including WhatsApp, Matrix, Feishu, etc.), and it's the *other*
first-class host for TencentDB Agent Memory. If Hermes Agent's Python/agent-loop model
ever turns out to be a worse fit than expected, OpenClaw is the fallback to evaluate
next — not a different tier of option, a close second.

### What adopting this changes, concretely

| Was (build-from-scratch) | Becomes (adopt hermes-agent) |
|---|---|
| `classifier.py`, `planner.py` custom-built (Phase 3) | Hermes Agent's own agent loop + tool-calling; your rule-based escalation logic becomes a thin wrapper, not the whole planner |
| `capability_registry.py`, modules register Python functions | Each module ships as an **MCP server**; Hermes Agent discovers its tools natively — no bespoke registry code to write or maintain |
| Custom Telegram bridge ported from VesperAIOS (Phase 5) | Hermes Agent's built-in multi-platform gateway; VesperAIOS's bridge becomes **read-only reference for command semantics only** (what `/ask /search /people /portfolio /journal` should do), reimplemented as Hermes **skills** |
| `llm_manager.py` with OpenCode Go + Groq fallback, hand-rolled routing | Hermes Agent's native provider system (`hermes model`) configured to point at OpenCode Go/DeepSeek V4 Flash with Groq as a secondary provider; only the complexity-based escalation rule (§14, still an open decision) is custom code |
| `memory/*.py` thin wrappers over Redis/Postgres/LanceDB | Hermes Agent's native memory + the TencentDB Agent Memory plugin for the L0–L3 pyramid and hybrid recall; Postgres/DuckDB/LanceDB remain the systems of record for module data, accessed via each module's MCP server, not re-implemented as a parallel memory layer |
| Notification Engine built from scratch (Phase 6) | Hermes Agent's cron + platform delivery does the "where it goes" half natively; the "what matters" judgment (§11) is still custom logic — either a skill Hermes Agent runs on a schedule, or a standalone worker that calls a module's MCP `notify` capability |
| Automation Engine, APScheduler-based (Phase 7) | **Split by whether the job needs reasoning.** Pure data/quant jobs (`fetch_equity`, `compute_factors`, `paper_trade_eod`, etc.) stay exactly as they are today — plain scheduled Python workers, no LLM in the loop, no reason to route them through an agent. Reasoning jobs (Morning Brief, Evening Review, Knowledge Architect commentary) become Hermes Agent cron-triggered skills that call the relevant MCP tools and synthesize |

### What does *not* change

- The Postgres schemas (§13), DuckDB/Parquet feature store, LanceDB semantic layer,
  and the module business logic itself are unaffected — they're still the systems of
  record; only *how Hermes reaches them* changes (MCP tool call instead of an in-process
  capability-registry call).
- §8's conflict resolutions (Relationship = ProjectVesper wholesale, Finance = Quiver
  wholesale, Journal = vault-backed) are unaffected.
- §10's universal graph, §16's safety boundary (Finance OS read-only from the agent
  side), and §17's feature inventory are unaffected in substance, only in which
  component delivers them (see the table above for what maps where).
- The **event bus (Redis pub/sub) for module-to-module decoupling has no native
  equivalent inside Hermes Agent** — it is an agent loop, not a message router. Keep
  the event bus exactly as designed in §6; Hermes Agent sits *outside* that graph as a
  consumer/producer at the edges (a skill can publish an event after acting; a
  standalone subscriber can hand a summarized event to Hermes Agent as an incoming
  message), not as a node inside it.

### Before committing: one required spike

Hermes Agent bundles a fuller runtime than a bespoke capability-registry service would
(Python 3.11 + Node.js + ripgrep + ffmpeg + `uv`-managed venv, full TUI/skills/subagent
machinery). Against the 4–8GB VPS budget in §15, this needs to be measured, not assumed.
**Phase 0 (coding_prompt.md) now includes installing Hermes Agent on a box matching the
target spec and measuring idle + single-conversation RAM before Phase 3 is written
against it as a foundation.** If it doesn't fit the budget, OpenClaw is the next thing
to measure, and building the bespoke registry remains the fallback of last resort.

---

## 1. Core Principles

1. Simplicity over complexity — question every component; unify or cut it if it doesn't earn its place.
2. One capability, one implementation — no duplicate CRM, no duplicate journal, no duplicate trading view (see §8 conflict resolutions).
3. Local-first wherever possible — Obsidian vault is the source of truth for notes/journal; DuckDB/Parquet for analytics; Postgres for metadata; LanceDB for vectors; TencentDB Agent Memory's SQLite+sqlite-vec for the conversational L0–L3 pyramid.
4. AI orchestrates, it never owns business logic — Hermes plans and calls capabilities (now via MCP); modules execute.
5. Event-driven, not tightly coupled — modules never call each other directly.
6. **Telegram is the primary interface.** The majority of daily interaction happens there, including voice — delivered by Hermes Agent's built-in gateway rather than a bespoke bridge.
7. Web exists mainly for dashboards, graph visualization, analytics, and complex editing/admin.
8. Modules are independently extensible via a manifest (now: an MCP server per module), so future modules (Coding OS/DriftLens, Health OS) slot in without touching Hermes.
9. Prefer open, portable data formats — no vendor lock-in.
10. Optimize for one user, on one 4–8GB VPS, first — pending the RAM spike in §0.

---

## 2. System Overview

```
                    ┌───────────────────────────────────────────┐
                    │              UNIVERSAL INBOX                │
                    │  Telegram text · Telegram voice · CLI ·      │
                    │  Discord/Slack (free, bundled) ·              │
                    │  mobile capture · (future) browser extension │
                    │  — delivered by Hermes Agent's own gateway   │
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
                    ┌───────────────────────────────────────────┐
                    │              HERMES  (= Hermes Agent)        │
                    │  Agent loop → Retrieve Memory (native +       │
                    │  TencentDB Agent Memory) → Plan → Call         │
                    │  Capabilities via MCP (parallel/subagents) →   │
                    │  Assemble Context → Provider-routed LLM call → │
                    │  Respond  (contains NO business logic)         │
                    └───────┬───────────────────────────┬───────────┘
                           │ MCP tool discovery           │ skills call out to
                           ▼                             ▼
        ┌──────────────────────────────┐     ┌───────────────────────┐
        │   MODULES (business logic)     │     │      EVENT BUS          │
        │  each exposed as an MCP server: │◄───►│  (Redis pub/sub —       │
        │  Knowledge · Relationship ·      │     │  Hermes sits OUTSIDE    │
        │  Journal · Study · Hobbies ·      │     │  this graph, at the    │
        │  Calendar/Task · Finance ·         │     │  edges only — §0)      │
        │  Graph                             │     │  JournalCreated,        │
        └──────────────┬───────────────┘     │  PersonUpdated,         │
                       │                       │  TradeExecuted,         │
                       ▼                       │  KnowledgeIndexed,      │
        ┌──────────────────────────────┐        │  ReminderDue, etc.      │
        │   DATA LAYER (§13)              │        └───────────┬───────────┘
        │   Postgres / DuckDB / LanceDB /  │                     │
        │   TencentDB Agent Memory SQLite   │                     ▼
        └──────────────────────────────┘        ┌───────────────────────┐
                                                 │  AUTOMATION             │
        ┌──────────────────────────────┐        │  - data/quant jobs:      │
        │  NOTIFICATION                    │        │    plain scheduled      │
        │  Hermes cron/skill: "what matters"│◄──────│    workers, no LLM      │
        │  Hermes Agent gateway: "which     │        │  - reasoning jobs:      │
        │    channel" (native delivery)     │        │    Hermes Agent cron    │
        └──────────────────────────────┘        └───────────────────────┘

        Web app (Next.js, secondary interface): dashboards, Graph OS
        visualization, analytics, settings/admin, complex editing —
        talks to the same module MCP servers / data layer, not a parallel API.
```

---

## 3. Interfaces

| Interface | Role | Notes |
|---|---|---|
| **Telegram** | Primary | Text + voice, via Hermes Agent's built-in gateway (not a bespoke bridge). |
| **Discord / Slack / WhatsApp / Signal** | Available for free | Hermes Agent's gateway supports these natively from the same process — not part of the original brief, but zero-cost to leave enabled if useful later. |
| **Web** | Secondary | Next.js app for the Graph OS visualization, dashboards, Finance OS terminal/screener, settings, and any editing too complex for chat (e.g. bulk CSV import, detailed strategy config). |
| **CLI** | Tertiary | Hermes Agent's own CLI (`hermes`) doubles as this — a thin custom wrapper is no longer needed unless you want a non-conversational scripting surface. |
| **Mobile capture** | Future | Quick-capture endpoint already exists in ProjectVesper (`POST /capture/quick`) — becomes an Inbox input source via a small MCP tool or direct webhook into Hermes Agent's gateway. |
| **Browser extension** | Future | Placeholder Inbox input source, not built in this pass. |

---

## 4. Universal Inbox & Voice Pipeline

Every input, regardless of source, enters through Hermes Agent's own gateway/inbox —
no custom pipeline needed for ingestion or STT:

```
Input (Telegram/Discord/Slack/voice/CLI)
        ↓
   Hermes Agent Gateway (tags source, transcribes voice natively)
        ↓
   Hermes Agent's agent loop: intent + plan
        ↓
   One or many MCP tool calls (a single voice note can hit
   Journal + Knowledge + Calendar + CRM + Study + Task in one pass,
   via subagents if calls are independent and parallelizable)
        ↓
   Module writes (via its own MCP server) + Event Bus publishes
   (module-side) + Hermes Agent's native reply/notification delivery
```

Concretely: you send a voice note on your commute — "met Priya for coffee, she's
starting a new job at X next month, remind me to follow up in two weeks, and I want to
log today's mood as good." Hermes Agent's plan for that single message: call the
Relationship MCP server's `log_interaction` and `create_reminder` tools, the Journal MCP
server's `write_entry` tool (mood=good), and possibly the Knowledge MCP server's
`link_entity` tool if "Priya" and "X" resolve to vault entities — four tool calls, one
voice note, zero app-switching, no custom voice-pipeline code required.

### 4.1 Universal capture — where an arbitrary "remember this" actually lands

The worked example above is the easy case: explicit dates, a clear mood statement, a
named entity. Most real "remember this" utterances are messier — a book title, a loose
idea, a fact with no obvious home. Route these through one deliberate decision point
rather than leaving it to the agent's turn-to-turn judgment:

```
tool: knowledge.capture(utterance, conversation_context) ->
      { stored_in: "journal" | "vault_note" | "reminder" | "expense" | "workout" |
                   "image_note" | "persona_only",
        ref_id, confidence }
```

**Routing rules, in priority order:**

1. **Explicit date/time attached** ("remind me on the 5th") → Calendar/Reminder,
   unchanged from the worked example above.
2. **Expense-shaped** ("300 on lunch," "spent 150 on the cab") → `journal.log_expense`,
   any time of day, not just during the Daily Journal Questionnaire (§12). Categorize
   against a small fixed taxonomy (Food, Travel/Transport, Shopping, Bills/Utilities,
   Health, Entertainment, Other) — best-effort, default to "Other" rather than
   blocking. Writes to a new `journal.spending` table (`date, amount, category,
   raw_text`) — deliberately allowed to be sparse and inconsistent; some days will have
   nothing, some only partial categorization.
3. **Workout-shaped** ("did legs today," "went for a run") → `journal.log_workout`, any
   time of day, writing to a new `journal.workouts` table (`date, activity,
   muscle_groups[], raw_text`) — this is what makes "how many times did I train legs
   this month" answerable later, not just that day's prose.
4. **Journal-flavored** (mentions today, mood, sent during/right after the Daily
   Journal Questionnaire, or a mood/reflection fragment) → append to today's
   in-progress vault journal entry via the Journal MCP server, per §8.3.
5. **Discrete, nameable idea/fact/reference** (a book title, a standalone idea, a fact
   that isn't about today) → a vault note via the Knowledge MCP server, auto-titled and
   handed to the reactive Knowledge Architect tier (§9) for tagging/linking.
6. **Image attachment** → save the original file to the vault's `attachments/` folder;
   analyze via Hermes Agent's native vision handling (main model if it supports vision,
   otherwise the `auxiliary.vision` provider, §14) and create a linked note embedding
   the image with the description as searchable text.
7. **Genuinely ambiguous between 4 and 5** → default to append to today's journal entry
   (cheapest to move later, least likely to become an orphaned note) and flag it for
   the nightly Knowledge Architect batch to reconsider — the re-filing judgment happens
   offline, cheap-tier, never blocking the interactive turn.
8. **In every case**, also mirror the raw utterance as an L1 Atom in TencentDB Agent
   Memory (§7) — a redundant recall path regardless of which "durable" store won above.

Log every routing decision (utterance, chosen store, confidence, which rule fired) to
`hermes.capture_routing_log` (§7) — this is what makes "where did this actually go"
auditable in bulk if a rule turns out to be miscalibrated, rather than something you'd
have to spelunk for by hand.

**Correction and forgetting**: add `update_note`/`delete_note` (Knowledge) and
`update_entry`/`resolve` (Journal) tools, routed from "forget X" / "actually, scratch
that" phrasing through the same intent-detection path. Deliberately **lighter-weight**
than §16's CRM/Finance approval gate — see §16's note-correction carve-out.

**Unified recall**: a further tool, `knowledge.recall_everything(query) -> results`,
fans out in parallel to LanceDB vault search, Postgres full-text search over
`diary_entries`/notes, and TencentDB Agent Memory's own recall (currently keyword/BM25
— see §7's revision note), merging and deduplicating by content similarity. This is
the tool Hermes reaches for on "what have I told you about X" phrasing, rather than
only checking whichever single store its default retrieval path happens to hit.

---

## 5. Hermes — The Cognitive Engine (now: adopted, not built)

Hermes = **NousResearch/hermes-agent**, configured (not written) for this system. Its
job, same as originally scoped, is to contain **no domain logic** — only:

1. **Retrieve Memory** — Hermes Agent's native memory (curated, nudged, FTS5-searchable)
   plus the TencentDB Agent Memory plugin's L0–L3 pyramid for persona-level recall,
   pulled before planning, not after.
2. **Plan** — Hermes Agent's own agent loop, augmented by a thin custom rule (§14) for
   when to escalate off the default cheap model.
3. **Call Capabilities via MCP** — never a direct REST call, never a direct module
   import. Each module runs as an MCP server exposing tools such as:
   ```
   tool: relationship.search(query) -> results
   tool: relationship.create_interaction(person, note, date) -> interaction_id
   tool: journal.write_entry(text, mood, source) -> entry_id
   tool: finance.portfolio_summary(strategy?) -> summary
   tool: knowledge.answer(question) -> answer + sources
   tool: automation.schedule(job, when) -> job_id
   ```
   (This is the same capability contract as the original plan — only the transport is
   now MCP as the primary path, not a fallback.)
4. **Assemble Context** — merge MCP tool results into one context window, respecting
   boundaries (Finance OS returns summaries only — see §16 safety).
5. **Provider-routed LLM call** — configured via Hermes Agent's own provider system
   (`hermes model`), pointed at OpenCode Go/DeepSeek V4 Flash by default with Groq as
   secondary; see §14 for the one remaining custom piece (escalation thresholds).
6. **Respond + fan out** — reply on the interface the request came from (native to
   Hermes Agent's gateway); anything a module needs to publish to the event bus is
   published by the module itself, on the same write, not by Hermes.

The **only new code this system needs to write** for Hermes's own operation is: (a) one
MCP server per module (Phase 4), (b) the model-escalation rule (§14), and (c) any custom
skills that reproduce VesperAIOS's existing Telegram command semantics
(`/ask /search /people /portfolio /journal`, extended with `/study` and `/calendar`).
Everything else — the loop itself, memory, gateway, cron, subagents — is Hermes Agent,
unmodified upstream, configured downstream.

---

## 6. Event Catalog

Unchanged from the original design. Modules never call each other directly. They
publish; the Event Bus (Redis pub/sub) delivers to whoever subscribed — the Automation
Engine, another module's own reactive handler, or (at the edges only, never as a graph
node — see §0) a Hermes Agent skill that turns a batch of events into a natural-language
notification.

| Event | Published by | Typical subscribers |
|---|---|---|
| `JournalCreated` | Journal | Knowledge (link entities), Automation (streak update) |
| `PersonUpdated` | Relationship | Graph (recompute edges), Notification (if health-score crossed threshold) |
| `InteractionLogged` | Relationship | Graph, Timeline, Automation (reminder recalculation) |
| `TradeExecuted` | Finance | Timeline, Notification (if circuit-breaker or large move) |
| `PortfolioNAVUpdated` | Finance | Automation (daily brief data), Notification |
| `KnowledgeIndexed` | Knowledge | Graph, nightly Knowledge Architect batch (§9) |
| `ReminderDue` | Automation | Notification |
| `CalendarEventCreated` | Calendar | Notification, Timeline |
| `StudyCompleted` | Study | Automation (exam-readiness commentary trigger), Timeline |
| `KnowledgeArchitectPassCompleted` | Automation (nightly worker) | Knowledge (structure refresh notice) |
| `DailyJournalCompleted` | Daily Journal Questionnaire job (§12) | Evening Review (§12, event-driven trigger + scheduled fallback) |

Every module's MCP server manifest declares which events it publishes and which it
subscribes to (replacing the earlier `module.yaml` publishes/subscribes fields
one-for-one) — this is the extensibility contract for future modules.

---

## 7. Memory Architecture

| Layer | Contents | Backing tech |
|---|---|---|
| **Working memory** | Current conversation, in-flight plan state | Hermes Agent's native session state |
| **Conversational memory pyramid (new)** | L0 raw conversation → L1 atomic facts → L2 scene blocks → L3 persona | **TencentDB Agent Memory** plugin — SQLite-backed, every layer inspectable as Markdown/SQLite. **Revised from the original design** (see note below): current upstream requires a Node.js Gateway sidecar with its own LLM credentials, not a zero-dependency embedded library, and recall is currently **keyword/BM25 only** — hybrid vector recall needs an EmbeddingService this deployment doesn't have configured yet. |
| **Persistent memory** | Obsidian vault (notes/journal source-of-truth), CRM, calendar | Obsidian vault files + Postgres |
| **Semantic memory** | Embeddings, vector search, entity relationships over module data | LanceDB (embedded) + Postgres graph tables (§10) |
| **Procedural memory** | Automations, routines, workflows, and — deliberately — Quiver's trading **strategies** (a strategy config is a procedure, not a fact) | Postgres (`automation` schema) + Quiver's existing strategy config files; Hermes Agent's own skill system for anything that's a *reasoning* procedure rather than a deterministic job |

The conversational pyramid (new row) is specifically what TencentDB Agent Memory adds
over the original design: instead of a flat log of everything Hermes has ever been told,
it distills conversation into atomic facts, then scene-level context, then a
day-to-day persona — with a deterministic drill-down path back to the original
conversation for verification, never an irreversible summary. This is a good match for
§9's Knowledge Architect goal (structure the system maintains, not something you
hand-manage).

**Revision, confirmed during Phase 3 implementation:** the plugin's upstream has moved
to a "team memory hub" architecture since this plan was first written. The lightweight
Hermes-Agent plugin still exists and still installs the way §0 describes, but it now
runs a small Node.js Gateway process (LLM-resolver pattern, accepts any OpenAI-compatible
`base_url`) rather than being a pure embedded SQLite library — so "costs nothing extra
to run" now means "one more small local process," not "zero moving parts." Point the
Gateway's LLM at whatever this deployment's primary provider is (§14) via env vars
(`TDAI_LLM_BASE_URL`/`_MODEL`/`_API_KEY`) so it stays API-ready rather than hand-tuned
to a specific local model. Recall defaults to keyword/BM25 (`recall.strategy: keyword`)
until an EmbeddingService is wired up for the hybrid mode this plan originally assumed —
track that as an explicit follow-up, not a silent gap: `knowledge.recall_everything`
(addendum-derived, §7 below) is weaker without it, since one of its three fan-out
sources is running in a degraded mode.

Hermes queries whichever layers are relevant to the current intent rather than always
hitting all four.

Two new lightweight tables live alongside this layer, added for the Daily Journal
Questionnaire (§9 below): `journal.workouts` (`date, activity, muscle_groups[],
raw_text`) and `journal.spending` (`date, amount, category, raw_text`), plus
`hermes.capture_routing_log` (utterance, chosen store, confidence, which rule fired) —
the audit trail for the capture-routing decisions in §4.

---

## 8. Modules & Conflict Resolutions

These decisions still hold under the new framing:

1. **Relationship OS = ProjectVesper's implementation, wholesale.** Re-exposed as an MCP
   server whose tools (`search`, `create_interaction`, `person_detail`, `graph`,
   `suggested`) point at ProjectVesper's real tables and logic. VesperAIOS's basic CRM
   (8 contacts, no graph) is read for reference during Phase 1 inventory, then dropped.
2. **Finance OS = Quiver's implementation, wholesale.** Same pattern — re-exposed as an
   MCP server backed by Quiver's actual paper trader, backtester, and 8 portfolios.
3. **Journal = vault-backed, not DB-backed.** ProjectVesper's `diary_entries` table
   (mood, streak, calendar UI) becomes a **metadata layer over vault notes**, not the
   content owner. One write path for both typed and voice-dictated entries: Hermes
   writes the markdown note to the vault via the Journal MCP server; a sync handler
   (subscribed to `KnowledgeIndexed`/vault-watch) creates or updates the corresponding
   `diary_entries` row. The `/diary` page's UI (calendar, moods, streaks) is unchanged.
4. **Telegram interaction = Hermes Agent's native gateway, not a ported bridge.**
   VesperAIOS's existing bridge is now **reference-only**: its command handlers
   (`/ask /search /people /portfolio /journal`) describe the *behavior* to reproduce as
   Hermes Agent skills, extended with `/study` and `/calendar` for parity.
5. **Knowledge OS = VesperAIOS's vault indexing, upgraded** with the Knowledge Architect
   behavior in §9, LanceDB for entity/semantic search (settled, no standing vector-DB
   container beyond it), and TencentDB Agent Memory for the conversational pyramid layer
   specifically (these are two different kinds of "memory" — vault-entity semantic
   search vs. conversation-about-you persona modeling — and don't compete).

---

## 9. Hermes as Continuous Knowledge Architect

Hermes does not just retrieve knowledge — it maintains the structure the knowledge
lives in. Two tiers of work, deliberately kept apart so the heavy tier never blocks an
interactive request:

- **Reactive, on every `KnowledgeIndexed` event** (light, in-process): auto-categorize
  the new/changed note, suggest links to existing entities, apply consistent tagging —
  either a lightweight Hermes Agent skill or module-side logic, whichever proves
  cheaper; decide during Phase 4 once real latency numbers exist.
- **Nightly batch, as a scheduled data job** (`knowledge_architect_pass`, no LLM
  reasoning required for the mechanical parts): deduplicate near-identical notes, merge
  fragmented ideas, split overly dense ones, recompute semantic clusters and topic
  hierarchies, and **reconsider anything §4.1's capture routing flagged as ambiguous**
  (defaulted into today's journal entry but structurally more like a standalone note —
  a book title, a discrete idea) for re-filing. Where genuine judgment is needed (is
  this really a duplicate, or two related-but-distinct ideas? does this fragment belong
  in the journal or as its own note?), that step calls into Hermes Agent as a
  cron-triggered skill; the rest is plain scheduled Python, per §0's
  data-vs-reasoning split.

Structure (tags, clusters, hierarchy) is a *view Hermes maintains*, not something you
hand-manage.

---

## 10. Universal Intelligence Graph

Unchanged from the original design:

- Generic `graph_nodes(id, entity_type, ref_table, ref_id, label, metadata)` and
  `graph_edges(source_id, target_id, edge_type, weight, metadata)` tables in Postgres.
- Every domain table gets a thin adapter that registers/updates its rows as graph nodes
  on write (via the event bus — e.g. `PersonUpdated` → upsert node).
- ProjectVesper's existing graph algorithms (Louvain community detection, betweenness
  centrality, structural-hole finder) now run over the general graph, not just the
  person subgraph.
- **The Graph OS page stays the flagship People view by default** — other entity types
  are togglable overlays, not a redesign of the visual product already spec'd.
- Launch scope unchanged: people + notes + stocks/holdings + tasks first (§19.2).

---

## 11. Notification Engine

- **"What matters" (Hermes's judgment)** — e.g. "NAV dropped 4% today" or "Priya's
  birthday is tomorrow" is worth surfacing; a routine NAV update at +0.1% is not. This
  logic lives either as a Hermes Agent skill triggered on a schedule, or as a standalone
  worker calling a module's MCP `notify` capability for the common, simple-rule cases —
  keep the common cases as rule checks, not an LLM call every time an event fires (same
  principle as the original design, unchanged).
- **"Which channel" (delivery)** — Hermes Agent's native gateway delivers to
  Telegram/Discord/Slack directly; ntfy (free `ntfy.sh`, no self-hosted server) and a
  web in-app list remain as additional channels for anything that shouldn't go through
  a conversational agent turn (e.g. a raw push notification with no reply expected).
- Modules never push notifications directly; they publish events, the notification
  logic triages, delivery happens through the appropriate channel.
- **Anti-nagging policy for loose-intent reminders**: a captured note with reminder-like
  intent but no explicit date/time ("sometime this month, no rush" — §4.1's routing
  rule 1 didn't fire) does **not** go on the daily notification surface. It surfaces
  only in the Weekly Review job's synthesis (§12), or on direct request ("what have I
  been meaning to do?"). Explicit, dated reminders are unaffected and behave as today.
  This exists specifically so the second-brain capture work in §4.1 doesn't turn into a
  daily nag once undated notes start accumulating reminder-like content.

---

## 12. Automation Engine

Split explicitly by whether a job needs reasoning (per §0):

| Job | Trigger | Mechanism | Absorbs |
|---|---|---|---|
| Morning Brief | 07:30 IST | Hermes Agent cron → skill (needs synthesis) | Cross-module summary: NAV deltas, due/cold contacts, journal streak, study progress; also offers to backfill an incomplete prior-day journal entry (§12.1) |
| **Daily Journal Questionnaire** | 21:30 IST, escalating retries, 23:55 hard deadline (§12.1) | Hermes Agent cron → skill (needs synthesis for the dynamic follow-ups) | The full nightly journaling ritual — see §12.1 for the complete spec |
| Evening Review | **event (`DailyJournalCompleted`) + scheduled fallback** | Hermes Agent cron → skill | Day's interactions, trades, journal entry check-in — now reads that day's actual completed journal content instead of running on its own clock |
| Weekly / Monthly Review | scheduled | Hermes Agent cron → skill | Rollup of the above at longer horizons; surfaces loose-intent reminders that never got a date (§11's anti-nagging policy) |
| Market Jobs | scheduled (IST), plain workers | No LLM needed | Quiver's existing `fetch_equity` 06:00, `compute_factors` 06:30, `fetch_macro` 07:00, `update_universe` 07:30, `paper_trade_eod` at **17:00 IST weekdays**, covering all 4 traders |
| Portfolio Refresh | event (`TradeExecuted`) + scheduled fallback, plain worker | No LLM needed | Quiver's 8 model portfolios |
| Knowledge Sync | event (vault file change), plain worker | Mechanical part, no LLM | Reactive tier of §9 |
| Knowledge Architect Pass | nightly, plain worker + Hermes Agent skill for judgment calls | Split per §9 | Batch tier of §9, including re-filing ambiguous captures from §4.1 |
| CRM Follow-ups | event (`ReminderDue`) + scheduled sweep, plain worker | No LLM needed | ProjectVesper's existing reminder cron logic |
| RSS Processing | scheduled (weekly), plain worker | No LLM needed | ProjectVesper's RSS fetcher |
| Graph Analytics | scheduled (nightly), plain worker | No LLM needed | Louvain/betweenness/structural-hole, now over the universal graph |
| Reminder Processing | event-driven, plain worker | No LLM needed | dispatches to Notification Engine |
| **Vault Backup & Publish** | daily, 00:15 IST, plain worker | No LLM needed | `git push` the vault to a private GitHub repo; rebuild the Quartz static site; refresh the Caddy-served copy (§15) |

The pure-data jobs are **unchanged from the original design** — they were never going to
benefit from being routed through an agent, and keeping them as plain scheduled Python
avoids paying an LLM-call cost (and Hermes Agent's runtime overhead) for work that's
purely mechanical.

### 12.1 Daily Journal Questionnaire — the concrete nightly ritual

Fires at **21:30 IST**, skipping if today's `diary_entries` row is already marked
`complete = true`. Fixed questions, in order (store as a versioned config,
`hermes-config/cron/daily_journal_questions.yaml`, not hardcoded):

1. Conditional opener: "How was your day in office?" (weekday, Mon–Fri IST) or "How was
   your day?" (otherwise).
2. "Any major accomplishments or tasks you completed today?"
3. "What did you learn today — and where do you plan to (or already did) apply it?"
4. "Any specific reminders you want me to hold onto for the future, based on today?"
5. "Did you work out today? If so, what did you do, and which muscle groups did you
   target?" → `journal.log_workout` (§4.1).
6. "What did you spend today?" → `journal.log_expense`, summed and categorized, read
   back for confirmation (§4.1). Accept "nothing"/"not tracking" gracefully — must never
   block completion.
7. "How would you rate your energy or mood today, and what mainly influenced it?" →
   `diary_entries.mood`.
8. "Did you connect with anyone worth logging today — anyone I should update in your
   contacts?" → `knowledge.link_entity` if a person is named.
9. "Anything on your mind about tomorrow?" → context for the next Morning Brief.

Then **4–5 dynamic follow-ups**, generated from that day's specific answers (a named
project, a person, an emotion) — this step should explicitly invoke §14's
model-escalation rule rather than run on the default tier.

**Turn-taking**: group related questions into fewer conversational round-trips (e.g.
workout + spending together, mood + connections + tomorrow together) rather than nine
separate back-and-forths — the fixed *content* above stays as specified, only the
grouping changes. Consider a **"quick mode"** that runs only questions 1–4 and 6 and
skips the dynamic follow-ups, for busy nights.

**Postponement**: "not now"/"busy" (or going quiet mid-questionnaire) triggers a retry
at 22:15, then 23:00, then a final urgent retry at 23:40 offering a 60-second shortcut
(questions 1 and 4 only). Never interrupt an active conversation to fire a retry.
Abandoned mid-way → resume from the last-answered question on the next retry, not from
the start.

**Hard deadline**: **23:55 IST**. If still incomplete, write a placeholder
`diary_entries` row (`complete = false`, whatever partial answers already exist —
persisted per-answer as they arrive, never batched) rather than ending the day with
nothing recorded. No nudges between the cutoff and the next morning. The following
Morning Brief offers a backfill, dated to the prior day.

On completion (full or placeholder), publish `DailyJournalCompleted` (§6) — this is
what Evening Review above now waits on.

---

## 13. Data Layer

| Store | Owns | Migrated from |
|---|---|---|
| Obsidian vault (markdown) | Notes, journal content (source of truth) | VesperAIOS's existing vault integration |
| Postgres, schema `relationship` | 19 ProjectVesper tables, unchanged | ProjectVesper's Supabase Postgres |
| Postgres, schema `journal` | `diary_entries` as metadata layer (§8.3) | ProjectVesper's Supabase Postgres |
| Postgres, schema `study` | tests, mock_tests | ProjectVesper's Supabase Postgres |
| Postgres, schema `finance` | paper trading state, job runs, experiments | Quiver's SQLite |
| Postgres, schema `graph` | universal `graph_nodes`/`graph_edges` (§10) | new |
| Postgres, schema `hermes` | MCP tool-call audit trail, LLM usage/cost (Hermes Agent's own logs, mirrored here for cross-module reporting) | new |
| DuckDB + Parquet | Quiver's feature store (partitioned by symbol/factor) | unchanged — stays exactly as-is, embedded, zero standing cost when idle |
| LanceDB (embedded) | Vector embeddings for module-entity semantic memory | KnowledgeEngine's existing LanceDB usage |
| TencentDB Agent Memory (SQLite, Node Gateway sidecar) | Conversational L0–L3 pyramid, keyword/BM25 recall (hybrid pending EmbeddingService — §7) | new — Hermes Agent plugin, local SQLite store, one small local Gateway process |
| Redis | Working memory, event bus, response/embedding cache | new |
| **MCP servers (new layer)** | One per module — the interface Hermes Agent actually calls; thin, stateless, translates MCP tool calls into reads/writes against the stores above | new |

Self-hosted Postgres, not Supabase — both your Supabase free-tier project slots are
already used elsewhere, and self-hosting was already the plan.

---

## 14. Compute Strategy & Model Routing

- **Provider routing**: configured through Hermes Agent's own provider system
  (`hermes model`), not hand-rolled. Primary is OpenCode Go / DeepSeek V4 Flash.
- **Fallback chain is a deliberate design decision, not a workaround** — formalized
  here after Phase 3 verification confirmed it end-to-end: **OpenCode Go
  (`deepseek-v4-flash`) → local Ollama (`llama3.2` — verified reliable for plain text
  completion; `qwen3.5:4b` is a reasoning model that leaves `content` empty on
  extraction-style calls, so don't use it where structured JSON output is required) →
  Groq (`llama-3.1-8b-instant`, requires `GROQ_API_KEY` to be set — currently isn't;
  the fallback resolves but fails until it is)**. OpenCode Go carries real operational
  risk on its own — a weekly usage cap and a region gate that can both fire
  independently — so a system meant to run daily needs this chain regardless of how
  reliable the primary provider normally is. Configure via Hermes Agent's
  `fallback_providers` (`~/.hermes/config.yaml`), not custom retry code.
- **`auxiliary.vision`** (image handling, `plan.md`-derived from the second-brain work):
  `provider: custom`, `model: kimi-k2.5`, `base_url: https://opencode.ai/zen/go/v1`,
  `api_key: ${OPENCODE_GO_API_KEY}` — use the `${VAR}` expansion form specifically; the
  auxiliary-provider resolver does not honor an `api_key_env` shortcut the way the main
  provider config might elsewhere. This is a separate, single-purpose provider slot,
  not part of the fallback chain above.
- **Model-escalation rule** — the one piece of custom logic in this layer: escalate to
  a stronger tier if assembled context exceeds ~40,000 tokens, or if the capability
  category is `analyze` on `finance`/`study` (verified via direct invocation against
  all four cases: normal turn stays on default, long-context and finance/study-analyze
  both escalate, hobbies-analyze correctly does not). Implemented as one small,
  clearly-labeled function (`hermes-config/model_escalation.py`), not folded into a
  general planner — this was flagged as an open decision in the original plan and is
  now resolved with these thresholds as the first-pass answer; revisit if they prove
  too aggressive or too lax in practice.
- **Local models are now real, load-bearing infrastructure, not a theoretical
  fallback** — this is a correction to the original design, which assumed "no
  always-on large models in memory, every tier is an API call." Ollama running
  `llama3.2`/`qwen3.5:4b` locally is part of the verified, working system. **Confirm
  Ollama's idle-unload behavior is configured** (models unload after a period of
  inactivity rather than staying resident indefinitely) so this fallback doesn't
  silently become a permanent RAM cost on top of the budget in §15 — it should only
  cost RAM while it's actually in use, covering an OpenCode Go outage.
- **Aggressive caching** — Redis caches embeddings and any module-side LLM calls (e.g.
  Knowledge Architect batch judgments) keyed by content hash. Hermes Agent's own
  provider layer handles conversational-turn caching internally.
- **Ephemeral workers, not always-on services** — indexing, backtesting, graph
  analytics, research, and the mechanical half of summarization batches run as
  short-lived worker processes triggered by schedule or event, never as a resident
  service competing with Hermes Agent for RAM.
- **Modular monolith for the data-layer half** — one codebase, multiple entrypoints
  (`api`, `worker`) for the module MCP servers and web backend; Hermes Agent itself runs
  as its own process (its own packaging, not folded into this monolith).

---

## 15. Infra & Container Topology

Ubuntu 24.04, Docker Compose. Container roles, updated for the adopted-Hermes model:

| Container | Role | Always-on? | Approx. steady-state RAM |
|---|---|---|---|
| `postgres` | relational store, all schemas | yes | ~350–450MB |
| `redis` | event bus, working memory, cache (`maxmemory 160mb`, `allkeys-lru`) | yes | ~130–160MB |
| `caddy` | HTTPS + reverse proxy for the web app | yes | ~25–40MB |
| `vesper-api` | Next.js (static-exported) served by Caddy + module MCP servers for the web dashboard | yes, 1 worker | ~400–600MB |
| `hermes-agent` (replaces `vesper-bot`) | Hermes Agent itself — gateway, agent loop, native memory, TencentDB Agent Memory plugin, cron | yes | **~300MB–600MB chat-only, up to ~1–2GB with the browser tool or heavy skill/MCP load — see note below and §0's required spike before treating this as final** |
| `vesper-worker` | ephemeral: pure-data market jobs, mechanical knowledge-architect pass, graph analytics, backtests, vault publish (§12) | triggered only | transient, isolated so it can't inflate steady-state RAM |
| `ollama` (local fallback, §14) | `llama3.2`, on standby for provider outages | conditional — **must be configured to unload idle models**, not resident | ~0 when idle if unload is configured correctly; ~2–4GB while actively covering an outage — confirm this is transient before trusting the total below |

**Steady-state total: a reasonable estimate is now ~1.5–3GB**, combining this table's
postgres/redis/caddy/vesper-api figures (~0.9–1.2GB) with Hermes Agent's own published
range above — independent testing and Hermes Agent's own docs converge on "comfortable
on 2–4GB dedicated to the agent alone for daily multi-channel use," which is consistent
with, not a contradiction of, the original ~1.2–1.7GB estimate once you separate what
Hermes Agent itself needs from the rest of the stack. **This assumes Ollama is idle
most of the time** (§14) — if idle-unload isn't actually configured, add its resident
footprint to the steady-state total, not just the burst total. Budget for **8GB as the
comfortable target**; **4GB is plausible but tight** — there's little margin left for
burst overlap (a nightly Knowledge Architect pass or the vault-publish job landing
during an active conversation, or Ollama staying warm longer than expected) once you're
near the top of the estimated range above.

Long-polling (not webhooks) for Telegram if Hermes Agent's gateway supports that mode
for your chosen platforms, so no public bot endpoint is needed — admin/web surfaces stay
behind Tailscale as before. Swapfile (2–4GB) remains as a burst safety net.

**Second-brain viewer**: the vault gets pushed daily to a **private** GitHub repo (free,
unlimited — the durable backup and the "read any note from my phone via GitHub's own
app" surface, zero extra tooling) and built locally with **Quartz** (free, open-source,
purpose-built for Markdown/Obsidian vaults — full graph view, backlinks, wikilinks) as
part of the same `vesper-worker` job (§12), *not* via GitHub Pages — the vault holds
journal/CRM content that shouldn't be public. Serve the built static output through the
existing `caddy` container at an internal-only hostname, behind Tailscale. This is not a
new always-on container — it's a static file directory Caddy already serving other
traffic can also serve, refreshed once a day.

---

## 16. Security

- Hermes Agent becomes the primary attack surface once it's the primary interface —
  restrict to your identity via its `approvals` block, in addition to (not instead of)
  `TELEGRAM_ALLOWED_USERS`-style allowlisting. **Verified working configuration**
  (`~/.hermes/config.yaml`): `mode: manual`, `timeout: 60`, `cron_mode: deny`,
  `mcp_reload_confirm: true`, `destructive_slash_confirm: true` — confirmed by
  deliberately asking Hermes to run a destructive shell command twice and having it
  refuse both times. `hermes pairing list` is the DM-pairing check; no pairing codes
  are needed until a second messaging platform beyond Telegram is added.
- Note-level corrections and deletes (§4, second-brain capture work) are deliberately
  **not** gated the same way — the approvals block above governs destructive
  shell/tool calls and Finance/CRM writes; a "forget that note" or "update this journal
  entry" request should go through without the same friction, since it's a
  high-frequency, low-stakes action and gating it would make the system's most-used
  feature annoying to use.
- Single JWT-based auth for the web app (reuse ProjectVesper's `SECRET_KEY` pattern)
  instead of separate credentials per module.
- Finance OS stays read-only from the agent/MCP side; the worker/scheduler is the only
  writer. **This is enforced at two layers, not one**: the `approvals` block above
  (no destructive tool call without explicit confirmation) *and* the Finance MCP server
  itself refusing to expose any write/execute tool — defense in depth, since you're
  trusting an upstream project's approval system for something with real financial
  consequences.
- Full audit trail: Hermes Agent's own tool-call logs, mirrored into the `hermes`
  Postgres schema for cross-module reporting (§13).
- **VPS provider choice matters less than configuration hygiene.** Any reputable
  provider (Contabo, Hetzner, DigitalOcean, and similar all clear this bar per
  independent review evidence as of mid-2026) is a reasonable choice for this
  workload — what actually determines whether personal journal/CRM/finance data is
  safe on it is Tailscale-gated admin access, SSH keys (not passwords), the Telegram
  allowlist above, `fail2ban`, and staying current on `apt` security updates, all of
  which this section already specifies regardless of vendor.

---

## 17. Complete Feature Inventory (nothing dropped)

| Feature | Source | Primary surface now |
|---|---|---|
| Graph OS (force-graph, Replay, radial layout) | ProjectVesper | Web (flagship page) |
| CRM search/lookup, meeting prep, health insights | ProjectVesper | Hermes Agent (`/people` skill) + Web |
| Journal (typed + voice), mood, streaks, calendar | ProjectVesper UI + VesperAIOS vault | Hermes Agent (voice) + Web (calendar view) |
| Study OS (mock tests, percentiles, exam readiness) | ProjectVesper | Hermes Agent (`/study` skill) + Web |
| Hobby tracker | ProjectVesper | Web |
| Calendar (birthdays, interactions, exam dates, market dates) | ProjectVesper + Quiver | Hermes Agent (`/calendar` skill) + Web |
| Portfolio/strategies, screener, paper trading, AI research assistant | Quiver | Hermes Agent (`/portfolio` skill) + Web (terminal/screener) |
| Vault search, entity Q&A | VesperAIOS | Hermes Agent (`/search`, `/ask` skills) + Web |
| Command palette (⌘K) | Quiver (planned) | Web only (not a Telegram concept) |
| Push notifications | ProjectVesper | Hermes Agent native delivery + ntfy |
| Daily brief / reviews | new, cross-module | Hermes Agent, delivered proactively via cron |
| Conversational memory / persona | new | TencentDB Agent Memory plugin |
| Daily Journal Questionnaire (workout, spending, mood, connections + dynamic follow-ups) | new, §12.1 | Hermes Agent, proactive 21:30 IST |
| Workout & spending logs | new, §4.1 | `journal.workouts`/`journal.spending`, queryable via Hermes Agent or Web |
| Image capture (photos → vault notes) | new, §4.1/§14 | Hermes Agent (native vision or `auxiliary.vision`) |
| Second-brain viewer (private GitHub + graph view) | new, §15 | Quartz, self-hosted behind Tailscale |

---

## 18. Phased Build Order

Mirrors `coding_prompt.md` — see that file for the operational version, now including
the Phase 0 RAM spike ahead of everything else.

| Phase | Outcome |
|---|---|
| 0 | Inventory the three real codebases + install Hermes Agent and measure its footprint against the target VPS spec; produce `INVENTORY.md` |
| 1 | Scaffold the new single repo (module MCP servers + web app); Docker Compose skeleton |
| 2 | Data layer: Postgres schemas, DuckDB carryover, LanceDB, Redis, TencentDB Agent Memory |
| 3 | Configure Hermes Agent (provider, model-escalation rule, skills scaffolding) — no capability registry to build |
| 4 | Event bus + port each module's business logic, each wrapped as an MCP server |
| 5 | Configure Hermes Agent's gateway for Telegram (+ any other platforms); write skills reproducing VesperAIOS's command semantics; voice pipeline is native, not built |
| 6 | Notification "what matters" logic (skill or worker) on top of Hermes Agent's native delivery |
| 7 | Automation: plain workers for data jobs, Hermes Agent cron skills for reasoning jobs |
| 8 | Web frontend (Next.js), pages ported in the order in `coding_prompt.md` |
| 9 | Universal graph layer over all entity types |
| 10 | Integration testing, resource audit against the (now re-measured) §15 estimate, final cleanup |

---

## 19. Remaining Open Decisions

1. **Model-routing thresholds** — what counts as "complex enough" to escalate off
   DeepSeek V4 Flash needs a first-pass heuristic — worth deciding once Phase 3 is
   underway rather than guessing now (unchanged from the original plan).
2. **Universal graph node types to launch with** — launch with people + notes +
   stocks/holdings + tasks (unchanged).
3. **Hermes Agent RAM footprint vs. the 4–8GB budget** — new, and blocking: run the
   Phase 0 spike before treating §15's container topology as final. If it doesn't fit,
   evaluate OpenClaw next, then fall back to the original from-scratch capability
   registry only if neither fits.
4. **Reactive Knowledge Architect tier (§9): skill vs. module-side logic** — decide once
   Phase 4 gives real latency numbers for calling out to Hermes Agent per-note versus
   handling simple categorization in the module itself.

---

## 20. Recommended Additional Open-Source Components

- **[TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)**
  (MIT) — adopted directly, see §0/§7/§13. **Correction from initial evaluation,
  confirmed during Phase 3 implementation**: this is not zero-external-dependency —
  current upstream runs a small local Node.js Gateway sidecar with its own LLM
  credentials (point it at whatever provider §14 configures). Recall is keyword/BM25
  by default; hybrid vector recall needs an EmbeddingService not yet wired up.
- **[Honcho](https://github.com/plastic-labs/honcho)** — dialectic user-modeling library
  already used inside Hermes Agent's own persona layer; worth knowing about directly if
  you ever want to tune persona-building behavior rather than take Hermes Agent's
  default, but not something to integrate separately — it's already in the dependency
  chain via Hermes Agent.
- **sqlite-vec** — the vector backend TencentDB Agent Memory's docs describe using
  locally; worth knowing it exists as a lighter-weight alternative to LanceDB if
  LanceDB's footprint ever becomes a concern, though LanceDB remains settled for the
  module-entity semantic layer (§8.5).
- **[Quartz](https://quartz.jzhao.xyz/)** (MIT-family, open-source) — free static-site
  generator purpose-built for Markdown/Obsidian vaults, with graph view, backlinks, and
  wikilinks out of the box. Used for the second-brain viewer in §15 — self-hosted
  behind Tailscale rather than its own default GitHub Pages path, since the vault holds
  private content.

## 21. Other "Hermes-as-brain" Projects Surveyed

| Project | Fit | Verdict |
|---|---|---|
| **NousResearch/hermes-agent** | Near-exact match for the cognitive-engine role (§0) | **Recommended** — see above |
| **OpenClaw** | Same category, broader channel list, non-profit-governed, same TencentDB Agent Memory support | Strong fallback if the Hermes Agent spike fails the RAM budget |
| Generic "AI second brain" templates (Obsidian-plugin-based, Claude-Code-skill-based) | Solve knowledge-vault organization only, not multi-module orchestration, cron, gateway, or MCP | Not a fit for the Hermes role — no orchestration/automation/multi-channel layer; some (e.g. the PARA/CODE-method vault conventions some of these enforce) could still inform Knowledge OS's tagging conventions if useful later |