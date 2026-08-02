---
name: morning-brief
description: "Morning Brief: cross-module daily summary (NAV deltas, due/cold contacts, journal streak, study progress). Reasoning job (plan §12)."
version: 0.1.0
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

Deliver a concise natural-language brief.
