from backend.modules.finance.catalyst.scores import select_diversified_candidates


def _row(symbol: str, sector: str, score: float, stock: float = 0.8) -> dict:
    return {
        "symbol": symbol,
        "sector": sector,
        "composite_score": score,
        "stock_score": stock,
        "sector_score": 0.8,
    }


def test_funnel_spreads_first_pass_across_sectors():
    rows = [
        _row("AAA.NS", "BANK", 0.90),
        _row("AAB.NS", "BANK", 0.89),
        _row("AAC.NS", "BANK", 0.88),
        _row("XYZ.NS", "IT", 0.80),
        _row("PQR.NS", "AUTO", 0.79),
    ]

    selected = select_diversified_candidates(rows, limit=3)

    assert [row["symbol"] for row in selected] == ["AAA.NS", "XYZ.NS", "PQR.NS"]


def test_funnel_respects_sector_cap_when_filling_remaining_slots():
    rows = [
        _row("AAA.NS", "BANK", 0.90),
        _row("XYZ.NS", "IT", 0.80),
        _row("AAB.NS", "BANK", 0.79),
        _row("AAC.NS", "BANK", 0.78),
        _row("AAD.NS", "BANK", 0.77),
    ]

    selected = select_diversified_candidates(rows, limit=5, max_per_sector=2)

    assert len(selected) == 3
    assert sum(row["sector"] == "BANK" for row in selected) == 2
