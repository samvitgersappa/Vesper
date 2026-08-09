# Security Policy

## Supported Versions

Security fixes are made against the latest `main` branch. This project is
primarily a self-hosted deployment, so operators must keep the host, Docker,
Python, Node.js, Caddy, and Hermes Agent updated.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Use a private GitHub
Security Advisory for this repository, or contact the repository maintainers
privately through GitHub.

Include:

- A clear description and impact.
- Reproduction steps or a minimal proof of concept.
- Affected commit, configuration, or deployment mode.
- Any proposed mitigation.

Do not include real API keys, Telegram tokens, personal vault content, database
dumps, or other private data in a report.

## Deployment Security Baseline

- Keep `.env`, Hermes state, vault content, and database files out of Git.
- Use a real hostname with HTTPS when exposing Caddy publicly.
- Keep Postgres, Redis, Quartz, and the API host port private.
- Keep Caddy Basic Auth enabled for public deployments.
- Use a least-privilege GitHub token for optional vault backups.
- Rotate any credential that is accidentally exposed.

See `DEPLOYMENT.md` for the full hardening guidance.
