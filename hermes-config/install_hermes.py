"""Provision Hermes Agent for Vesper on a fresh machine.

Called by start.sh (§Hermes). On a brand-new VM this is the whole
"Hermes up and running" step. It:

1. Writes `~/.hermes/.env` with the secrets start.sh collected
   (OPENCODE_GO_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, …).
2. Merges `hermes-config/hermes.config.template.yaml` into
   `~/.hermes/config.yaml` (repo paths resolved to this checkout), preserving
   any keys Hermes itself manages (auth, pairing, session, etc.).
3. Runs `sync_mcp.py` to (re)register the 8 Vesper module MCP servers.
4. Installs the vesper-capture-router plugin into `~/.hermes/plugins/`.
5. Registers the reasoning cron jobs (Morning Brief, Daily Journal
   Questionnaire, Reviews, Knowledge Architect) with `hermes cron create`
   if they are not already present.
6. Ensures the skills/cron external_dirs point at this checkout.

Idempotent and safe to re-run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "hermes-config" / "hermes.config.template.yaml"
MCP_TEMPLATE = REPO / "hermes-config" / "mcp_servers.json"
SYNC_MCP = REPO / "hermes-config" / "sync_mcp.py"
PLUGIN_SRC = REPO / "hermes-config" / "plugins" / "vesper-capture-router"
CRON_SKILLS_DIR = REPO / "hermes-config" / "cron"
SKILLS_DIR = REPO / "hermes-config" / "skills"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CONFIG = HERMES_HOME / "config.yaml"
HERMES_ENV = HERMES_HOME / ".env"
PLUGIN_DST = HERMES_HOME / "plugins" / "vesper-capture-router"

# Hermes binary — prefer the venv path (works immediately after install, before
# ~/.local/bin is on PATH), fall back to the shell wrapper.
_HERMES_CANDIDATES = [
    HERMES_HOME / "hermes-agent" / "venv" / "bin" / "hermes",
    Path.home() / ".local" / "bin" / "hermes",
    Path("hermes"),  # let subprocess search PATH
]
HERMES_BIN: str = "hermes"
for _c in _HERMES_CANDIDATES:
    if _c.exists() or _c == Path("hermes"):
        HERMES_BIN = str(_c)
        break

# Reasoning jobs that must run through Hermes Agent (plan.md §12): each maps
# to a skill under hermes-config/cron/<name>/SKILL.md and an IST cron expr.
CRON_JOBS = [
    # (name, schedule, skill, deliver)
    ("vesper-morning-brief", "30 7 * * 1-5", "morning-brief", "telegram"),
    ("vesper-daily-journal-questionnaire", "30 21 * * *", "daily-journal-questionnaire", "telegram"),
    ("vesper-evening-review", "45 21 * * 1-5", "evening-review", "telegram"),
    ("vesper-weekly-review", "0 10 * * 0", "weekly-review", "telegram"),
    ("vesper-monthly-review", "0 10 1 * *", "monthly-review", "telegram"),
    ("vesper-knowledge-architect", "30 2 * * *", "knowledge-architect", "telegram"),
]


def log(msg: str) -> None:
    print(f"[hermes-provision] {msg}")


def log_warn(msg: str) -> None:
    print(f"[hermes-provision] WARN: {msg}")


def telegram_delivery_target() -> str:
    """Return Hermes's explicit Telegram target when one is configured.

    Scheduled delivery needs `telegram:<chat_id>`; bare `telegram` does not
    identify a destination in Hermes's cron runner. Keep the fallback for
    installs that intentionally do not configure a home channel.
    """
    values: dict[str, str] = {}
    project_env = REPO / ".env"
    if project_env.exists():
        for line in project_env.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    channel = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip() or values.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not channel:
        channel = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip() or values.get("TELEGRAM_ALLOWED_USERS", "").strip()
    return f"telegram:{channel.split(',')[0].strip()}" if channel else "telegram"


# ── 1. Secrets into ~/.hermes/.env ─────────────────────────────────────
def write_hermes_env(env_path: Path) -> None:
    """Copy the project .env values Hermes cares about into ~/.hermes/.env."""
    project_env = REPO / ".env"
    if not project_env.exists():
        log_warn(".env missing — no secrets to mirror")
        return
    project = {}
    for line in project_env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        project[k.strip()] = v.strip()

    # Keys Hermes reads at runtime (gateway / provider / memory).
    wanted = [
        "OPENCODE_GO_API_KEY", "GROQ_API_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL",
        "OPENAI_API_KEY",
    ]
    lines = []
    seen: set = set()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            k = ""
            if line and not line.startswith("#") and "=" in line:
                k = line.split("=", 1)[0].strip()
                seen.add(k)
                # Replace any wanted key whose project value is non-empty.
                if k in wanted and project.get(k):
                    continue  # re-added below with the fresh value
            lines.append(line)
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)

    for k in wanted:
        if project.get(k):
            lines.append(f"{k}={project[k]}")
    # Drop duplicate keys (keep the last occurrence = the fresh value above).
    merged: list[str] = []
    final_seen: set = set()
    for line in lines:
        k = ""
        if line and not line.startswith("#") and "=" in line:
            k = line.split("=", 1)[0].strip()
            if k in wanted and k in final_seen:
                continue  # already replaced with the fresh value
        if k:
            final_seen.add(k)
        merged.append(line)
    env_path.write_text("\n".join(merged) + "\n", encoding="utf-8")
    log(f"secrets mirrored into {env_path}")


# ── 2. Config template → ~/.hermes/config.yaml ─────────────────────────
def merge_config(template: Path, target: Path) -> None:
    """Merge the Vesper template into the Hermes config (template wins on
    conflicts, but keys Hermes manages on its own are preserved)."""
    raw = template.read_text(encoding="utf-8")
    raw = raw.replace("REPO_ROOT", str(REPO)).replace("VENV_PYTHON", str(REPO / ".venv" / "bin" / "python"))
    tpl = yaml.safe_load(raw) or {}

    if target.exists():
        cfg = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    else:
        cfg = {}
        target.parent.mkdir(parents=True, exist_ok=True)

    def _merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = v

    _merge(cfg, tpl)
    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False), encoding="utf-8")
    shutil.move(str(tmp), str(target))
    log(f"config.yaml merged from template ({target})")


# ── 3. MCP servers ─────────────────────────────────────────────────────
def sync_mcp() -> None:
    if not HERMES_HOME.is_dir():
        log_warn("hermes home missing — MCP sync skipped")
        return
    result = subprocess.run(
        [sys.executable, str(SYNC_MCP), str(CONFIG)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log(result.stdout.strip() or "MCP servers synced")
    else:
        log_warn(f"MCP sync failed: {result.stderr.strip()[:300]}")


# ── 4. Capture-router plugin ───────────────────────────────────────────
def install_plugin() -> None:
    if not PLUGIN_SRC.is_dir():
        log_warn("capture-router plugin source missing in repo")
        return
    PLUGIN_DST.parent.mkdir(parents=True, exist_ok=True)
    if PLUGIN_DST.exists():
        shutil.rmtree(PLUGIN_DST)
    shutil.copytree(PLUGIN_SRC, PLUGIN_DST)
    log(f"capture-router plugin installed → {PLUGIN_DST}")

    # Ensure it's enabled in config.yaml plugins.enabled
    if CONFIG.exists():
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        enabled = cfg.setdefault("plugins", {}).setdefault("enabled", [])
        if "vesper-capture-router" not in enabled:
            enabled.append("vesper-capture-router")
            CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False), encoding="utf-8")
            log("vesper-capture-router enabled in plugins.enabled")


# ── 5. Cron jobs ───────────────────────────────────────────────────────
def register_cron() -> None:
    """Register reasoning cron jobs if not already present."""
    try:
        existing = subprocess.run(
            [HERMES_BIN, "cron", "list"], capture_output=True, text=True, timeout=60,
        ).stdout
    except Exception:
        log_warn("`hermes cron list` failed — skipping cron registration (run start.sh again later)")
        return

    for name, schedule, skill, deliver in CRON_JOBS:
        if name in existing:
            log(f"cron job {name} already present")
            continue
        prompt = (
            f"You are Vesper's scheduled '{skill}' job. Load the "
            f"skill_view(name='{skill}') skill from the Vesper cron skills dir "
            f"and execute its instructions for today, fully autonomously. "
            f"Write any outputs through the Vesper MCP servers."
        )
        delivery = telegram_delivery_target() if deliver == "telegram" else deliver
        cmd = [
            HERMES_BIN, "cron", "create",
            schedule,
            prompt,
            "--name", name,
            "--deliver", delivery,
            "--skill", skill,
            "--workdir", str(REPO),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                log(f"cron job {name} registered ({schedule} → {delivery})")
            else:
                log_warn(f"cron job {name} failed: {result.stderr.strip()[:300]}")
        except Exception as exc:
            log_warn(f"cron job {name} raised: {exc}")


def main() -> int:
    write_hermes_env(HERMES_ENV)
    merge_config(TEMPLATE, CONFIG)
    sync_mcp()
    install_plugin()
    register_cron()
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
