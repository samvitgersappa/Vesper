"""Model-escalation rule (plan.md §14, open decision §19.1).

The one genuinely custom piece of logic in the model-routing layer. Everything
else is Hermes Agent's own provider system (`hermes model` / fallback chain).

Contract:
- Called BEFORE a turn that may need the stronger tier.
- Returns the model to use for that turn, or None to keep the default
  (hy3 via opencode-go).

First-pass heuristic (deliberately minimal — revise in one file):
- Escalate if assembled context would exceed ESCALATE_CONTEXT_TOKENS.
- Escalate if the capability category is `analyze` on the `finance` or `study`
  modules (deep reasoning over holdings / test scores).

This is a thin wrapper around a model-switch decision; the actual switch is
performed by the caller via Hermes Agent's model commands. Open decision
§19.1: thresholds are a first-pass heuristic, not yet tuned.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Thresholds (first-pass heuristics — §19.1 open decision) ────────────────
ESCALATE_CONTEXT_TOKENS = 40_000  # approx assembled context that needs a strong tier
DEFAULT_MODEL = "hy3"  # plan §14 primary, via opencode-go
STRONG_MODEL = "opencode-go/gpt-5.6-luna"  # stronger tier for long-context / deep analysis

# Capability categories that always escalate when targeting these modules.
ANALYZE_MODULES = {"finance", "study"}


@dataclass(frozen=True)
class TurnProfile:
    """What the caller knows about the upcoming turn."""

    assembled_context_tokens: int = 0
    capability: str = ""      # e.g. "analyze", "recall", "upsert"
    module: str = ""          # e.g. "finance", "study", "relationship"


def choose_model(profile: TurnProfile) -> str | None:
    """Return the model for this turn, or None to keep the default."""
    if profile.assembled_context_tokens >= ESCALATE_CONTEXT_TOKENS:
        return STRONG_MODEL
    if profile.capability == "analyze" and profile.module in ANALYZE_MODULES:
        return STRONG_MODEL
    return None  # keep DEFAULT_MODEL
