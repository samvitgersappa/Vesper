---
name: monthly-review
description: "Monthly Review: month-level rollup. Reasoning job (plan §12)."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [review, monthly, cross-module, scheduled]
    cron: "0 10 1 * *"
    related_skills: [weekly-review]
---

# Monthly Review

Month-level rollup delivered via Hermes Agent cron.

## When to Use

Triggered monthly (1st, 10:00).

## Behavior

Aggregate the month's NAV, interactions, study progress, journal consistency into
a single narrative summary.
