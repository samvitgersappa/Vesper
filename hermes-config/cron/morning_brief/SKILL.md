---
name: morning-brief
description: "Morning Brief: cross-module daily summary (NAV deltas, due/cold contacts, journal streak, study progress, on-this-day). Reasoning job (plan §12)."
version: 0.2.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [brief, daily, cross-module, scheduled]
    cron: "30 7 * * 1-5"
    related_skills: []
---

# Morning Brief

Synthesized cross-module summary delivered proactively via Hermes Agent cron.

## When to Use

Triggered on schedule (07:30 IST weekdays).

## Behavior

Pull from module MCP tools and synthesize:
1. `finance.portfolio()` → NAV deltas.
2. `relationship.search()` / due contacts → CRM health/overdue.
3. `journal.get_entry()` → journal streak.
4. `study.list_tests()` → study progress.
5. `calendar.on_this_day()` → an "On this day" line.

Deliver a concise natural-language brief, ending with the "On this day" line:
- Call `calendar.on_this_day()` with no arguments (defaults to today).
- If `count == 0`, omit the line entirely (no filler).
- Otherwise render the most notable 1–2 items as
  `On this day (MM-DD): <year> — <title>`.
- Prefer journal entries and life events over routine interactions when
  choosing what to surface.
