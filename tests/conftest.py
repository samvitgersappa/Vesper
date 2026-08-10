import os
from pathlib import Path

# Reveal the project-local .env (secrets, DB URL, vault path) so the
# integration suite connects to the real Postgres the same way the API and
# worker do. Without this, `DATABASE_URL` falls back to `vesper:change-me` and
# the whole test run impersonates nothing successfully.
_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_env, override=False)
    except Exception:  # pragma: no cover - dotenv missing in some CI images
        pass

os.environ.setdefault("VESPER_TESTING", "1")