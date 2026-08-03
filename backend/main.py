"""Vesper backend entrypoint.

Single FastAPI app; the entrypoint switches behavior by the APP_MODE env var:
- `api`: serve the web REST surface (backend/api/routers.py) + /health
- `worker`: run the plain-data APScheduler jobs (no LLM, no agent) + event
  subscribers (graph write adapter, hermes mirror, notification delivery)

Hermes Agent is a separate process and connects to this app's module MCP servers
over the network/local socket; it never imports this package.
"""

import os

APP_MODE = os.environ.get("APP_MODE", "api")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import router as api_router

# CORS for local development (Next.js dev server on :3000 calling the API on
# :8000). In production Caddy proxies the API same-origin, so this is inert —
# but broad allows are fine here because the API holds no cookies/sessions.
_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost,http://127.0.0.1",
).split(",")

app = FastAPI(title="Vesper", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _ALLOWED_ORIGINS if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "app_mode": APP_MODE}


def _run_worker() -> None:
    """Start the data scheduler + event subscribers (blocking)."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from backend.automation.scheduler import run

    run()


def main() -> None:
    """Entrypoint for `uvicorn backend.main:app` (api) or the worker process."""
    import uvicorn

    if APP_MODE == "worker":
        _run_worker()
        return
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
