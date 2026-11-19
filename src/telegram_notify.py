"""Telegram Bot alerts for 落飛 / brown-grid events."""

from __future__ import annotations

import html
from typing import Any

import requests

from .logger import log, log_exception
from .odds_math import held_brown, parse_odds
from .schema import VENUE_NAMES
from .timeutil import format_hk, now_hk, weekday_zh

BET_LABELS = {
    "win": "只買獨贏",
    "place": "只買位置",
    "win_place": "獨贏 + 位置",
}


def _token(cfg: dict[str, Any]) -> str:
    return str(cfg.get("telegram", {}).get("bot_token") or "").strip()


def _chat_id(cfg: dict[str, Any]) -> str:
    return str(cfg.get("telegram", {}).get("chat_id") or "").strip()


def enabled(cfg: dict[str, Any]) -> bool:
    tg = cfg.get("telegram") or {}
    return bool(tg.get("enabled")) and bool(_token(cfg)) and bool(_chat_id(cfg))


def _checkpoint(cfg: dict[str, Any]) -> str:
    raw = str((cfg.get("telegram") or {}).get("checkpoint") or "T-1").strip().upper()
    if raw.isdigit():
        return f"T-{raw}"
    return raw or "T-1"


def send_message(cfg: dict[str, Any], text: str) -> bool:
    token, chat = _token(cfg), _chat_id(cfg)
    if not token or not chat:
        log("Telegram skipped: missing bot token or chat id", level="WARN")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        payload = response.json() if response.content else {}
        if response.ok and payload.get("ok"):
            log("Telegram message sent")
            return True
        log(f"Telegram API error: {response.status_code} {payload}", level="ERROR")
        return False
    except Exception as exc:
        log_exception("Telegram send failed", exc)
        return False


def send_test(cfg: dict[str, Any]) -> bool:
    stamp = format_hk(now_hk())
    tg = cfg.get("telegram") or {}
    text = (
        "✅ <b>HKJC 量化平台測試訊息</b>\n"
        f"連線正常 · {html.escape(stamp)} HKT\n"
        f"規則：{html.escape(BET_LABELS.get(str(tg.get('bet_type') or 'win'), '只買獨贏'))}"
        f" · {html.escape(_checkpoint(cfg))}"
        f" · 獨贏 {html.escape(str(tg.get('min_odds', 3.5)))}"
        f"–{html.escape(str(tg.get('max_odds', 9.0)))}"
    )
    return send_message(cfg, text)


def should_alert(cfg: dict[str, Any], row: dict[str, Any]) -> bool:
    """Same gate as strategy: chosen checkpoint + 獨贏啡格 + 獨贏賠率範圍."""
    if not enabled(cfg):
        return False
    if str(row.get("checkpoint") or "").upper() != _checkpoint(cfg):
        return False
    win = parse_odds(row.get("win_odds"))
    if win is None:
        return False
    tg = cfg.get("telegram") or {}
    drop = float(row.get("win_drop_pct") or 0)
    threshold = float(
        tg.get("min_drop_pct")
        if tg.get("min_drop_pct") not in (None, "")
        else (cfg.get("data") or {}).get("brown_grid_drop_pct", 50)
    )
    hold_need = float((cfg.get("data") or {}).get("brown_hold_seconds", 20) or 0)
    if not held_brown(
        row.get("hkjc_grid"),
        drop,
        threshold,
        row.get("brown_hold_seconds"),
        hold_need,
        row.get("is_brown_grid"),
    ):
        return False
    lo = float(tg.get("min_odds", 3.5))
    hi = float(tg.get("max_odds", 9.0))
    return lo <= float(win) <= hi


def format_alert(cfg: dict[str, Any], row: dict[str, Any]) -> str:
    venue = VENUE_NAMES.get(str(row.get("venue")), row.get("venue"))
    name = html.escape(str(row.get("horse_name") or ""))
    prev = row.get("prev_win_odds") or "—"
    win = row.get("win_odds") or "—"
    pla = row.get("place_odds") or "—"
    drop = row.get("win_drop_pct") or 0
    race_date = row.get("race_date")
    try:
        wd = weekday_zh()
    except Exception:
        wd = ""
    bet = BET_LABELS.get(str((cfg.get("telegram") or {}).get("bet_type") or "win"), "只買獨贏")
    hold = row.get("brown_hold_seconds")
    hold_txt = "" if hold in (None, "") else f" · 啡格持續 {html.escape(str(hold))}s"
    return (
        f"🚨 <b>落飛警報</b> · 🟤 啡格\n\n"
        f"📅 {html.escape(str(race_date))}（{wd}）{html.escape(str(venue))}\n"
        f"🏁 第 {html.escape(str(row.get('race_no')))} 場"
        f"  開跑 {html.escape(str(row.get('scheduled_time') or '—'))}\n"
        f"🐴 {html.escape(str(row.get('horse_no')))}. {name}\n"
        f"📉 獨贏 {html.escape(str(prev))} → <b>{html.escape(str(win))}</b>"
        f"  ({html.escape(str(drop))}%){hold_txt}\n"
        f"📍 位置 {html.escape(str(pla))}\n"
        f"🎯 {html.escape(bet)} · {html.escape(str(row.get('checkpoint')))}\n"
        f"⏰ {html.escape(str(row.get('capture_timestamp')))} HKT"
    )
