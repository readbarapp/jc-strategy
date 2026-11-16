"""Commit and push collected data from GitHub Actions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import requests

from .csv_store import copy_to_docs
from .logger import log, log_exception
from .timeutil import format_hk, now_hk

ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def persist_and_push(message: str | None = None) -> bool:
    copy_to_docs()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        log("Not running in GitHub Actions — files saved locally, skip git push")
        return True
    _run(["git", "config", "user.name", "hkjc-monitor[bot]"])
    _run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    _run(
        [
            "git",
            "add",
            "data",
            "logs",
            "status.json",
            "docs/data",
            "docs/config.json",
            "docs/status.json",
            "docs/logs",
            "config.json",
        ]
    )
    diff = _run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        log("No data changes to commit")
        return True
    stamp = format_hk(now_hk())
    msg = message or f"data: sync HKJC odds {stamp} HKT"
    committed = _run(["git", "commit", "-m", msg])
    if committed.returncode != 0:
        log(f"git commit failed: {committed.stderr}", level="ERROR")
        return False
    branch = os.environ.get("GITHUB_REF_NAME") or "main"
    for attempt in range(1, 5):
        _run(["git", "pull", "--rebase", "origin", branch])
        pushed = _run(["git", "push", "origin", branch])
        if pushed.returncode == 0:
            log(f"Pushed data commit to {branch}")
            return True
        log(f"git push attempt {attempt} failed: {pushed.stderr}", level="WARN")
    log_exception("git push exhausted retries", RuntimeError("push failed"))
    return False


def dispatch_monitor(command: str = "auto", race_date: str | None = None) -> bool:
    """Start a new HKJC Monitor workflow so tracking can continue after this job exits.

    GitHub-hosted runners are killed at 6 hours. A workflow_dispatch from GITHUB_TOKEN
    is allowed to create a new run (unlike push events).
    """
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    token = os.environ.get("GITHUB_TOKEN") or ""
    ref = os.environ.get("GITHUB_REF_NAME") or "main"
    if not repo or not token:
        log("Cannot self-dispatch monitor: missing GITHUB_REPOSITORY or GITHUB_TOKEN", level="WARN")
        return False
    url = f"https://api.github.com/repos/{repo}/actions/workflows/hkjc_monitor.yml/dispatches"
    payload = {
        "ref": ref,
        "inputs": {
            "command": command or "auto",
            "race_date": race_date or "",
        },
    }
    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
    except Exception as exc:
        log_exception("workflow dispatch failed", exc)
        return False
    if response.status_code in {204, 201, 200}:
        log(f"Dispatched continuation workflow command={command} date={race_date or ''} ref={ref}")
        return True
    log(
        f"workflow dispatch HTTP {response.status_code}: {response.text[:300]}",
        level="ERROR",
    )
    return False
