"""Catalyst Swing Trader (Trader 6, Part E).

A momentum/catalyst swing strategy layered over the existing paper-trading
infrastructure. Pipeline per the Trader 6 Data Acquisition Guide:

- Data acquisition (18:00–18:15 IST): NSE bhavcopy delivery, FII/DII,
  index option-chain PCR, sector indices, breadth computed from equity_daily.
- Screening (18:20–18:40): factors → Layer 1 (market) / Layer 2 (sector) /
  Layer 3 (stock) multiplicative scoring → watchlist funnel → LLM catalyst
  analysis (DeepSeek V4 Flash, capped at CATALYST_TRADER_MAX_LLM_CALLS_PER_DAY).
- Risk & execution (18:50–19:00): cost gate (3–4x target), position limits
  (5–8 concurrent, 1–3 entries/day), ATR stops, trailing stops, 10-day time
  exit, rank-deterioration exit, negative-catalyst exit.

All writes happen only in the worker jobs; the Finance MCP/API surface stays
read-only (plan §16). Every external fetch retries 3x then records a
`degraded` run in finance.job_runs — the pipeline never aborts and never
fabricates data.
"""

TRADER_ID = "catalyst_swing"

# Daily LLM-call budget for the catalyst-analysis stage (work order).
MAX_LLM_CALLS_PER_DAY = int(
    __import__("os").environ.get("CATALYST_TRADER_MAX_LLM_CALLS_PER_DAY", "65")
)

# Risk knobs (work order).
MAX_CONCURRENT_POSITIONS = 8
MIN_CONCURRENT_POSITIONS = 5
MAX_ENTRIES_PER_DAY = 3
MAX_HOLD_DAYS = 10
# Cost gate: expected cost must be <= target / COST_TARGET_MIN_MULTIPLE.
# The 3–4x range is enforced as a target-to-cost ratio between 3 and 4.
COST_TARGET_MIN_MULTIPLE = 3.0
COST_TARGET_MAX_MULTIPLE = 4.0

# Watchlist-funnel sizes.
SCREEN_TOP_N = 15  # factor-composite funnel fed to the LLM stage
WATCHLIST_SIZE = 10  # candidates that survive the LLM gate for entry review

# Sector indices on yfinance (Nifty sector indices) for Layer-2 momentum.
SECTOR_TICKERS = {
    "AUTO": "^CNXAUTO",
    "IT": "^CNXIT",
    "PHARMA": "^CNXPHARMA",
    "FMCG": "^CNXFMCG",
    "METAL": "^CNXMETAL",
    "ENERGY": "^CNXENERGY",
    "MEDIA": "^CNXMEDIA",
    "REALTY": "^CNXREALTY",
    "BANK": "^NSEBANK",
}
