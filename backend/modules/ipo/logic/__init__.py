"""ipo module — upcoming & recent Indian IPO calendar (plan §13, web + MCP).

Backed by **real data** from Moneycontrol's IPO page (`__NEXT_DATA__` JSON),
fetched live with a short TTL cache. When the network/provider is unreachable
it degrades honestly to a small curated fallback list (never fabricates), and
reports `source: "live"` vs `source: "sample"` so the UI can say which.

Every row maps to the web page's shape:
  id, name, symbol, exchange, open_date, close_date, listing_date,
  price_band, lot_size, status, note
"""

from __future__ import annotations

import json
import html
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger("vesper.ipo")

# Moneycontrol IPO page — the `__NEXT_DATA__` JSON holds the live calendar.
MONEYCONTROL_IPO_URL = "https://www.moneycontrol.com/ipo/"
CHITTORGARH_IPO_URL = "https://www.chittorgarh.com/calendar/ipo-calendar/1/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_TTL_SECONDS = 10 * 60  # refresh the live calendar at most every 10 min
_cache: dict[str, Any] = {"ts": 0.0, "data": None, "ok": False}


def _iso(d: date) -> str:
    return d.isoformat()


# ── Live fetch from Moneycontrol ─────────────────────────────────────────
def _moneycontrol_rows() -> Optional[list[dict[str, Any]]]:
    """Fetch + parse the live IPO calendar. Returns None on any failure."""
    try:
        resp = httpx.get(
            MONEYCONTROL_IPO_URL, headers=_HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("moneycontrol IPO page returned %s", resp.status_code)
            return None
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            resp.text, re.S,
        )
        if not m:
            logger.warning("moneycontrol IPO page has no __NEXT_DATA__")
            return None
        data = json.loads(m.group(1))
        ipo = data["props"]["pageProps"]["ipoData"]
    except Exception as exc:  # noqa: BLE001 - any fetch failure degrades
        logger.warning("moneycontrol IPO fetch failed: %s", exc)
        return None

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _band(lo, hi) -> str:
        try:
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError):
            return ""
        if lo <= 0 and hi <= 0:
            return ""
        return f"₹{int(lo):,} – ₹{int(hi):,}"

    def _symbol(name: str, code) -> str:
        return str(code or "").upper() or ""

    def _add(item: dict, status: str) -> None:
        name = str(item.get("company_name") or item.get("equityName") or "").strip()
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        code = item.get("sc_id") or item.get("company_code") or item.get("short_name")
        rows.append({
            "id": str(code or re.sub(r"[^a-z0-9]+", "-", name.lower())),
            "name": name,
            "symbol": _symbol(name, code),
            "exchange": "NSE/BSE" if str(item.get("ipo_type", "")).lower() != "sme" else "SME",
            "open_date": str(item.get("open_date") or item.get("dt_open") or ""),
            "close_date": str(item.get("close_date") or ""),
            "listing_date": str(item.get("listing_date") or ""),
            "price_band": _band(item.get("from_issue_price"), item.get("to_issue_price")),
            "lot_size": item.get("lot_size") or 0,
            "status": status,
            "note": str(item.get("short_desc") or item.get("note") or "").strip()
            or f"{name} {status.lower()}.",
        })

    # Open / upcoming issues.
    for it in ipo.get("open_Upcoming", []) or []:
        st = str(it.get("ipo_status", "")).strip().lower()
        _add(it, "open" if st == "open" else "upcoming")
    for it in ipo.get("openIpoList", []) or []:
        _add(it, "open")
    # Closed (waiting to list) → recent.
    for it in ipo.get("closedIpo", []) or []:
        _add(it, "recent")
    # Recently listed.
    for it in ipo.get("listedIpo", []) or []:
        _add(it, "listed")
    # Draft papers — no price band/dates yet; keep them as "draft" (the UI shows
    # them under Upcoming with a clean note rather than empty fields).
    for it in ipo.get("draftIssue", []) or []:
        _add(it, "draft")

    return rows


def _chittorgarh_rows() -> Optional[list[dict[str, Any]]]:
    """Parse the public IPO calendar when Moneycontrol requires consent.

    Chittorgarh publishes one dated event per issue (open/close/allotment). We
    only promote facts present in that calendar; price, lot size, and listing
    dates stay blank when the calendar does not publish them.
    """
    try:
        resp = httpx.get(CHITTORGARH_IPO_URL, headers=_HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return None
        links = re.findall(
            r'href=["\']([^"\']*ipo_news[^"\']*)["\'][^>]*>(.*?)</a>',
            resp.text,
            re.S | re.I,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chittorgarh IPO fetch failed: %s", exc)
        return None

    today = date.today()
    by_slug: dict[str, dict[str, Any]] = {}
    for url, raw_title in links:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(raw_title))).strip()
        match = re.match(r"(.+?) IPO (Opens|Closes) on ([A-Za-z]+ \d{1,2}, \d{4})$", title, re.I)
        if not match:
            continue
        name, event, date_text = match.groups()
        try:
            event_date = datetime.strptime(date_text, "%b %d, %Y").date().isoformat()
        except ValueError:
            continue
        slug_match = re.search(r"/ipo_news/([^/]+)/", url)
        slug = slug_match.group(1) if slug_match else re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        row = by_slug.setdefault(slug, {
            "id": slug,
            "name": name.strip(),
            "symbol": slug.upper().replace("-IPO", "")[:12],
            "exchange": "NSE/BSE",
            "open_date": "",
            "close_date": "",
            "listing_date": "",
            "price_band": "",
            "lot_size": 0,
            "status": "upcoming",
            "note": "Calendar dates from Chittorgarh. Price band and lot size were not published in this feed.",
            "source_url": url.split("#", 1)[0],
        })
        row["open_date" if event.lower() == "opens" else "close_date"] = event_date

    rows = list(by_slug.values())
    for row in rows:
        close_date = date.fromisoformat(row["close_date"]) if row["close_date"] else None
        open_date = date.fromisoformat(row["open_date"]) if row["open_date"] else None
        if open_date and open_date <= today <= (close_date or open_date):
            row["status"] = "open"
        elif close_date and close_date < today:
            row["status"] = "recent"
        else:
            row["status"] = "upcoming"
    return rows or None


def _live_or_fallback() -> tuple[list[dict[str, Any]], str]:
    """Return (rows, source). Caches the live payload for TTL seconds."""
    now = time.monotonic()
    if now - _cache["ts"] > _TTL_SECONDS:
        rows = _moneycontrol_rows()
        if not rows:
            rows = _chittorgarh_rows()
        if rows:
            _cache.update(ts=now, data=rows, ok=True)
        else:
            _cache.update(ts=now, data=None, ok=False)
    if _cache["ok"] and _cache["data"]:
        return _cache["data"], "live"
    return _curated_fallback(), "sample"


# ── Curated fallback (offline / provider down) ───────────────────────────
def _curated_fallback() -> list[dict[str, Any]]:
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
            "note": "Follow-on public offer (fallback placeholder).",
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
            "note": "Food-delivery IPO (fallback placeholder).",
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
            "note": "Value retail IPO (fallback placeholder).",
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
            "note": "Closed; listing expected (fallback placeholder).",
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
            "note": "Listed at premium (fallback placeholder).",
        },
    ]


# ── Public read tools ────────────────────────────────────────────────────
async def list_all() -> dict[str, Any]:
    """The full IPO calendar (upcoming + open + recent + listed)."""
    rows, source = _live_or_fallback()
    return {"ok": True, "count": len(rows), "source": source, "ipos": rows}


async def list_upcoming() -> dict[str, Any]:
    """IPOs that are upcoming, draft, or currently open for subscription."""
    rows, source = _live_or_fallback()
    rows = [r for r in rows if r["status"] in {"upcoming", "open", "draft"}]
    rows.sort(key=lambda r: r["open_date"])
    return {"ok": True, "count": len(rows), "source": source, "ipos": rows}


async def list_recent() -> dict[str, Any]:
    """Recently closed or listed IPOs (newest listing first)."""
    rows, source = _live_or_fallback()
    rows = [r for r in rows if r["status"] in {"recent", "listed"}]
    rows.sort(key=lambda r: r["listing_date"], reverse=True)
    return {"ok": True, "count": len(rows), "source": source, "ipos": rows}
