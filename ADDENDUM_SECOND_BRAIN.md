# Addendum — Universal Capture & Second-Brain Recall

**Addressed to:** the coding agent building/maintaining Vesper.

**Status:** this is a gap-fill addendum, not a replacement for `plan.md` or
`coding_prompt.md`. Everything here slots into the existing architecture — mostly
§4/§6/§7/§9/§12/§14/§15/§16 of `plan.md` and Phases 1/4/5/7/10 of `coding_prompt.md` —
rather than introducing a parallel system. §11 maps every piece to its exact home if
you fold this back in permanently. Covers: capture routing (§1), the Daily Journal
Questionnaire including workout/spending logging (§2), unified recall (§3),
correction/forgetting (§4), anti-nagging (§5), durability (§6), vault publishing to a
private GitHub repo + a self-hosted graph view (§7), image/vision capture (§8), a
one-command bootstrap script (§9), and infra sizing (§10).

## Why this addendum exists

`plan.md` already has real infrastructure for personal note-taking: the vault-backed
Journal module (§8.3), Knowledge OS with a reactive + nightly Knowledge Architect (§9),
and the TencentDB Agent Memory conversational pyramid (§7). What it does **not** specify
explicitly is the behavior that actually makes those add up to "a second brain that
understands, reminds, and learns from everything I say" — specifically:

1. No defined rule for *which store* an arbitrary "remember this" utterance should land
   in, so the agent's own judgment decides turn-to-turn, with no consistency guarantee
   and no audit trail of the decision.
2. No proactive end-of-day journal prompt — "Evening Review" (§12) is scoped as a
   read-and-summarize job, not "ask me if I haven't journaled yet."
3. No single recall path that searches across the vault, Postgres, and the TencentDB
   Agent Memory pyramid at once — three separate search surfaces, no merge.
4. No forget/correct/update semantics for a note once captured.
5. No explicit durability guarantee — nothing currently rules out a capture path that
   only lives in an in-process buffer and evaporates on restart.
6. No policy preventing loose-intent notes ("call the dentist sometime") from becoming
   a daily nag once they do get a reminder attached.

`TEST_PROMPTS.md` §4 is written to test all six of these directly and is expected to
fail against the current design until this addendum is implemented.

---

## 1. Capture routing — a single decision point, not implicit agent judgment

Add a new capability, exposed as an MCP tool from wherever it makes most sense to own
it (recommend extending the **Knowledge** module rather than creating a whole new
module, since routing is fundamentally a knowledge-classification problem):

```
tool: knowledge.capture(utterance, conversation_context) ->
      { stored_in: "journal" | "vault_note" | "reminder" | "expense" | "workout" |
                   "image_note" | "persona_only",
        ref_id, confidence }
```

Hermes calls this tool (via a skill, `hermes-config/skills/capture/SKILL.md`, with a
deterministic plugin backstop at `hermes-config/plugins/vesper-capture-router/`) whenever a
turn contains "remember," "note," "don't let me forget," or similar intent — not just
when the utterance is *only* that, since these often arrive attached to other content
(see `plan.md` §4's worked example, which is exactly this pattern already).

**Routing rules, in priority order:**

1. **Explicit date/time attached** ("remind me on the 5th", "in two weeks") → existing
   Calendar/Reminder path, unchanged. This case already works; don't touch it.
2. **Expense-shaped** (mentions an amount of money spent — "300 on lunch," "spent 150
   on the cab") → `journal.log_expense`, at any time of day, not just during the
   questionnaire in §2. See §2.4 for the categorization/summing behavior.
3. **Workout-shaped** (describes exercise/training — "did legs today," "went for a
   run") → `journal.log_workout`, at any time of day. See §2.4.
4. **Journal-flavored** (mentions today, mood, is sent during/right after the Daily
   Journal Questionnaire in §2, or is a mood/reflection fragment) → append to today's
   in-progress vault journal entry via the Journal MCP server, exactly as §8.3 (of
   `plan.md`) specifies.
5. **Discrete, nameable idea/fact/reference** (a book title, a standalone idea, a fact
   that isn't about today) → a vault note via the Knowledge MCP server, auto-titled and
   handed to the existing reactive Knowledge Architect tier (`plan.md` §9) for
   tagging/linking.
6. **Image attachment** → see §8 (Image Capture & Vision Routing) — saves the original
   file and creates a linked note from the resulting description.
7. **Genuinely ambiguous between 4 and 5** → default to **append to today's journal
   entry** (cheapest to move later, least likely to become an orphaned, hard-to-find
   note) and flag it for the nightly Knowledge Architect batch to reconsider — the
   mechanical re-filing judgment happens offline, cheap-tier, not blocking the
   interactive turn.
8. **In every case**, also mirror the raw utterance as an L1 Atom in TencentDB Agent
   Memory (it already does this automatically for anything said in conversation — this
   just confirms you're not fighting it, and gives you a redundant recall path
   regardless of which "durable" store won above).

**Audit trail:** log every routing decision (utterance, chosen store, confidence, which
rule fired) to a new table, `hermes.capture_routing_log`. This is what makes §4.2 of
`TEST_PROMPTS.md` checkable — "where did this actually go" needs to be answerable
without spelunking through three different stores by hand.

This resolves `TEST_PROMPTS.md` §4.2, §4.3, and §4.5's requirement for an inspectable,
consistent routing decision.

---

## 2. The Daily Journal Questionnaire — nightly ritual, 21:30 IST

This supersedes the lighter single-line nudge originally sketched here with a full,
scheduled, structured ritual — its own automation job (a new row in `plan.md` §12),
distinct from Evening Review, which now triggers off *this* job's completion rather
than its own independent clock (§2.7).

### 2.1 Trigger & scheduling
- New cron-triggered Hermes Agent skill, `daily_journal_questionnaire`, fires at
  **21:30 IST** every day.
- Before firing, check whether today's `diary_entries` row is already marked
  `complete = true` — if so, skip (don't ask twice).
- A casual journal entry already existing for today via ad hoc `knowledge.capture`
  doesn't cancel this — the questionnaire's job is a *complete*, structured record for
  the day, not just whatever came up in passing.

### 2.2 Fixed questions (same order, every day)
Store as a versioned config (`hermes-config/cron/daily_journal_questions.yaml`), not
hardcoded in the skill, so the set is easy to tune later:

1. Conditional opener: **"How was your day in office?"** on a weekday (Mon–Fri, IST
   calendar) or **"How was your day?"** otherwise.
2. **"Any major accomplishments or tasks you completed today?"**
3. **"What did you learn today — and where do you plan to (or already did) apply it?"**
4. **"Any specific reminders you want me to hold onto for the future, based on today?"**
5. **"Did you work out today? If so, what did you do, and which muscle groups did you
   target?"** — becomes a queryable workout log, not just journal prose; see §2.4.
6. **"What did you spend today?"** — accepts one amount or several ("300 on lunch, 150
   on the cab"); Hermes sums and categorizes each, per §2.4. Accept "nothing" or "not
   tracking today" gracefully — this question must never block completion.
7. *(proposed addition)* **"How would you rate your energy or mood today, and what
   mainly influenced it?"** — feeds `diary_entries.mood` directly.
8. *(proposed addition)* **"Did you connect with anyone worth logging today — anyone I
   should update in your contacts?"** — bridges to Relationship OS.
9. *(proposed addition)* **"Anything on your mind about tomorrow?"** — feeds context
   into the next morning's Morning Brief.

Confirm or adjust 7–9 before building — they round out the fixed set to something more
complete, but they're a proposed default, not a hard requirement the way 1–6 are (5 and
6 are hard requirements from this addendum, same tier as 1–4).

### 2.3 Specific follow-up questions (4–5, generated per day)
Once the fixed set is answered, generate 4–5 personalized follow-ups referencing
specifics actually mentioned — a named project, a person, an emotion, a decision. This
step needs genuine synthesis across that day's answers, so it should explicitly invoke
the model-escalation rule from `plan.md` §14 rather than run on the default cheap tier.
Ask conversationally, one at a time, so it still reads as a conversation, not a form.

### 2.4 Capture & decomposition — not one big text blob
Persist each answer immediately as it arrives (per the durability guarantee in §6), and
decompose rather than just concatenating into one paragraph:
- The full day's Q&A becomes today's primary vault journal entry.
- Q1's (and Q7's) answers set `diary_entries.mood`.
- Q4's answer, and any dynamic follow-up surfacing a task, goes through
  `knowledge.capture`'s routing rules (§1) — dated items become real Reminder rows;
  undated ones follow the anti-nagging policy (§5).
- Q3's answer, if it names something genuinely reusable, also becomes a linked vault
  note via Knowledge (§1's "discrete idea" rule) rather than staying buried in prose.
- **Q5's answer (workout)** writes a row to a new lightweight `journal.workouts` table
  (`date, activity, muscle_groups[], raw_text`) via a `journal.log_workout` MCP tool —
  this is what makes "how many times did I train legs this month" answerable later, not
  just that day's prose description.
- **Q6's answer (spending)** writes one row per mentioned amount to a new lightweight
  `journal.spending` table (`date, amount, category, raw_text`) via a
  `journal.log_expense` MCP tool. Categorize against a small fixed taxonomy (Food,
  Travel/Transport, Shopping, Bills/Utilities, Health, Entertainment, Other) —
  best-effort, defaulting to "Other" rather than blocking on an unclear category. Sum
  same-day entries and read the day's total back for confirmation before moving on
  ("Got it — ₹530 today: ₹300 food, ₹150 travel, ₹80 uncategorized"). **This table is
  deliberately allowed to be sparse and inconsistent** — some days will have nothing,
  some only partial categorization — don't require completeness to accept an entry.
- **Ad hoc, mid-day mentions don't wait for 21:30.** An expense- or workout-shaped
  utterance said at any time of day (§1, rules 2–3) routes immediately to the same
  `journal.log_expense`/`journal.log_workout` tools questions 5–6 use. By 21:30, the
  questionnaire should show what's already logged for the day and only ask "anything
  else?" rather than making you repeat yourself.
- Q8's answer, if a specific person is named, resolves and links to that person's CRM
  record via `knowledge.link_entity`, same as any other incidental mention.

### 2.5 Postponement
If the reply to the 21:30 prompt is "not now," "busy," "later," or similar (or the
questionnaire goes quiet mid-way), snooze and retry — never just wait silently for a
single next attempt:
- **21:30** — initial prompt.
- **22:15** — first retry, if not started or not completed.
- **23:00** — second retry.
- **23:40** — final retry, more urgent tone, offering an explicit shortcut: "Let's do
  the 60-second version — one thing about today, and any reminders" (questions 1 and 4
  only, skipping the rest for that night).
- Don't interrupt an active conversation — if a retry's scheduled moment arrives while
  the user is mid-answer, let them finish instead of firing the retry on top of it.
- If abandoned partway through, remember which question was last answered and **resume
  from there** on the next retry, not from question 1.

### 2.6 Hard deadline — a record must exist before midnight
- **23:55 IST cutoff.** If still incomplete, write a placeholder `diary_entries` row
  for that date (`complete = false`, whatever partial answers already exist — saved
  per-answer, not batched — mood left null if Q1/Q5 were never reached). The day must
  never end with literally nothing recorded, even if incomplete.
- No nudges between the cutoff and the next morning — respect sleep, don't ping
  overnight.
- The next morning, fold a gentle backfill offer into the Morning Brief ("Didn't finish
  yesterday's journal — fill in the rest now, or mark it skipped?"). A backfilled answer
  routes through the same `knowledge.capture` path, dated to the prior day, not today.

### 2.7 Completion event
On completion (full, or the midnight-deadline placeholder), publish a new event,
**`DailyJournalCompleted`** (add to the event catalog in `plan.md` §6), carrying
`{date, complete: bool}`. **Evening Review's trigger changes** from a fixed schedule to
event-driven off `DailyJournalCompleted`, with a scheduled fallback if the event never
fires for some reason — the same "event + scheduled fallback" pattern already used for
Portfolio Refresh in `plan.md` §12. This way Evening Review's cross-module summary
always has that day's actual journal content to draw from, instead of running on its
own clock and possibly summarizing before the entry exists.

### 2.8 Worth flagging before you build this
Nine fixed questions plus 4–5 dynamic ones is up to ~14 questions a night — a real
nightly commitment, even with §2.5 softening the timing. Two things worth doing so it
doesn't feel like filling out a form:
- **Group related questions into fewer conversational turns** rather than one
  back-and-forth per question — e.g. ask workout + spending together ("Anything to log
  today — a workout, any spending?") and mood + connections + tomorrow together. The
  fixed *content* in §2.2 stays as specified; only the *turn-taking* groups it.
- Consider a **"quick mode"** ("give me the short version tonight") that runs only
  questions 1–4 and 6 (spending is quick to answer and worth keeping even in a hurry;
  workout and the wellbeing/connection/forward-look questions are the ones to skip) and
  drops the dynamic follow-ups, while still producing a valid, complete entry — pairs
  naturally with §2.5's postponement flow without weakening §2.6's "something before
  midnight, always" guarantee.

Resolves `TEST_PROMPTS.md` §4.1 (now the full-pipeline acceptance test for this entire
ritual, including workout/spending) plus §4.11–§4.14.

---

## 3. Unified recall

Add one more MCP tool, again on the Knowledge module:

```
tool: knowledge.recall_everything(query) -> merged_results
```

Implementation: fan out to (a) LanceDB vault/entity semantic search, (b) Postgres
full-text search over `diary_entries` and notes metadata, and (c) TencentDB Agent
Memory's own hybrid BM25+vector+RRF recall API — in parallel, merge and dedupe by
content similarity, and return a single ranked list. This becomes the tool Hermes
reaches for on any "what have I told you about X" / "did I ever mention Y" phrasing,
instead of only checking whichever single store its default retrieval path happens to
hit.

This doesn't replace the existing per-store search tools (`knowledge.answer`,
TencentDB Agent Memory's own recall) — it's an additional, broader tool for the
specific case where the user doesn't know or care which store something landed in,
which is the common case for casual asides.

Resolves `TEST_PROMPTS.md` §4.4 and §4.5.

---

## 4. Correction and forgetting

Add `update_note` and `delete_note` tools to the Knowledge MCP server, and an
`update_entry`/`resolve` tool to the Journal MCP server for correcting or closing out a
past entry or reminder. Route "forget X" / "actually, scratch that" / "update my note
about Y" phrasing to these, through the same intent-detection skill as §1.

**Security note, deliberately lighter than `plan.md` §16's CRM/Finance gate:** note
edits and deletes are high-frequency, low-stakes actions — gating every "forget the
wifi password note" behind the same explicit-confirmation friction as deleting a CRM
contact would make the system's most-used feature annoying to use. Recommend: no
approval friction for note-level corrections (they're reversible via the vault's own
version history/git if you keep one, and low-consequence), while the heavier gate from
§16 stays exactly as strict as designed for CRM/Finance destructive actions. Flag this
distinction explicitly in `plan.md` §16 when you implement it, so it reads as a
deliberate choice rather than an inconsistency.

Resolves `TEST_PROMPTS.md` §4.6.

---

## 5. Anti-nagging policy for loose-intent reminders

When a captured note carries reminder-like intent but no explicit date/time (rule 1 in
§1 didn't fire — e.g. "sometime this month, no rush"), do **not** attach it to the
daily Notification Engine surface. Instead, surface it only in the **Weekly Review**
job's synthesis (`plan.md` §12), or on direct request ("what have I been meaning to
do?"). Explicit, dated reminders are unaffected by this and keep working exactly as
today.

Resolves `TEST_PROMPTS.md` §4.8.

---

## 6. Durability guarantee

State this as a hard requirement, not an implementation detail: **any utterance routed
through `knowledge.capture` must be synchronously persisted to at least one on-disk
store (vault file, Postgres row, or TencentDB Agent Memory's SQLite) within the same
turn, before Hermes replies that it's been remembered.** No capture path may rely solely
on an in-process/session buffer that a restart could lose. This is what
`TEST_PROMPTS.md` §4.9 (recall rate under load) and §4.10 (survives restart) are
designed to catch — treat any failure there as a durability bug, not a recall-tuning
issue.

---

## 7. Second Brain Publishing — Vault Backup to GitHub + Browsable Graph View

Two separate goals here, worth keeping distinct: **durable, versioned backup** (the
vault survives VPS loss) and **browsable access with graph view from any device** (you
can actually look at your second brain, not just trust it exists). Both are achievable
for free.

### 7.1 What research turned up
[**Quartz**](https://quartz.jzhao.xyz/) is a free, open-source static-site generator
built specifically for Markdown/Obsidian vaults — full compatibility with wikilinks,
backlinks, and an interactive graph view out of the box, with Docker support and a
documented GitHub Actions deployment path. This is close to exactly the
"Obsidian-online" experience you described — the thing that doesn't exist for free is
Obsidian's own official Sync/Publish (that's paid); Quartz is the free, open-source
substitute that gets you the graph view specifically.

### 7.2 One important adjustment: keep this private, not public
Quartz's own default deployment path is GitHub Pages, which is **public** unless you
pay for GitHub Pro/Enterprise to serve Pages privately. Your vault holds daily journal
entries, CRM notes, and personal reflections — not something to publish to the open
internet by default. Recommend different wiring, still entirely free:

1. **Push the vault to a *private* GitHub repository** (private repos are free and
   unlimited). This alone satisfies "see my second brain on any device" — GitHub's own
   web UI and mobile app render Markdown natively, so you can browse any note from your
   phone the moment it's pushed, no additional tooling required. This is the part that
   directly answers "GitHub is enough."
2. **Run the Quartz build locally**, as an ephemeral worker job (fits the existing
   "ephemeral workers, not always-on services" principle, `plan.md` §14) — not via
   GitHub Actions/Pages. Serve the built static output through the **existing Caddy
   container**, behind the **existing Tailscale setup** (`plan.md` §15/§16), at an
   internal-only hostname. This gets you the graph view and full browsing experience
   from any of your own devices, privately, with no public exposure — actually
   achieving the "ideal" you described rather than settling for the GitHub fallback.

### 7.3 Automation job
New Automation Engine row (`plan.md` §12), **plain scheduled worker, no LLM needed**:

| Job | Trigger | Does |
|---|---|---|
| Vault Backup & Publish | daily, 00:15 IST (after the questionnaire's 23:55 hard deadline) | `git add/commit/push` the vault to the private repo; rebuild the Quartz static site; refresh the Caddy-served copy |

Daily, per your stated preference, rather than weekly — it's cheap and mechanical, and
gives you same-day-visible backups. Log each run via the existing `CronRun` pattern so
a failed push doesn't fail silently.

### 7.4 Optional: structured data alongside the vault
The vault naturally holds Journal/Knowledge notes. If you also want CRM/Finance/
workout/spending data visible in the same private repo, the same daily job can
additionally export those tables to Markdown or CSV into a `data-exports/` folder —
worth deciding once the core vault backup is working, not a blocker for it.

---

## 8. Image Capture & Vision Routing

### 8.1 Hermes Agent already does most of this — configure, don't build
Hermes Agent has documented, built-in image handling: when an image arrives from any
entry point — including a Telegram photo — it checks whether the *currently active
main model* supports vision. If it does, the image goes through natively as real
pixels. If the main model is text-only (true of your default, DeepSeek V4 Flash), it
automatically falls back to a built-in `vision_analyze` tool that calls a configured
**auxiliary vision model**, describes the image, and injects that description into the
conversation — no manual "switch models" step, and no custom routing code to write.

**What you need to configure**: point `auxiliary.vision` (in
`hermes-config/provider.yaml`) at a vision-capable model. **Kimi K2.5, available
through your existing OpenCode Go subscription, explicitly supports vision** — no new
provider or subscription needed, just a config line.

### 8.2 A known upstream quirk to test for
There's an open issue on Hermes Agent's own repo (#29135) where, in `auto` image-input
mode, an explicit `auxiliary.vision` setting can incorrectly override *native* vision
handling even for main models that support it directly — forcing everything through
the lossy text-description path when it doesn't need to. This doesn't block the
recommendation here (your main model is text-only anyway, so the auxiliary path is what
you want regardless), but test for it explicitly during Phase 3/5 if you ever also
configure a vision-capable *main* model — don't assume auto-routing picks the better
path without checking.

### 8.3 Getting the analyzed image into notes
Once an image is analyzed (natively or via the auxiliary description), route it through
`knowledge.capture` (§1, rule 6): save the **original image file** into the vault's
`attachments/` folder, and create or update a linked vault note that embeds the image
and includes the AI-generated description as searchable text — tagged and categorized
by the existing reactive Knowledge Architect tier, same as any other note. Keeping the
actual image (not just a text description) matters here — a photo of a place is a much
better long-term memory than a caption of one.

---

## 9. One-Command Bootstrap (`start.sh`)

This is cross-cutting, not second-brain-specific — fold it into `coding_prompt.md`
Phase 1/Phase 10 when you next consolidate that document; captured here since it's part
of this session's requests.

**Goal:** `git clone <repo> && cd vesper && ./start.sh` is the entire setup process.
The only interactive input is secrets that can't be generated or guessed:

1. **Toolchain**: install git, python3-venv, node/npm, openssl, Docker + Compose,
   and Caddy via `apt` (Ubuntu 24.04 target per `plan.md` §15) or Homebrew
   (macOS). Also installs **Hermes Agent** via its official installer.
2. **Secrets, collected once, on first run only** (skip entirely on a re-run if
   `.env` already exists — the script must be idempotent):
   - LLM provider API key (OpenCode Go) — **required**.
   - Telegram bot token **and your numeric Telegram user ID** (for the
     `TELEGRAM_ALLOWED_USERS` allowlist, `plan.md` §16) — **required** for the
     agent to answer you.
   - Everything else (Postgres password, JWT secret, internal service URLs) is
     **generated automatically**, never asked for.
3. **Second-brain vault**: create `~/Documents/KnowledgeVault` fresh
   (`00 Journal/YYYY`, `03 Knowledge`, `99 Assets/images`, `01 Inbox`,
   `02 Projects`, `index.md`) and git-init it — no pre-existing vault assumed.
4. **Bring up the data layer**: `docker compose up -d postgres redis`, wait for
   health. On first run, wipe the DB to a genuinely empty state (schemas,
   tables, enum types, alembic version), then `alembic upgrade head` → 56 empty
   tables across 7 schemas; initialise the DuckDB feature store; seed the 6
   paper-trader accounts.
5. **Provision Hermes Agent** (`hermes-config/install_hermes.py`): write
   `~/.hermes/.env`, merge `hermes-config/hermes.config.template.yaml` →
   `~/.hermes/config.yaml` (provider + `auxiliary.vision` from §8, approvals,
   skills/cron external dirs), sync the 8 module MCP servers, install the
   `vesper-capture-router` plugin, and register the 6 reasoning cron jobs
   (Morning Brief, Daily Journal Questionnaire 21:30, Reviews, Knowledge
   Architect).
6. **Start the backend**: the API (:8000) and worker as host processes
   (`.venv/bin/python -m backend.main` with `APP_MODE=api|worker`).
7. **Start the web**: Quartz garden (Docker) + Caddy on :80 serving the static
   frontend, proxying `/api`, and serving `/brain` — reachable from your phone
   at `http://<server-ip>/`.
8. **Start Hermes Agent's gateway** pointed at the provided Telegram token.
9. **Health check + handoff message**: confirm Postgres/Redis/every module MCP
   server/Hermes Agent's gateway all report healthy, then print something like:
   "Vesper is live — message your bot on Telegram to get started."
10. **Idempotency**: safe to re-run at any time — detect what's already set up
    and skip it, so `start.sh` doubles as the update/repair path, not just
    first-run setup. `--fresh` forces a full DB wipe + re-migrate.

---

## 10. Infra Sizing: RAM & VPS Provider Notes

Answering the sizing questions this session raised, now with real numbers instead of
`plan.md` §15's earlier "unmeasured" placeholder — still worth confirming with that
section's Phase 0.5 spike against your actual configuration, but the range below is
well-supported by Hermes Agent's own published specs and independent testing:

- Hermes Agent itself: chat-only resident use holds around 300–600MB; published specs
  vary by source between a bare 1GB minimum (API-only, no browser tool) and a
  "comfortable for daily use" recommendation of 2–4GB once messaging gateways, a
  growing skill library, and (if ever enabled) the browser-automation tool are factored
  in.
- Combined with the rest of the stack (`plan.md` §15's postgres/redis/caddy/vesper-api
  estimate of ~0.9–1.2GB), a reasonable steady-state total is **~1.5–3GB**, comfortably
  inside an **8GB** VPS with real headroom for ephemeral worker bursts (nightly
  Knowledge Architect pass, backtests, this addendum's new vault-publish job).
- **4GB is plausible but tight** — little margin left for burst overlap (a Knowledge
  Architect pass landing during an active conversation, say), and less room to be wrong
  about the estimate above. **8GB is the safer target.** Still run the Phase 0.5 spike
  with your actual module/skill/memory-plugin configuration before treating either
  number as final.
- Image analysis calls (§8) and the Quartz publish job (§7) don't materially change
  this: image analysis is an API call (no local RAM cost beyond a normal conversation
  turn), and the Quartz build is a bounded, ephemeral job like the other worker-tier
  jobs already budgeted for.

**On Contabo specifically**: independent reviews are generally positive on
price-to-performance and uptime, with the usual spread of complaints any large budget
host accumulates (an occasional flagged/recycled IP, minor peak-hour slowdowns on the
cheapest tier). Nothing in that research points to a *safety* problem specific to
Contabo. The more relevant point for this project: for a VPS holding personal
journal/CRM/finance data, safety is determined far more by your own configuration than
by which reputable provider you pick — see the new bullet added to `plan.md` §16.

---

## 11. Where this lands in the existing documents

If/when you fold this addendum's content back into the main docs directly:

- `plan.md` §4 (Universal Inbox) — add the capture-routing description from §1 above,
  including the expense/workout/image cases.
- `plan.md` §7 (Memory Architecture) — note the mirror-to-TencentDB-Agent-Memory
  guarantee from §1's last rule; add the new lightweight `journal.workouts` and
  `journal.spending` tables from §2.4.
- `plan.md` §9 (Knowledge Architect) — add the "ambiguous → journal-first, reconsider
  nightly" rule from §1.
- `plan.md` §6 (Event Catalog) — add `DailyJournalCompleted`, published by the new
  questionnaire job, subscribed to by Evening Review (§2.7).
- `plan.md` §12 (Automation Engine) — add two new rows: **Daily Journal Questionnaire**
  (21:30 IST, escalating retries per §2.5, 23:55 hard deadline) and **Vault Backup &
  Publish** (§7.3, daily 00:15 IST); change the existing **Evening Review** row's
  trigger from "scheduled" to "event (`DailyJournalCompleted`) + scheduled fallback."
- `plan.md` §14 (Compute Strategy) — note the `auxiliary.vision` provider setting (§8)
  alongside the existing default/fallback provider configuration.
- `plan.md` §15 (Infra) — add the Quartz-served static site behind Caddy/Tailscale as
  an additional (still free, still local) surface, not a new always-on container.
- `plan.md` §16 (Security) — add the lighter-weight note-correction carve-out from §4;
  add the VPS-provider-hygiene note from §10.
- `coding_prompt.md` Phase 4 — module MCP server work for Knowledge/Journal should
  include `capture`, `recall_everything`, `update_note`, `delete_note`, `log_expense`,
  `log_workout` as named tools to build, not left implicit.
- `coding_prompt.md` Phase 7 — add the `daily_journal_questionnaire` skill (§2.1–§2.6)
  under `hermes-config/cron/`, alongside its questions config; add the Vault Backup &
  Publish job (§7.3); update Evening Review to subscribe to `DailyJournalCompleted`
  instead of running on its own fixed time.
- `coding_prompt.md` Phase 1/Phase 10 — add `start.sh` (§9) as the required final
  deliverable script.
