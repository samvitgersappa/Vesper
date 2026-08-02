"""Vault → LanceDB index job (plan.md §13, addendum §3).

Rebuilds the vector index over the vault so `knowledge.recall_everything` has a
real semantic fan-out source. Runs nightly after the Knowledge Architect pass so
new/changed notes from the day are indexed by morning.
"""

from __future__ import annotations

import logging
import os

from backend.modules.knowledge.logic import vault_root

logger = logging.getLogger("vesper.automation.lancedb")


async def index_vault_semantic() -> dict:
    """Rebuild the LanceDB index from the vault."""
    from backend.db.lancedb_client import index_vault

    root = os.environ.get("HERMES_VAULT_PATH", "") or str(vault_root())
    if not root or not os.path.isdir(root):
        logger.info("index_vault_semantic: no vault at %s — no-op", root)
        return {"ok": True, "indexed": 0, "note": "no vault"}
    result = index_vault(root)
    logger.info("index_vault_semantic: %s", result)
    return result
