"""ipo module — upcoming & recent Indian IPO calendar (plan §13, web + MCP).

The NSE IPO API is unreachable from typical dev environments (and yfinance
has no IPO calendar), so this module is backed by a curated dataset of
upcoming/recent NSE/BSE IPOs (`IPO_UNIVERSE` below). Every row carries enough
structure for the web page (dates, price band, lot size, status) and is
deterministic — no network dependency, no LLM.

Exposes read tools:
- `list_upcoming()`   — IPOs still open/upcoming (status in pending/upcoming)
- `list_recent()`     — recently closed/listed IPOs
- `list_all()`        — the whole curated calendar

An optional DB-backed path (`finance`-style table) can be added later if a
live provider becomes available; the module stays read-only today.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Curated NSE/BSE IPO calendar. Dates are illustrative placeholders on a
# rolling window anchored to today so the page always has upcoming + recent
# rows. Replace/refresh this list to track real listings.
def _iso(d: date) -> str:
    return d.isoformat()


def _universe() -> list[dict[str, Any]]:
    today = date.today()
    return [
        {
            "id": "one971-2026",
            "name": "ONE97 Communications (Paytm) FPO",
            "symbol": "PAYTM",
            "exchange": "NSE",
            "open_date": _iso(today + timedelta(days=1)),
            "close_date": _iso(today + timedelta(days=3)),
            "listing_date": _iso(today + timedelta(days=9)),
            "price_band": "₹950 – ₹1,000",
            "lot_size": 15,
            "status": "upcoming",
            "note": "Follow-on public offer (curated placeholder).",
        },
        {
            "id": "swiggy-2026",
            "name": "Swiggy Ltd",
            "symbol": "SWIGGY",
            "exchange": "NSE/BSE",
            "open_date": _iso(today + timedelta(days=2)),
            "close_date": _iso(today + timedelta(days=4)),
            "listing_date": _iso(today + timedelta(days=10)),
            "price_band": "₹370 – ₹390",
            "lot_size": 38,
            "status": "upcoming",
            "note": "Food-delivery IPO (curated placeholder).",
        },
        {
            "id": "vishal-2026",
            "name": "Vishal Mega Mart",
            "symbol": "VMM",
            "exchange": "NSE",
            "open_date": _iso(today + timedelta(days=4)),
            "close_date": _iso(today + timedelta(days=6)),
            "listing_date": _iso(today + timedelta(days=12)),
            "price_band": "₹72 – ₹78",
            "lot_size": 190,
            "status": "upcoming",
            "note": "Value retail IPO (curated placeholder).",
        },
        {
            "id": "watch-2026",
            "name": "Watch & Accessories Manufacturing Co",
            "symbol": "WATCH",
            "exchange": "NSE/BSE",
            "open_date": _iso(today - timedelta(days=1)),
            "close_date": _iso(today + timedelta(days=1)),
            "listing_date": _iso(today + timedelta(days=6)),
            "price_band": "₹350 – ₹370",
            "lot_size": 40,
            "status": "open",
            "note": "Currently open for subscription (curated placeholder).",
        },
        {
            "id": "inventurus-2026",
            "name": "Inventurus Knowledge Solutions",
            "symbol": "INVENT",
            "exchange": "NSE/BSE",
            "open_date": _iso(today - timedelta(days=2)),
            "close_date": _iso(today - timedelta(days=1)),
            "listing_date": _iso(today + timedelta(days=5)),
            "price_band": "₹1,290 – ₹1,326",
            "lot_size": 11,
            "status": "recent",
            "note": "Closed; listing expected (curated placeholder).",
        },
        {
            "id": "zomato-2025",
            "name": "Zomato Ltd (recent listing)",
            "symbol": "ZOMATO",
            "exchange": "NSE/BSE",
            "open_date": _iso(today - timedelta(days=14)),
            "close_date": _iso(today - timedelta(days=12)),
            "listing_date": _iso(today - timedelta(days=7)),
            "price_band": "₹72 – ₹76",
            "lot_size": 195,
            "status": "listed",
            "note": "Listed at premium (curated placeholder).",
        },
        {
            "id": "ecom-2025",
            "name": "Ecom Express Ltd",
            "symbol": "ECOM",
            "exchange": "NSE/BSE",
            "open_date": _iso(today - timedelta(days=21)),
            "close_date": _iso(today - timedelta(days=19)),
            "listing_date": _iso(today - timedelta(days=14)),
            "price_band": "₹756 – ₹798",
            "lot_size": 18,
            "status": "listed",
            "note": "E-commerce logistics IPO (curated placeholder).",
        },
        {
            "id": "unicom-2025",
            "name": "Unicommerce eSolutions",
            "symbol": "UNICOM",
            "exchange": "NSE/BSE",
            "open_date": _iso(today - timedelta(days=28)),
            "close_date": _iso(today - timedelta(days=26)),
            "listing_date": _iso(today - timedelta(days=21)),
            "price_band": "₹102 – ₹108",
            "lot_size": 138,
            "status": "listed",
            "note": "E-commerce SaaS IPO (curated placeholder).",
        },
    ]


async def list_all() -> dict[str, Any]:
    """The full curated IPO calendar (upcoming + recent/listed)."""
    rows = _universe()
    return {"ok": True, "count": len(rows), "source": "sample", "ipos": rows}


async def list_upcoming() -> dict[str, Any]:
    """IPOs that are upcoming or currently open for subscription."""
    rows = [r for r in _universe() if r["status"] in {"upcoming", "open"}]
    rows.sort(key=lambda r: r["open_date"])
    return {"ok": True, "count": len(rows), "source": "sample", "ipos": rows}


async def list_recent() -> dict[str, Any]:
    """Recently closed or listed IPOs (newest listing first)."""
    rows = [r for r in _universe() if r["status"] in {"recent", "listed"}]
    rows.sort(key=lambda r: r["listing_date"], reverse=True)
    return {"ok": True, "count": len(rows), "source": "sample", "ipos": rows}
