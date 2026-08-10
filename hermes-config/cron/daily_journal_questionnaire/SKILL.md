---
name: daily-journal-questionnaire
description: "Nightly structured journal ritual at 21:30 IST — the Daily Journal Questionnaire (addendum §2, plan.md §12.1)."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [journal, daily, scheduled, questionnaire]
    cron: "30 21 * * *"
    related_skills: [evening-review]
---

# Daily Journal Questionnaire

The nightly structured journal ritual. Runs as a Hermes Agent cron job every day at
**21:30 IST**. Distinct from Evening Review, which now triggers off *this* job's
completion (`DailyJournalCompleted`) rather than its own clock.

## Before starting

1. Check today's `journal` metadata — if `diary_entries.complete == true` for today,
   skip entirely (don't ask twice).
2. A casual journal entry from ad hoc `knowledge.capture` does **not** cancel this —
   the questionnaire produces a *complete, structured* record for the day.

## The fixed questions

Loaded from `hermes-config/cron/daily_journal_questions.yaml` (versioned config,
same order every day). Do **not** re-read the YAML per question — load once at start.

- Q1 uses the weekday variant (`...in office?`) Mon–Fri IST, the default otherwise.
- Before Q5/Q6, read what's already logged today via
  `journal.spending_summary` and the workout read tool so you ask "anything
  else?" instead of repeating.

## Journal entry formatting (Obsidian / Quartz graph)

The vault journal must be a **connected graph node**, not flat text. Every entry
should surface in the Quartz garden with proper wikilinks:

1. **Write verbosely and specifically.** Each answer is a short paragraph (2–4
   sentences), not a single line — name actual people, places, projects,
   decisions, emotions, and numbers. A link-rich, detailed record compounds into
   a genuinely useful second brain; a terse one does not.

2. **People as wikilinks** — every person you mention must be linked with
   `[[person-slug]]` (the exact filename stem of their vault note in lower-case).
   Before writing, use `mcp__knowledge__search` to find people notes under
   `05 People/`. For people without existing notes, create a one-line stub.

3. **Topic cross-references** — if today mentions a skill, project, or concept
   that has a vault note (in `03 Knowledge/`, `04 Learning/`, `06 Finance/`),
   link it with `[[note-slug]]`. When an answer names something reusable, create
   the note now via `knowledge.capture` (not just a link to a note that doesn't
   exist yet).

4. **Use `##` section headings** (Mood, Highlights, Learning, Workout, Expenses,
   Reminders, People, Connected, Tomorrow). This keeps journal entries readable
   and the Quartz table of contents works.

5. **Create stub People notes as needed.** If a person has no note yet, create
   a minimal one-liner under `05 People/person-name.md` so the wikilink resolves.

6. **Mirror the graph template.** When the machine-facing
   `journal.enrich_entry` / `journal.complete_day` step runs it rewrites
   frontmatter and the `## Connected` block automatically — keep your own
   sections' *content* rich and specific so that rewrite has real links to keep.

Do NOT exhaustively search — linking 2-3 people and 1-2 topics per entry is
enough. The graph improves incrementally with each day's links.

## Verbosity & detail bar

Each answered question becomes a paragraph with concrete specifics:

- **Mood** — 1–2 lines: the word plus *why*; name the trigger (a meeting, a
  workout skipped, weather, a win).
- **Highlights / accomplishments** — name the task/project, the outcome, and any
  ripple effect (who it helped, what it unblocks).
- **Learning** — state the concept, the source (video/book/conversation), and
  where you plan to apply it. Link `[[learning-note]]` where it exists.
- **Workout** — what you did, sets/reps or distance, muscle groups, how it felt.
- **Expenses** — via `journal.log_expense`: amount, item, category (Food,
  Travel/Transport, Shopping, Bills/Utilities, Health, Entertainment, Other).
- **Reminders** — dated when possible (routed to a real Reminder row).
- **People / Connected** — who, in what context, why it mattered.
- **Tomorrow** — the top 1–3 concrete things, not a vague "work stuff".

A complete entry lands between ~180–500 words. If your answers come out shorter
than ~150 words, you've left concrete detail on the table — expand before you
finish.

## Persist each answer immediately (§2.4, §6 durability)

Never batch — every answer is written the moment it arrives:

- Full day's Q&A becomes today's primary vault journal entry
  (`journal.write_entry`, append).
- Q1/Q7 → `diary_entries.mood`.
- Q4 → route through `knowledge.capture` (dated → real Reminder row; undated →
  anti-nagging policy).
- Q3 → if genuinely reusable, also a linked vault note via Knowledge.
- Q5 → one `journal.log_workout` row per answer.
- Q6 → one `journal.log_expense` row per mentioned amount, against the fixed
  taxonomy (Food, Travel/Transport, Shopping, Bills/Utilities, Health,
  Entertainment, Other; best-effort, default "Other"); read the day's total back
  for confirmation.
- Q8 → resolve each individual person separately. Group labels such as
  "grandparents", "parents", "family", or "colleagues" are not people: ask for
  the individual names before creating contacts. For each named person, search
  first, call `relationship.create_person` only when no match exists, then call
  `relationship.create_interaction` with today's date and the connection context.
  Never claim a contact was saved without a successful tool result.
- Q9 → append the answer to the journal entry as the Tomorrow section; do not
  leave it only in the chat transcript.

## Turn-taking (§2.8) — group, don't interrogate

Group into conversational turns (day → log → wellbeing → reminders) rather than one
back-and-forth per question. Offer **quick mode** when the user wants the short
version: questions 1, 4, 6 only, still a valid complete entry.

## After the fixed set (§2.3)

Generate 4–5 personalized follow-ups referencing specifics already mentioned (a
named project, person, emotion, decision). Ask one at a time. This step needs real
synthesis — escalate to the plan §14 model tier rather than the cheap default.

## Completion

On completion publish `DailyJournalCompleted` via `journal.complete_day`
(marks `diary_entries.complete = true`). Evening Review subscribes to this event.
Only announce completion after `complete_day` returns `ok: true`; if any mapped
write fails, retry it and report the specific failure instead of saying the entry
is held in chat.

## Retries (§2.5)

If the user says "not now"/"later"/"busy", or the questionnaire goes quiet:
reschedule to the next retry slot (22:15 → 23:00 → 23:40). Never fire a retry on
top of an active conversation. Resume from the last-answered question, not Q1.

## Hard deadline (§2.6)

At 23:55 IST, if still incomplete, write a placeholder `diary_entries` row
(`complete = false`, whatever partial answers exist, mood left null) — the day must
never end with literally nothing recorded. No nudges overnight. The Morning Brief
offers a backfill next morning (answers dated to the prior day).
