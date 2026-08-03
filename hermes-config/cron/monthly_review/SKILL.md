---
name: monthly-review
description: "Monthly Review: month-level cross-module narrative rollup of finance, relationships, journal and study. Reasoning job (plan §12)."
version: 0.2.0
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

Month-level cross-module narrative rollup delivered via Hermes Agent cron.

## When to Use

Triggered monthly (1st, 10:00). Covers the trailing ~30 calendar days.

## Data Sources

Pull each module once and hold the results in working context:

1. `finance.nav()` → NAV series per trader over the month (trend, peak-to-trough,
   day/cumulative PnL %).
2. `finance.trades()` (limit 500) → executed trades in the window, plus
   `finance.portfolio()` for total equity / capital.
3. `relationship.search()` + `relationship.get_due_today()` + `relationship.graph()`
   → interactions, due/cold contacts, bridge contacts, network moves over the month.
4. `journal.get_entry()` for the month's entries → journal consistency, themes,
   recurring topics, and any goals stated in the writing.
5. `study.list_tests()` + `study.mock_tests(test_id)` + `study.percentiles(test_id)`
   → mock-test scores, percentile deltas, and readiness vs. the previous month.

## Behavior

Produce a SINGLE narrative summary, not a bullet list of modules. Compare against
the previous month where data allows and weave the threads into one story:

1. **The month in two sentences.** The overall shape (compounding, flatlining,
   regressing) supported by the strongest evidence across modules.
2. **Cross-module narrative.** Explicitly connect the threads: did capital growth
   come from attention spent elsewhere? Did a relationship push lead to new
   study material or a journal theme? Surface contradictions (e.g. strong NAV but
   deteriorating journal consistency).
3. **Cost line (required).** Compute total trading cost for the month as:
   - slippage cost per executed trade = `abs(fill_price - signal_price) * quantity`
     (use `signal_price`/`fill_price`/`quantity` from `finance.trades()`);
   - total cost = sum of slippage costs (report basis points as well:
     `total_cost / sum(quantity * signal_price) * 10000`);
   - express the final figure as **cost as % of capital**: `total_cost /
     total_equity * 100` where `total_equity` comes from `finance.portfolio()`.
   - Emit a line like "Trading cost was 0.12% of capital this month (35 bp of
     notional slippage)."
   - If no executed trades occurred, say so explicitly ("No trades executed —
     no cost accrued.").
4. **Journal consistency** — streak preserved or broken; whether writing volume
   tracked the month's intensity.
5. **Study progress** — percentile deltas, tests added, and remaining readiness
   gap to the target exam date.
6. **One-line lookahead** — the single most important thing for next month.

Keep it under ~250 words. Start with the two-sentence summary.
