"""Journal module vault file I/O helpers (plan.md §8.3).

Journal content is vault-backed: the markdown note at
`<vault>/00 Journal/YYYY/YYYY-MM-DD.md` is the source of truth and
`diary_entries` is a metadata layer over it. These helpers own every vault
read/write for the journal tools.

The `00 Journal/YYYY/YYYY-MM-DD.md` layout is the vault's native convention —
the knowledge module's capture routing (`knowledge.capture` → `_today_journal_path`)
writes the same path, so journaling and capture land in one note.
`_LEGACY_JOURNAL_DIR = "journal"` is kept only so old notes written to the
previous `journal/YYYY/MM/` layout are still discovered by readers.

Everything is defensive — no helper ever raises. Failures return error dicts so
the logic layer degrades gracefully when the vault is missing or unreadable.
"""

import os
import tempfile
from datetime import date
from pathlib import Path

DEFAULT_VAULT = "~/Documents/KnowledgeVault"

# Legacy layout written before the vault adopted `00 Journal/` (kept for reads).
_LEGACY_JOURNAL_DIR = "journal"


def vault_root() -> Path:
    """Resolve the vault root from env (default ~/Documents/KnowledgeVault)."""
    raw = os.environ.get("HERMES_VAULT_PATH", DEFAULT_VAULT)
    return Path(raw).expanduser().resolve()


def entry_path(d: date) -> Path:
    """Vault path for a journal entry: 00 Journal/YYYY/YYYY-MM-DD.md."""
    if isinstance(d, str):
        d = date.fromisoformat(d.strip()[:10])
    return vault_root() / "00 Journal" / f"{d:%Y}" / f"{d:%Y-%m-%d}.md"


def legacy_entry_path(d: date) -> Path:
    """Legacy path for a journal entry: journal/YYYY/MM/YYYY-MM-DD.md."""
    if isinstance(d, str):
        d = date.fromisoformat(d.strip()[:10])
    return vault_root() / _LEGACY_JOURNAL_DIR / f"{d:%Y}" / f"{d:%m}" / f"{d:%Y-%m-%d}.md"


def read_entry_file(d: date) -> dict:
    """Read the vault note for `d`. Returns content or an error dict.

    Checks the current `00 Journal/` layout first, then the legacy
    `journal/YYYY/MM/` layout, so old notes keep working after the switch.
    """
    p = entry_path(d)
    if not p.exists():
        legacy = legacy_entry_path(d)
        if legacy.exists():
            p = legacy
        else:
            return {
                "ok": False,
                "found": False,
                "path": str(entry_path(d)),
                "message": f"No journal entry for {d.isoformat()}",
            }
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        return {"ok": False, "found": True, "path": str(p), "message": str(exc)}
    return {
        "ok": True,
        "found": True,
        "path": str(p),
        "content": content,
        "word_count": len(content.split()),
    }


def write_entry_file(d: date, content: str, append: bool = False) -> dict:
    """Write (or append to) the vault note for `d`, atomically (temp + rename).

    Returns `{ok, path, appended, word_count}` or an error dict. Never raises.
    """
    p = entry_path(d)
    root = vault_root()
    if not root.exists():
        return {"ok": False, "path": str(p), "message": "vault missing"}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        return {"ok": False, "path": str(p), "message": str(exc)}

    existed = p.exists()
    if append and existed:
        try:
            existing = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - defensive
            return {"ok": False, "path": str(p), "message": str(exc)}
        combined = existing.rstrip() + "\n\n" + content.strip() + "\n"
    else:
        combined = content

    try:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".vesper-journal-tmp-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(combined)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:  # pragma: no cover - defensive
        return {"ok": False, "path": str(p), "message": str(exc)}

    return {
        "ok": True,
        "path": str(p),
        "appended": append and existed,
        "word_count": len(combined.split()),
    }
