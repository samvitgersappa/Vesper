"""Catalyst Swing Trader — LLM catalyst analysis (DeepSeek V4 Flash).

The ONLY LLM stage in the pipeline. Takes the factor-composite top of the
funnel and asks the model for a structured catalyst verdict (positive /
negative / none) with urgency and confidence, returned as strict JSON.

Budget: the daily call counter (`catalyst_llm_usage`) is capped at
`CATALYST_TRADER_MAX_LLM_CALLS_PER_DAY` (default 65). Calls beyond the cap are
skipped (the candidate keeps its composite score with signal "none").

Endpoint is OpenAI-compatible `/chat/completions`, driven by env:
- CATALYST_LLM_BASE_URL  (default: DeepSeek API v1)
- CATALYST_LLM_API_KEY   (falls back to OPENCODE_GO_API_KEY)
- CATALYST_LLM_MODEL     (default: deepseek-v4-flash)

When no API key is configured the stage degrades honestly: every candidate is
recorded with signal "none" and the run is marked degraded — it never
fabricates an LLM verdict.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import text

from backend.modules.db import session_factory
from backend.modules.finance.catalyst import MAX_LLM_CALLS_PER_DAY
from backend.modules.finance.catalyst._util import ist_today, record_run

logger = logging.getLogger("vesper.finance.catalyst.llm")

LLM_BASE_URL = os.environ.get("CATALYST_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("CATALYST_LLM_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY", "")
LLM_MODEL = os.environ.get("CATALYST_LLM_MODEL", "deepseek-v4-flash")

_SYSTEM_PROMPT = (
    "You are the catalyst desk for a swing-trading strategy. Given a stock and "
    "its recent price/factor context, decide whether there is a tradable "
    "catalyst for a 10-day swing. Respond ONLY with JSON: "
    '{"signal":"positive"|"negative"|"none","urgency":0.0-1.0,'
    '"confidence":0.0-1.0,"rationale":"<one sentence>"}. '
    "Never invent facts; if nothing concrete, signal none."
)


def _ts() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")[:19]


async def _calls_used(date: str) -> int:
    async with session_factory()() as db:
        row = (await db.execute(
            text("SELECT calls_used FROM finance.catalyst_llm_usage WHERE date = :d"),
            {"d": date},
        )).first()
    return int(row.calls_used) if row else 0


async def _increment_usage(date: str) -> None:
    async with session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO finance.catalyst_llm_usage (date, calls_used) VALUES (:d, 1) "
                "ON CONFLICT (date) DO UPDATE SET calls_used = catalyst_llm_usage.calls_used + 1"
            ),
            {"d": date},
        )
        await db.commit()


async def _log_call(date: str, symbol: str, ok: bool, model: Optional[str], response: Optional[str]) -> None:
    try:
        async with session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO finance.catalyst_llm_calls "
                    "(ts, date, symbol, model, response_json, ok) VALUES (:t, :d, :s, :m, :r, :ok)"
                ),
                {"t": _ts(), "d": date, "s": symbol, "m": model, "r": response, "ok": ok},
            )
            await db.commit()
    except Exception:  # pragma: no cover - audit logging never fails the stage
        pass


def _parse_verdict(text: str) -> Optional[dict]:
    """Extract the JSON verdict from an OpenAI-compatible response."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("choices"):
        content = data["choices"][0].get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except Exception:
            return None
    return None


async def _recent_news(symbol: str, limit: int = 5) -> list[str]:
    """Headline text for `symbol` from the persisted catalyst_news table."""
    try:
        from backend.modules.finance.catalyst.news import news_for_symbol

        date = ist_today()
        items = await news_for_symbol(date, symbol, limit=limit)
        out = []
        for it in items:
            title = (it.get("title") or "").strip()
            source = (it.get("source") or "").strip()
            out.append(f"{title} ({source})" if source and title else (title or source))
        return out
    except Exception:  # noqa: BLE001 - news is never required for a verdict
        return []


async def classify_catalyst(symbol: str, context: dict) -> dict[str, Any]:
    """Ask DeepSeek V4 Flash for a structured catalyst verdict for `symbol`.

    Honors the daily call budget. Returns a dict always containing
    `signal` (positive|negative|none) and the raw LLM fields when available.
    """
    date = ist_today()
    default = {"symbol": symbol, "signal": "none", "urgency": 0.0, "confidence": 0.0, "rationale": ""}

    if not LLM_API_KEY:
        return default

    used = await _calls_used(date)
    if used >= MAX_LLM_CALLS_PER_DAY:
        logger.info("catalyst LLM daily budget reached (%d/%d); skipping %s", used, MAX_LLM_CALLS_PER_DAY, symbol)
        return default

    prompt = (
        f"Stock: {symbol}\n"
        f"Context: {json.dumps(context)}\n"
    )
    news = await _recent_news(symbol)
    if news:
        prompt += "Recent news headlines:\n" + "\n".join(f"- {n}" for n in news) + "\n"
    prompt += "Assess the swing-trade catalyst."
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 160,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:  # noqa: BLE001 - degraded call, not a failure
        await _log_call(date, symbol, ok=False, model=LLM_MODEL, response=str(exc)[:500])
        logger.warning("catalyst LLM call failed for %s: %s", symbol, exc)
        return default

    await _increment_usage(date)
    verdict = _parse_verdict(json.dumps(body))
    await _log_call(date, symbol, ok=bool(verdict), model=LLM_MODEL, response=json.dumps(body)[:4000])

    if not verdict or verdict.get("signal") not in {"positive", "negative", "none"}:
        return default
    return {
        "symbol": symbol,
        "signal": verdict["signal"],
        "urgency": float(verdict.get("urgency", 0.0)),
        "confidence": float(verdict.get("confidence", 0.0)),
        "rationale": str(verdict.get("rationale", ""))[:500],
    }


async def analyze_funnel(candidates: list[dict], date: str) -> list[dict]:
    """Run the LLM catalyst stage over the funnel; returns annotated candidates.

    Updates catalyst_scores.catalyst_json / catalyst_signal / llm_analyzed.
    """
    results = []
    for c in candidates:
        verdict = await classify_catalyst(c["symbol"], c)
        c.update(verdict)
        c["llm_analyzed"] = True
        results.append(c)

    async with session_factory()() as db:
        for c in results:
            await db.execute(
                text(
                    "UPDATE finance.catalyst_scores SET "
                    "catalyst_json = :cj, catalyst_signal = :cs, llm_analyzed = :la "
                    "WHERE date = :d AND symbol = :s"
                ),
                {
                    "cj": json.dumps({k: c.get(k) for k in ("signal", "urgency", "confidence", "rationale")}),
                    "cs": c.get("signal", "none"),
                    "la": True,
                    "d": date,
                    "s": c["symbol"],
                },
            )
        await db.commit()

    analyzed = sum(1 for c in results if c.get("llm_analyzed"))
    positive = sum(1 for c in results if c.get("signal") == "positive")
    await record_run("catalyst_llm", "ok", f"{analyzed} analyzed, {positive} positive", rows=analyzed)
    return results
