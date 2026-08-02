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
- Before Q5/Q6, read what's already logged today via `journal.log_expense` /
  `journal.log_workout` totals so you ask "anything else?" instead of repeating.

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

## Retries (§2.5)

If the user says "not now"/"later"/"busy", or the questionnaire goes quiet:
reschedule to the next retry slot (22:15 → 23:00 → 23:40). Never fire a retry on
top of an active conversation. Resume from the last-answered question, not Q1.

## Hard deadline (§2.6)

At 23:55 IST, if still incomplete, write a placeholder `diary_entries` row
(`complete = false`, whatever partial answers exist, mood left null) — the day must
never end with literally nothing recorded. No nudges overnight. The Morning Brief
offers a backfill next morning (answers dated to the prior day).
