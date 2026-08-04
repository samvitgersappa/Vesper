# Catalyst Swing Trader - Methodology and Validation Tracker

Items that are research prerequisites, not code bugs. The pipeline machinery
is tested (34 passing tests, honest degrade), but none of that proves edge.

## Before trusting backtest numbers

### E.13 - Point-in-time universe fix
**Status: NOT YET VALIDATED**

The Nifty-500 membership CSV is a static snapshot - it does not reflect
historical index composition changes. Backtests that use today's universe to
score symbols from 2018-2023 bake in survivorship bias.

**What to do:**
1. Collect historical Nifty-500 constituent lists (monthly snapshots)
2. Store as `index_membership` rows keyed by date
3. Validate: re-run backtests and compare returns against the static-universe
   baseline. Expect a drop, not a gain (survivorship bias inflates).

### E.14 - Walk-forward validation
**Status: NOT YET VALIDATED**

The current setup trains and trades on the full history. Walk-forward means:
train on 2018-2020, trade 2021; train on 2018-2021, trade 2022; etc.

**What to do:**
1. Run `run_day` for each walk-forward window
2. Compute cumulative returns, Sharpe, max drawdown per window

### E.15 - Phase-gate: 3-dimension vs 6-dimension Layer-3
**Status: SHIPPED TOGETHER (not phased)**

The screen ships with all 6 Layer-3 dimensions in one pass. The plan was:
prove the first 3 work OOS, then add the next 3.

**What to do:**
1. Run backtests with only the first 3 dimensions
2. Run backtests with all 6 dimensions
3. Compare on walk-forward OOS. If the extra 3 do not improve Sharpe/Calmar,
   remove them (complexity without edge is just noise).

## Pipeline timing

### 18:00 job stagger
**Status: FIXED** - `notification_sweep_evening` moved 18:00 to 18:05.

### compute_market_breadth to catalyst_screen gap
**Status: MONITORING (5 min gap)**

Only 5 minutes between `compute_market_breadth` (18:15) and `catalyst_screen`
(18:20). The breadth pass reads DuckDB in-process, fast for 500 symbols. If it
spills past 18:20, catalyst_screen runs with stale breadth.

### NSE endpoint format changes
**Status: RESILIENT BY DESIGN**

NSE shifts endpoint formats periodically. The catalyst pipeline always degrades
honestly (returns `degraded: true` with a note, records a degraded run, and
moves on). No job ever fails the scheduler.
