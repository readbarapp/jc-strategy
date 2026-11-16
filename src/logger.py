"""Append-only Hong Kong time logger writing to logs/latest.log."""

from __future__ import annotations

import sys
from pathlib import Path

from .timeutil import format_hk, now_hk

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "latest.log"
MAX_LOG_CHARS = 400_000


def _trim(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    cut = text[-MAX_LOG_CHARS:]
    nl = cut.find("\n")
    if nl > 0:
        cut = cut[nl + 1 :]
    return "[log truncated]\n" + cut


def log(message: str, level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{format_hk(now_hk())} HKT [{level}] {message}"
    print(line, flush=True)
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    LOG_PATH.write_text(_trim(existing + line + "\n"), encoding="utf-8")


def log_exception(prefix: str, exc: BaseException) -> None:
    log(f"{prefix}: {type(exc).__name__}: {exc}", level="ERROR")
    sys.stdout.flush()
