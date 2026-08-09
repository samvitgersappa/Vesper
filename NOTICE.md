# Third-Party Notices

Vesper is MIT-licensed. This repository uses or integrates with third-party
software and services that retain their own terms and licenses.

## Runtime Integrations

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) is installed
  separately and is not vendored in this repository. Consult its repository for
  its license and terms.
- [Model Context Protocol](https://modelcontextprotocol.io/) is used for the
  Hermes-to-module interface.
- [FastMCP](https://github.com/jlowin/fastmcp), FastAPI, SQLAlchemy, Alembic,
  APScheduler, Redis, PostgreSQL, DuckDB, LanceDB, pandas, NetworkX, and
  yfinance are runtime dependencies. Their licenses are provided by their
  respective distributions and package metadata.
- [Next.js](https://github.com/vercel/next.js), React, and D3 are used by the
  frontend and retain their respective licenses.
- [Quartz](https://github.com/jackyzha0/quartz) is cloned during the optional
  Quartz container build; it is not copied into this repository.

## External Services

OpenCode Go, Telegram, GitHub, yfinance data sources, NSE data sources, and
optional fallback providers are external services. Their availability, terms,
pricing, rate limits, and data licenses are separate from Vesper's MIT license.
Operators are responsible for complying with those terms.

This notice is informational and does not replace the license files distributed
by third-party components.
