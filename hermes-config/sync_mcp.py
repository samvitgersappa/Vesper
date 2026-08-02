"""Sync Vesper MCP servers into Hermes' ~/.hermes/config.yaml.

Called by start.sh (§6). Reads hermes-config/mcp_servers.json (a template whose
VENV_PYTHON / REPO_ROOT placeholders are resolved against this checkout), then
merges each server into the `mcp_servers:` block of the Hermes config,
preserving any servers Hermes already has (echo-mcp, aegis, etc.) and only
adding/refreshing the eight Vesper module servers.

Idempotent: re-running replaces the Vesper servers with the current template,
never touches unrelated keys. Config is rewritten with PyYAML (block style) —
safe because Hermes reads plain YAML config.yaml; we only ever load+dump it.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "hermes-config" / "mcp_servers.json"
VENV_PYTHON = REPO / ".venv" / "bin" / "python"


def resolve(template: dict) -> dict:
    """Resolve VENV_PYTHON / REPO_ROOT placeholders to concrete values."""
    def _fix(v):
        if isinstance(v, str):
            return (
                v.replace("VENV_PYTHON", str(VENV_PYTHON))
                .replace("REPO_ROOT", str(REPO))
            )
        if isinstance(v, dict):
            return {k: _fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_fix(x) for x in v]
        return v

    return _fix(template)


def main(config_path: str) -> int:
    raw = TEMPLATE.read_text(encoding="utf-8")
    template = json.loads(raw)["mcpServers"]
    resolved = resolve(template)

    cfg_path = Path(config_path).expanduser()
    if not cfg_path.exists():
        print(f"error: {cfg_path} not found — is Hermes installed?", file=sys.stderr)
        return 1

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    servers = cfg.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
        cfg["mcp_servers"] = servers

    servers.update(resolved)

    tmp = cfg_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False), encoding="utf-8")
    shutil.move(str(tmp), str(cfg_path))

    print(f"synced {len(resolved)} Vesper MCP servers into {cfg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "~/.hermes/config.yaml"))
