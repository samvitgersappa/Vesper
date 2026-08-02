---
name: weekly-review
description: "Weekly Review: rollup of brief/review data over the week. Reasoning job (plan §12)."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [review, weekly, cross-module, scheduled]
    cron: "0 10 * * 0"
    related_skills: [monthly-review]
---

# Weekly Review

Longer-horizon rollup delivered via Hermes Agent cron.

## When to Use

Triggered weekly (Sunday).

## Behavior

Aggregate the week's NAV, interactions, study progress, journal consistency into
a single narrative summary.
