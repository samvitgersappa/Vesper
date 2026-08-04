"""NSE/BSE trading holiday calendar.

All days when the Indian stock markets are closed. Add/remove dates as the
official NSE holiday calendar is published each year. Weekend checks happen
separately (paper_trade_eod only runs Mon-Fri already).

Lunar-based holidays (Holi, Id, Diwali) are estimated for 2026 — confirm exact
dates against the official NSE circular after publication.
"""

from datetime import date

# NSE trading holidays 2026. Format: YYYY-MM-DD.
# Lunar-based dates marked (EST) — confirm against NSE circular.
NSE_HOLIDAYS_2026: set[str] = {
    "2026-01-26",  # Republic Day
    "2026-02-19",  # Chatrapati Shivaji Maharaj Jayanti (Maharashtra)
    "2026-03-04",  # Mahashivratri
    "2026-03-20",  # Holi (EST — lunar)
    "2026-03-27",  # Id-ul-Fitr / Ramzan Id (EST — lunar)
    "2026-04-14",  # Dr Ambedkar Jayanti
    "2026-04-17",  # Good Friday
    "2026-05-01",  # Maharashtra Day / May Day
    "2026-05-22",  # Buddha Purnima (EST)
    "2026-06-03",  # Id-ul-Zuha / Bakrid (EST — lunar)
    "2026-07-06",  # Muharram (EST — lunar)
    "2026-08-15",  # Independence Day
    "2026-09-05",  # Ganesh Chaturthi (EST)
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-19",  # Diwali — Balipratipada (EST — lunar)
    "2026-10-20",  # Diwali — Laxmi Pujan (EST — lunar)
    "2026-11-05",  # Guru Nanak Jayanti
    "2026-11-14",  # Kartiki Ekadashi (EST — regional, NSE may stay open)
    "2026-12-25",  # Christmas
}


def is_market_holiday(d: date | None = None) -> bool:
    """Return True when the NSE/BSE is closed for a holiday at *d* (default: today IST)."""
    from datetime import datetime, timezone, timedelta

    if d is None:
        ist = timezone(timedelta(hours=5, minutes=30))
        d = datetime.now(ist).date()
    key = d.isoformat()
    return key in NSE_HOLIDAYS_2026


def is_trading_day(d: date | None = None) -> bool:
    """Return True when the NSE/BSE is open. Shorthand: not holiday AND not weekend."""
    from datetime import datetime, timezone, timedelta

    if d is None:
        ist = timezone(timedelta(hours=5, minutes=30))
        d = datetime.now(ist).date()
    if is_market_holiday(d):
        return False
    if d.weekday() >= 5:
        return False
    return True
