"""Load and persist config.json (never write Telegram bot tokens to disk)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS: dict[str, Any] = {
    "timezone": "Asia/Hong_Kong",
    "data": {
        "brown_grid_drop_pct": 50,
        "scrape_interval_seconds": 10,
        "idle_poll_seconds": 60,
        "commit_every_seconds": 120,
        "checkpoints_minutes": [15, 10, 5, 1, 0],
        "venues": ["ST", "HV"],
        "monitor_lead_minutes": 20,
        "monitor_trail_minutes": 25,
        "max_wait_before_monitor_minutes": 45,
    },
    "strategy": {
        "min_odds": 3.5,
        "max_odds": 9.0,
        "bet_type": "win",
        "checkpoint": "T-1",
        "stake": 10,
    },
    "monte_carlo": {
        "initial_bankroll": 10000,
        "stake": 10,
        "race_days_per_year": 88,
        "races_per_year": 400,
        "simulations": 1000,
    },
    "telegram": {
        "enabled": False,
        "chat_id": "",
        "bot_token": "",
        "bet_type": "win",
        "checkpoint": "T-1",
        "min_odds": 3.5,
        "max_odds": 9.0,
        "min_drop_pct": 50,
    },
    "github": {
        "owner": "",
        "repo": "",
        "branch": "main",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or CONFIG_PATH
    data: dict[str, Any] = {}
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
    cfg = _deep_merge(DEFAULTS, data)
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_token:
        cfg["telegram"]["bot_token"] = env_token
    if env_chat:
        cfg["telegram"]["chat_id"] = env_chat
    return cfg


def public_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy of config with secrets stripped — safe to commit / expose on Pages."""
    data = deepcopy(cfg or load_config())
    if "telegram" in data:
        data["telegram"]["bot_token"] = ""
    return data


def save_config(cfg: dict[str, Any], path: Path | None = None) -> None:
    target = path or CONFIG_PATH
    payload = public_config(cfg)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def brown_grid_threshold(cfg: dict[str, Any]) -> float:
    return float(cfg.get("data", {}).get("brown_grid_drop_pct", 50))


def scrape_interval(cfg: dict[str, Any]) -> int:
    return max(5, int(cfg.get("data", {}).get("scrape_interval_seconds", 10)))
