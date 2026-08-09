# Contributing to Vesper

Thank you for contributing. Vesper is a personal-intelligence platform, so
changes should preserve data safety, deterministic module boundaries, and the
privacy of deployments.

## Before You Start

- Read `README.md`, `plan.md`, and `DEPLOYMENT.md`.
- Open an issue for a substantial feature or architectural change first.
- Never include `.env`, Hermes state, vault files, database dumps, API keys,
  Telegram tokens, personal data, or generated build artifacts in a patch.

## Development

```bash
./start.sh --no-web --no-hermes
set -a; source .env; set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-vesper}:${POSTGRES_PASSWORD:-change-me}@localhost:5432/${POSTGRES_DB:-vesper}"
export REDIS_URL="redis://localhost:6379/0"
VESPER_TESTING=1 .venv/bin/python -m pytest tests/
```

The integration suite expects Postgres and Redis to be running. Tests may write
temporary records; use `./start.sh --fresh` afterward if working against a
personal development database.

## Pull Requests

- Keep changes focused and explain the operational impact.
- Add or update tests for behavior changes.
- Run `bash -n start.sh`, `python -m compileall`, and the integration suite.
- Document new environment variables, schedules, external services, and
  migrations.
- Keep the Finance MCP read-only; finance writes belong in worker jobs.
- Do not claim external services or data sources are always available. Use the
  project's honest degraded-mode conventions.

## Commit Style

Use concise imperative commit subjects, for example:

```text
Add spending summary MCP tools
```

## License

By contributing, you agree that your contribution is provided under the MIT
License in `LICENSE`. Third-party components retain their own licenses.
