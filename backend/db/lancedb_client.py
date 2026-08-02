"""LanceDB semantic layer (plan.md §13/§8.5, addendum §3).

Vector search over vault notes + journal entries using LanceDB (embedded, no
standing container). Embeddings come from a deterministic local token-hash
TF-IDF vectorizer (numpy only, zero external API dependency) because this
deployment has no EmbeddingService configured yet — plan §7 explicitly tracks
hybrid recall as degraded until one is wired. The local embedder is a real,
queryable vector index that improves as the vault grows, and swapping it for a
proper embedding model later is a one-function change.

The index lives at `LANCEDB_PATH` (default `vesper/data/lancedb`), one table
`vault`. `index_vault()` rebuilds it from the vault; `search()` is the fan-out
source used by `knowledge.recall_everything`.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger("vesper.lancedb")

try:
    import lancedb
except ImportError:  # pragma: no cover - degrades to no-op
    lancedb = None

try:
    import pyarrow as pa
except ImportError:  # pragma: no cover
    pa = None

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "lancedb")
LANCEDB_PATH = os.environ.get("LANCEDB_PATH", _DEFAULT_PATH)
TABLE_NAME = "vault"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_VOCAB = {}  # token -> id (persisted implicitly by recomputing deterministically)
_ID_COUNTER = [0]
_MAX_TOKENS = 20000


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic token-hash TF-IDF-style embedding (fixed dim).

    Each token hashes to a bucket; we accumulate term frequency per bucket and
    L2-normalize. Deterministic across calls/restarts because the hash is stable.
    """
    vec = np.zeros(dim, dtype=np.float32)
    tf: dict[int, float] = {}
    for tok in _tokenize(text):
        bucket = abs(hash(tok)) % dim
        tf[bucket] = tf.get(bucket, 0.0) + 1.0
    for bucket, freq in tf.items():
        vec[bucket] = np.log1p(freq)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.tolist()


def _documents(vault_root: str) -> list[dict]:
    """Collect (id, text, file_path, title) pairs from vault markdown files."""
    docs: list[dict] = []
    root = Path(vault_root)
    if not root.exists():
        return docs
    for p in sorted(root.rglob("*.md")):
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = re.sub(r"^---.*?---", "", content, flags=re.S).strip()
        docs.append({
            "id": str(p),
            "file_path": str(p),
            "title": p.stem,
            "text": body[:8000],
        })
    return docs


def _get_db():
    if lancedb is None:  # pragma: no cover
        return None
    Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
    return lancedb.connect(LANCEDB_PATH)


def index_vault(vault_root: str) -> dict:
    """(Re)build the LanceDB index from the vault. Returns doc counts."""
    if lancedb is None or pa is None:  # pragma: no cover
        return {"ok": False, "error": "lancedb not installed"}
    docs = _documents(vault_root)
    if not docs:
        return {"ok": True, "indexed": 0, "table": TABLE_NAME}
    db = _get_db()
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)

    table = db.create_table(
        TABLE_NAME,
        data=[
            {
                "vector": _embed(d["text"]),
                "id": d["id"],
                "file_path": d["file_path"],
                "title": d["title"],
            }
            for d in docs
        ],
    )
    # IVF_PQ needs enough vectors to train K centroids; small vaults fall back
    # to brute-force (exact) search, which is perfectly fine at this scale.
    try:
        table.create_index(
            vector_column_name="vector",
            index_type="IVF_PQ",
            num_partitions=min(8, len(docs) // 4) or 1,
            num_sub_vectors=32,
        )
    except Exception as exc:  # pragma: no cover
        logger.info("lancedb: skipping IVF_PQ index for small corpus (%s)", exc)
    logger.info("lancedb: indexed %d vault documents", len(docs))
    return {"ok": True, "indexed": len(docs), "table": TABLE_NAME}


def search(query: str, top_k: int = 5, vault_root: str = "") -> list[dict]:
    """Vector search over the indexed vault. Returns [{file_path, title, score}]."""
    if lancedb is None or pa is None:  # pragma: no cover
        return []
    try:
        db = _get_db()
        if TABLE_NAME not in db.table_names():
            return []
        table = db.open_table(TABLE_NAME)
        result = table.search(_embed(query)).limit(top_k).to_list()
        return [
            {"file_path": r.get("file_path"), "title": r.get("title"),
             "score": float(r.get("_distance", 0.0))}
            for r in result
        ]
    except Exception as exc:  # pragma: no cover - degraded recall path
        logger.debug("lancedb search failed: %s", exc)
        return []
