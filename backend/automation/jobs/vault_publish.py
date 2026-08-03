"""Vault Backup & Publish (addendum §7, plan §12).

Daily 00:15 IST plain worker:
1. `git add/commit/push` the Obsidian vault to the private GitHub repo
   (`VAULT_GIT_REMOTE` in the environment). This alone gives "second brain on
   any device" via GitHub's own app — private repo, free.
2. Rebuild the Quartz static site and refresh the Caddy-served copy.

The Quartz build itself runs inside the `vesper-quartz` container (which has
Node). The worker has no Node, so step 2 triggers the container's `POST
/rebuild` endpoint (`QUARTZ_TRIGGER_URL`). Both steps are optional by config:
with no remote and no trigger the job is a successful no-op that logs why.
Never fail the worker.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("vesper.automation.vault")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _git(cwd: str, *args: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", cwd, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return True
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        logger.warning("git %s in %s failed: %s", args[0], cwd, exc.stderr[-400:])
        return False


def vault_backup_publish() -> dict:
    """Push vault to private GitHub repo + rebuild/serve Quartz if configured."""
    result: dict = {"ok": True, "git_pushed": False, "quartz_rebuilt": False}

    vault = os.environ.get("HERMES_VAULT_PATH", "").strip()
    # Remote resolution: VAULT_GIT_REMOTE (full URL, explicit) takes precedence;
    # otherwise VAULT_REPO_URL + GH_PAT (start.sh/.env.example convention) is
    # composed into an authenticated HTTPS remote.
    remote = os.environ.get("VAULT_GIT_REMOTE", "").strip()
    if not remote:
        repo_url = os.environ.get("VAULT_REPO_URL", "").strip()
        pat = os.environ.get("GH_PAT", "").strip()
        if repo_url and pat:
            repo_url = repo_url.replace("https://", "").replace("git@github.com:", "").replace("ssh://git@github.com/", "")
            remote = f"https://{pat}@{repo_url}"
        else:
            remote = repo_url
    if vault and remote and os.path.isdir(vault):
        _git(vault, "add", "-A")
        _git(vault, "commit", "-m", f"vault sync {_now().isoformat()}", "--allow-empty")
        pushed = _git(vault, "push", "origin", "HEAD")
        result["git_pushed"] = pushed
    else:
        logger.info("vault_backup_publish: git step skipped (remote unset)")

    quartz = os.environ.get("QUARTZ_TRIGGER_URL", "").strip()
    if quartz:
        try:
            req = urllib.request.Request(
                quartz, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read() or b"{}")
            if body.get("ok"):
                result["quartz_rebuilt"] = True
                result["quartz_detail"] = {
                    "exit_code": body.get("exitCode"),
                    "duration_ms": body.get("durationMs"),
                }
            else:
                logger.warning("quartz rebuild reported failure: %s", body.get("output", "")[-500:])
        except Exception as exc:  # pragma: no cover
            logger.warning("quartz rebuild trigger failed: %s", exc)
    else:
        logger.info("vault_backup_publish: quartz step skipped (QUARTZ_TRIGGER_URL unset)")

    return result
