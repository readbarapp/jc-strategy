"""status.json consumed by the GitHub Pages live dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .timeutil import format_hk, iso_hk, now_hk, today_hk

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "status.json"
DOCS_STATUS = ROOT / "docs" / "status.json"


def load_status() -> dict[str, Any]:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "state": "idle",
        "hk_time": format_hk(now_hk()),
        "is_race_day": False,
        "venue": "",
        "race_date": today_hk(),
        "races_monitored_today": [],
        "last_sync": "",
        "last_message": "尚未啟動",
        "workflow": "hkjc_monitor",
        "error": "",
    }


def write_status(**kwargs: Any) -> dict[str, Any]:
    current = load_status()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    current["hk_time"] = format_hk(now_hk())
    current["updated_at"] = iso_hk(now_hk())
    text = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
    STATUS_PATH.write_text(text, encoding="utf-8")
    DOCS_STATUS.parent.mkdir(parents=True, exist_ok=True)
    DOCS_STATUS.write_text(text, encoding="utf-8")
    return current
