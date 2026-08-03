---
name: weekly-review
description: "Weekly Review: cross-module narrative rollup of finance, relationships, journal and study over the past week. Reasoning job (plan §12)."
version: 0.2.0
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

Longer-horizon cross-module narrative rollup delivered via Hermes Agent cron.

## When to Use

Triggered weekly (Sunday, 10:00). The review covers the trailing 7 calendar days.

## Data Sources

Pull each module once and hold the results in working context:

1. `finance.nav()` → NAV series per trader over the week (deltas, day/cumulative
   PnL %).
2. `finance.trades()` (limit 100) → executed trades in the window, plus
   `finance.portfolio()` for total equity / capital.
3. `relationship.search()` + `relationship.get_due_today()` + `relationship.graph()`
   → interactions, due/cold contacts, bridge contacts, network moves over the week.
4. `journal.get_entry()` for the week's entries → journal consistency/streak,
   themes, recurring topics.
5. `study.list_tests()` + `study.percentiles()` → test progress and readiness
   deltas vs. the previous week.

## Behavior

Produce a SINGLE narrative summary, not a bullet list of modules. Weave the four
threads together into one story:

1. **The week in one sentence.** What kind of week it was overall (building,
   drifting, consolidating) based on the strongest signal across modules.
2. **Where the story moved** — how finance, relationship, journal and study
   reinforced or contradicted each other (e.g. a winning week paired with a cold
   CRM and a journal gap is a "capital without follow-through" story).
3. **Cost line (required).** Compute total trading cost for the week as:
   - slippage cost per executed trade = `abs(fill_price - signal_price) * quantity`
     (use `signal_price`/`fill_price`/`quantity` from `finance.trades()`);
   - total cost = sum of slippage costs (report the basis points equivalent as
     well: `total_cost / sum(quantity * signal_price) * 10000`);
   - express the final figure as **cost as % of capital**: `total_cost /
     total_equity * 100` where `total_equity` comes from `finance.portfolio()`.
   - Emit a line like "Trading cost was 0.04% of capital this week (18 bp of
     notional slippage)."
   - If no executed trades occurred, say so explicitly ("No trades executed —
     no cost accrued.").
4. **Journal consistency** — streak preserved or broken, and whether the week's
   writing reflects the week's events (or diverges).
5. **Study progress** — mock-test percentile deltas and how many readiness levels
   remain before the target exam date.
6. **One-line lookahead** — the single most important thing for next week.

Keep it under ~200 words. Start with the one-sentence summary.
