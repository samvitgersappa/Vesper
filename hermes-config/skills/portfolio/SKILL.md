---
name: portfolio
description: "Portfolio summary via the Finance module. Reproduces VesperAIOS /portfolio."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [finance, portfolio, paper-trading, nav]
    related_skills: []
---

# Portfolio

Reproduces VesperAIOS `/portfolio` (INVENTORY.md §2.2).

## When to Use

User asks about portfolio value, positions, P&L, or recent trades.

## Behavior

1. Call Finance MCP tools: `finance.portfolio(strategy?)`, `finance.trades()`, `finance.signals()`.
2. Reply format: `📈 Portfolio: ₹{total:,.0f}` + `P&L: ±₹…` + per-position `• SYM: qty @ avg → ±₹pnl`.
3. Empty → "Portfolio is empty."

## MCP tools used

- `finance.portfolio(strategy?)`
- `finance.trades(limit=20)`
- `finance.signals()`

## Safety

Finance MCP server is read-only (plan §16). This skill never triggers trades.
