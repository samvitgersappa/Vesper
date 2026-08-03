"""Deterministic capture routing for the Vesper second brain.

When a turn contains capture intent — "remember X", "note to self", "save
this", "don't let me forget", "log/spent <amount>", "did <workout>", "remind
me <date>" — this plugin guarantees the utterance reaches the Vesper
Knowledge module's single routing decision point (``knowledge.capture``),
regardless of whether the model chose to load the capture skill.

We fire on ``post_llm_call`` (once per turn, after the tool loop completes)
and inspect the turn's tool calls. If the agent already routed the capture
through an appropriate sink (``mcp__knowledge__capture`` itself, or a
journal/expense/reminder/relationship write), we do nothing. If capture
intent was present but nothing was routed, we dispatch
``mcp__knowledge__capture`` ourselves and append a note to the reply.

This is the deterministic backstop the ADDENDUM_SECOND_BRAIN.md §1
design assumed a skill would provide. It cannot be skipped by model
discretion.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Capture-intent detection
# ---------------------------------------------------------------------------

# Words/phrases that mark a standalone capture intent (ADDENDUM §1).
# Expense amounts ("300 on lunch", "spent 150") and workout phrasing
# ("did legs", "went for a run") are also signals.
_CAPTURE_RE = re.compile(
    r"(remember|note to self|don'?t let me forget|save this|save that|"
    r"save a note|note that|note this|log this|log that|spent|spend(ing)?|"
    r"bought|paid|on lunch|on the cab|on chai|did (upper|lower|legs|chest|"
    r"back|arms|shoulders|triceps|biceps|cardio|pull|push)|"
    r"went for a (run|walk|swim)|gym|workout|remind me|reminder|"
    r"i should|an idea|a fact|note:|remember:|plan to|"
    r"\bidea\b|\bideas\b|idea:|would be cool|maybe I should|"
    r"thinking of|want to build|want to try|want to read|should read)",
    re.IGNORECASE,
)

# Turn tool names that already handled the capture (so we don't double-capture).
_CAPTURE_SINKS = {
    "mcp__knowledge__capture",
    "mcp__journal__log_expense",
    "mcp__journal__log_workout",
    "mcp__journal__write_entry",
    "mcp__journal__update_entry",
    "mcp__journal__append_entry",
    "mcp__relationship__add_reminder",
    "mcp__calendar__create_reminder",
}

# ---------------------------------------------------------------------------
# Tool-call extraction from the turn's message history
# ---------------------------------------------------------------------------


def _iter_tool_names(messages: Optional[List[Any]]) -> Set[str]:
    """Collect every tool name that appears in the turn's message list."""
    names: Set[str] = set()
    if not messages:
        return names

    def _scan(obj: Any) -> None:
        if isinstance(obj, dict):
            # Anthropic-style: tool_use / tool_result content blocks
            ctype = obj.get("type")
            if ctype == "tool_use":
                nm = obj.get("name")
                if nm:
                    names.add(str(nm))
            if ctype == "tool_result":
                c = obj.get("content")
                if isinstance(c, str):
                    for m in re.findall(r'"name"\s*:\s*"([^"]+)"', c):
                        names.add(m)
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)
        elif isinstance(obj, str):
            # OpenAI/Responses-style tool_calls may be serialized in strings
            for m in re.findall(r'"name"\s*:\s*"([^"]+)"', obj):
                names.add(m)

    for msg in messages:
        _scan(msg)
        # Some providers put tool_calls in top-level keys
        for key in ("tool_calls", "tool_call", "function_calls", "function_call"):
            if isinstance(msg, dict):
                _scan(msg.get(key))
    return names


def _iter_vault_writes(messages: Optional[List[Any]]) -> Set[str]:
    """Collect vault markdown paths written by the agent this turn.

    The vault lives at ~/Documents/KnowledgeVault (OBSIDIAN_VAULT_PATH may
    override it). We look for write_file/patch/terminal calls whose inputs
    reference a path under that root. Returns a set of vault-relative paths.
    """
    vault = os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        str(Path.home() / "Documents" / "KnowledgeVault"),
    )
    root = Path(vault).expanduser()
    writes: Set[str] = set()

    def _scan(obj: Any) -> None:
        if isinstance(obj, dict):
            # write_file / patch calls carry the target path in inputs.
            name = obj.get("name") or ""
            if name in {"write_file", "patch", "append_file"}:
                for key in ("path", "file_path", "target"):
                    p = obj.get(key) or obj.get("input") or {}
                    if isinstance(p, str):
                        _maybe_add(p)
            # Some providers nest the raw tool call under "input".
            raw = obj.get("input")
            if isinstance(raw, dict):
                p = raw.get("path") or raw.get("file_path") or raw.get("target")
                if isinstance(p, str):
                    _maybe_add(p)
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)
        elif isinstance(obj, str):
            # Serialized tool calls in strings.
            for m in re.finditer(r'"path"\s*:\s*"([^"]+)"', obj):
                _maybe_add(m.group(1))

    def _maybe_add(p: str) -> None:
        try:
            path = Path(p).expanduser()
            if root not in [path, *path.parents]:
                return
            if path.suffix.lower() != ".md":
                return
            writes.add(str(path.relative_to(root)))
        except Exception:
            pass

    for msg in messages or []:
        _scan(msg)
    return writes


def _publish_knowledge_indexed(rel_paths: Set[str]) -> None:
    """Publish KnowledgeIndexed events so the worker creates graph nodes."""
    vault = os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        str(Path.home() / "Documents" / "KnowledgeVault"),
    )
    try:
        import redis as _redis
    except Exception:
        return
    client = _redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    root = Path(vault).expanduser()
    for rel in rel_paths:
        client.publish(
            "KnowledgeIndexed",
            json.dumps({"path": str(root / rel), "action": "vault_note"}),
        )


# ---------------------------------------------------------------------------
# Capture execution
# ---------------------------------------------------------------------------


def _run_capture(ctx, utterance: str, session_id: str) -> Optional[Dict[str, Any]]:
    """Dispatch knowledge.capture through the registry. Returns parsed result."""
    try:
        from tools.registry import registry
    except Exception as exc:  # pragma: no cover
        logger.warning("capture-router: registry import failed: %s", exc)
        return None

    try:
        raw = registry.dispatch(
            "mcp__knowledge__capture",
            {"utterance": utterance, "conversation_context": {}},
            parent_agent=getattr(ctx, "_agent", None),
        )
    except Exception as exc:
        logger.warning("capture-router: dispatch failed: %s", exc)
        return {"error": str(exc)}

    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    return None


def _append_router_note(base: str, result: Optional[Dict[str, Any]]) -> str:
    """Return a reply that reflects the routed store, appending a router note."""
    text = (base or "").rstrip()
    if not text:
        text = "Done."
    store = "?"
    if isinstance(result, dict):
        store = result.get("stored_in") or result.get("category") or store
        ref = result.get("ref_id") or result.get("path") or result.get("note")
        if store and ref:
            return f"{text}\n\n_router: captured as {store} ({ref})._"
        if store:
            return f"{text}\n\n_router: captured as {store}._"
        if "error" in result:
            return f"{text}\n\n_router: capture failed — {result['error']}._"
    return f"{text}\n\n_router: routed through knowledge.capture._"


def _log_router(
    session_id: str,
    task_id: str,
    utterance: str,
    result: Any,
    tools_used: List[str],
) -> None:
    """Append one audit line to ~/.hermes/logs/capture-router.log."""
    try:
        log_dir = Path(os.path.expanduser("~/.hermes/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "session_id": session_id,
            "task_id": task_id,
            "utterance": utterance,
            "result": result,
            "tools_used": tools_used,
        }
        with open(log_dir / "capture-router.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# post_llm_call hook
# ---------------------------------------------------------------------------


def _on_post_llm_call(
    user_message: Any = None,
    assistant_response: str = "",
    conversation_history: Optional[List[Any]] = None,
    session_id: str = "",
    task_id: str = "",
    **_: Any,
) -> Optional[str]:
    """Guarantee capture intent reaches knowledge.capture."""
    # Extract the raw text of the user's message.
    user_text = ""
    if isinstance(user_message, str):
        user_text = user_message
    elif isinstance(user_message, dict):
        # {'content': ...} or {'text': ...}
        user_text = user_message.get("text") or user_message.get("content") or ""
        if isinstance(user_text, list):
            user_text = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in user_text
            )
        else:
            user_text = str(user_text)

    if not user_text.strip():
        return None

    # Only act on turns with capture intent.
    if not _CAPTURE_RE.search(user_text):
        return None

    # If the agent already routed this through a sink tool, don't double-capture.
    used = _iter_tool_names(conversation_history)
    if used & _CAPTURE_SINKS:
        logger.debug(
            "capture-router: agent already routed via %s; skipping",
            sorted(used & _CAPTURE_SINKS),
        )
        return None

    # Dispatch knowledge.capture deterministically.
    try:
        from hermes_cli.plugins import get_plugin_manager

        manager = get_plugin_manager()
        ctx = getattr(manager, "_ctx_for_capture", None)
    except Exception:
        ctx = None

    result = _run_capture(ctx, user_text.strip(), session_id)

    # Log to a local audit file so the fix is verifiable end-to-end.
    _log_router(session_id, task_id, user_text.strip(), result, sorted(used))

    return _append_router_note(assistant_response, result)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    # Stash the context so the hook can dispatch tools (dispatch needs the
    # parent agent / registry, which is resolved lazily at call time).
    try:
        from hermes_cli.plugins import get_plugin_manager

        get_plugin_manager()._ctx_for_capture = ctx
    except Exception:
        pass
    logger.info("vesper-capture-router: registered post_llm_call hook")
