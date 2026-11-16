"""Strict Asia/Hong_Kong (UTC+8) time helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HK_TZ = ZoneInfo("Asia/Hong_Kong")
TZ_NAME = "Asia/Hong_Kong"


def now_hk() -> datetime:
    return datetime.now(HK_TZ)


def to_hk(dt: datetime | None = None) -> datetime:
    if dt is None:
        return now_hk()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HK_TZ)
    return dt.astimezone(HK_TZ)


def today_hk() -> str:
    return now_hk().strftime("%Y-%m-%d")


def format_hk(dt: datetime | None = None, with_seconds: bool = True) -> str:
    stamp = to_hk(dt)
    fmt = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return stamp.strftime(fmt)


def iso_hk(dt: datetime | None = None) -> str:
    return to_hk(dt).isoformat(timespec="seconds")


def parse_hk(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return to_hk(dt)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=HK_TZ)
        except ValueError:
            continue
    raise ValueError(f"unrecognised datetime: {value}")


def combine_hk(date_str: str, time_str: str) -> datetime:
    date_str = date_str.replace("/", "-")[:10]
    time_str = time_str.strip()
    if len(time_str) == 5:
        time_str += ":00"
    return parse_hk(f"{date_str} {time_str}")


def weekday_zh(dt: datetime | None = None) -> str:
    names = ["一", "二", "三", "四", "五", "六", "日"]
    return names[to_hk(dt).weekday()]


def minutes_until(target: datetime, now: datetime | None = None) -> float:
    return (to_hk(target) - to_hk(now)).total_seconds() / 60.0


def plus_minutes(dt: datetime, minutes: float) -> datetime:
    return to_hk(dt) + timedelta(minutes=minutes)
