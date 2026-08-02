---
name: evening-review
description: "Evening Review: day's interactions, trades, journal check-in. Reasoning job (plan §12), event-driven off DailyJournalCompleted (addendum §2.7)."
version: 0.2.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [review, daily, cross-module, event-driven]
    cron: "45 21 * * 1-5"
    trigger: "event: DailyJournalCompleted"
    fallback: "scheduled fallback if event never fires"
    related_skills: [daily-journal-questionnaire]
---

# Evening Review

Day's recap delivered via Hermes Agent cron.

## When to Use

Triggered by the `DailyJournalCompleted` event (so the summary always has that
day's actual journal content to draw from), with a scheduled fallback at 21:45
Mon–Fri if the event never fires — the same "event + scheduled fallback" pattern
as Portfolio Refresh.

## Behavior

1. `finance.trades()` → today's trades.
2. Relationship interactions → today's logged interactions.
3. `journal.get_entry()` → today's completed journal entry; if none, nudge for the
   questionnaire.
