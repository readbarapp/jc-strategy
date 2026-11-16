"""Race-day detection, high-frequency odds capture, results harvest."""

from __future__ import annotations

import time
from typing import Any

from . import csv_store, gitops, telegram_notify
from .config import brown_grid_threshold, load_config, scrape_interval
from .hkjc_client import HKJCClient, Meeting
from .logger import log, log_exception
from .odds_math import is_brown_grid, match_checkpoint, parse_odds, win_drop_pct
from .status import write_status
from .timeutil import format_hk, minutes_until, now_hk, plus_minutes, today_hk


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def collect_results(client: HKJCClient, meeting: Meeting) -> int:
    all_rows: list[dict] = []
    for race in meeting.races:
        try:
            rows = client.fetch_results(meeting, race.race_no)
        except Exception as exc:
            log_exception(f"results R{race.race_no}", exc)
            continue
        if rows:
            log(f"Results R{race.race_no}: {len(rows)} runners")
            all_rows.extend(rows)
        time.sleep(0.4)
    if not all_rows:
        return 0
    added = csv_store.upsert_results(all_rows)
    csv_store.copy_to_docs()
    return added


def snapshot_race(
    cfg: dict[str, Any],
    meeting: Meeting,
    race,
    runners,
    checkpoint_odds: dict[tuple[int, int], float],
    captured: set[tuple[int, int, str]],
    alerted: set[tuple[int, int]],
) -> list[dict]:
    """Write one snapshot per official checkpoint.

    啡格 is vs the previous checkpoint (e.g. T-1 vs T-3), not vs the last 10s tick.
    """
    now = now_hk()
    post = HKJCClient.scheduled_datetime(meeting, race)
    if post:
        minutes = minutes_until(post, now)
        checkpoint = match_checkpoint(
            minutes, cfg.get("data", {}).get("checkpoints_minutes") or [15, 10, 5, 3, 1, 0]
        )
    else:
        checkpoint = "T-0"
    if not checkpoint:
        return []
    threshold = brown_grid_threshold(cfg)
    scheduled = post.strftime("%H:%M:%S") if post else (race.post_time or "")
    capture_ts = format_hk(now)
    out: list[dict] = []
    for runner in runners:
        win = parse_odds(runner.win_odds)
        pla = parse_odds(runner.place_odds)
        key = (race.race_no, runner.horse_no)
        ck = (race.race_no, runner.horse_no, checkpoint)
        if ck in captured:
            continue
        prev = checkpoint_odds.get(key)
        drop = win_drop_pct(prev, win) if prev is not None else 0.0
        brown = is_brown_grid(drop, threshold)
        if win is not None:
            checkpoint_odds[key] = win
        captured.add(ck)
        row = {
            "race_date": meeting.race_date,
            "venue": meeting.venue,
            "race_no": race.race_no,
            "scheduled_time": scheduled,
            "checkpoint": checkpoint,
            "capture_timestamp": capture_ts,
            "horse_no": runner.horse_no,
            "horse_name": runner.horse_name,
            "win_odds": "" if win is None else win,
            "place_odds": "" if pla is None else pla,
            "prev_win_odds": "" if prev is None else prev,
            "win_drop_pct": drop,
            "is_brown_grid": _bool_str(brown),
        }
        out.append(row)
        alert_key = (race.race_no, runner.horse_no)
        if alert_key not in alerted and telegram_notify.should_alert(cfg, win, drop):
            telegram_notify.send_message(cfg, telegram_notify.format_alert(row))
            alerted.add(alert_key)
    return out


def run_monitor(cfg: dict[str, Any] | None = None, race_date: str | None = None) -> str:
    cfg = cfg or load_config()
    client = HKJCClient()
    meeting = client.detect_today_meeting(race_date or today_hk())
    if not meeting:
        write_status(
            state="idle",
            is_race_day=False,
            venue="",
            race_date=race_date or today_hk(),
            last_message="今日香港無賽馬日",
            last_sync=format_hk(now_hk()),
        )
        gitops.persist_and_push("data: no HK race meeting today")
        return "idle"

    posts = []
    for race in meeting.races:
        dt = client.scheduled_datetime(meeting, race)
        if dt:
            posts.append(dt)
    now = now_hk()
    lead = int(cfg["data"].get("monitor_lead_minutes", 20))
    trail = int(cfg["data"].get("monitor_trail_minutes", 25))
    start_at = min(posts) if posts else now
    end_at = plus_minutes(max(posts), trail) if posts else plus_minutes(now, 4 * 60)
    first_watch = plus_minutes(start_at, -lead) if posts else now

    write_status(
        state="running",
        is_race_day=True,
        venue=meeting.venue,
        race_date=meeting.race_date,
        races_monitored_today=[],
        last_message=f"監控 {meeting.venue} {len(meeting.races)} 場",
        last_sync=format_hk(now),
        error="",
    )

    if now < first_watch:
        log(f"Waiting until {format_hk(first_watch)} HKT before high-frequency capture")
        while now_hk() < first_watch:
            time.sleep(min(60, max(5, (first_watch - now_hk()).total_seconds())))

    checkpoint_odds: dict[tuple[int, int], float] = {}
    captured: set[tuple[int, int, str]] = set()
    alerted: set[tuple[int, int]] = set()
    monitored: list[int] = []
    last_commit = time.time()
    log(
        f"High-frequency monitor start {meeting.race_date} {meeting.venue} "
        f"interval={scrape_interval(cfg)}s until {format_hk(end_at)}"
    )

    while now_hk() <= end_at:
        cfg = load_config()
        interval = scrape_interval(cfg)
        idle = max(interval, int(cfg["data"].get("idle_poll_seconds", 60)))
        tick_rows: list[dict] = []
        nearest = None
        for race in meeting.races:
            post = client.scheduled_datetime(meeting, race)
            if post:
                delta = minutes_until(post, now_hk())
                if nearest is None or abs(delta) < abs(nearest):
                    nearest = delta
            # skip races that finished more than 5 minutes ago
            if post and minutes_until(post, now_hk()) < -5:
                continue
            try:
                runners = client.fetch_win_place_odds(meeting, race.race_no)
            except Exception as exc:
                log_exception(f"odds R{race.race_no}", exc)
                continue
            if not runners:
                continue
            if race.race_no not in monitored:
                monitored.append(race.race_no)
            tick_rows.extend(
                snapshot_race(cfg, meeting, race, runners, checkpoint_odds, captured, alerted)
            )
            time.sleep(0.15)

        if tick_rows:
            csv_store.upsert_odds(tick_rows)
            log(f"Wrote {len(tick_rows)} odds rows (races={monitored})")

        write_status(
            state="running",
            is_race_day=True,
            venue=meeting.venue,
            race_date=meeting.race_date,
            races_monitored_today=monitored,
            last_message=f"已監控場次 {monitored or '—'}",
            last_sync=format_hk(now_hk()),
        )

        if time.time() - last_commit >= int(cfg["data"].get("commit_every_seconds", 120)):
            gitops.persist_and_push()
            last_commit = time.time()

        # Slow down when no race is within 20 minutes
        sleep_for = interval if nearest is not None and nearest <= 20 else idle
        time.sleep(sleep_for)

    log("Odds loop finished — harvesting official results")
    collect_results(client, meeting)
    write_status(
        state="idle",
        is_race_day=True,
        venue=meeting.venue,
        race_date=meeting.race_date,
        races_monitored_today=monitored,
        last_message="監控結束，已嘗試寫入官方賽果",
        last_sync=format_hk(now_hk()),
    )
    gitops.persist_and_push("data: close HKJC race day")
    return "completed"


def run_once(cfg: dict[str, Any] | None = None, race_date: str | None = None) -> str:
    cfg = cfg or load_config()
    client = HKJCClient()
    meeting = client.detect_today_meeting(race_date or today_hk())
    if not meeting:
        write_status(state="idle", is_race_day=False, last_message="無賽事可抓取")
        gitops.persist_and_push()
        return "idle"
    checkpoint_odds: dict[tuple[int, int], float] = {}
    captured: set[tuple[int, int, str]] = set()
    alerted: set[tuple[int, int]] = set()
    rows: list[dict] = []
    for race in meeting.races:
        runners = client.fetch_win_place_odds(meeting, race.race_no)
        rows.extend(snapshot_race(cfg, meeting, race, runners, checkpoint_odds, captured, alerted))
        time.sleep(0.2)
    if rows:
        csv_store.upsert_odds(rows)
    write_status(
        state="idle",
        is_race_day=True,
        venue=meeting.venue,
        race_date=meeting.race_date,
        last_sync=format_hk(now_hk()),
        last_message=f"單次快照 {len(rows)} 列",
    )
    gitops.persist_and_push("data: single odds snapshot")
    return "snapshot"


def run_results(cfg: dict[str, Any] | None = None, race_date: str | None = None) -> str:
    cfg = cfg or load_config()
    client = HKJCClient()
    meeting = client.detect_today_meeting(race_date or today_hk())
    if not meeting:
        log("No meeting for results harvest")
        write_status(state="idle", is_race_day=False, last_message="無賽果可收")
        gitops.persist_and_push()
        return "idle"
    added = collect_results(client, meeting)
    write_status(
        state="idle",
        is_race_day=True,
        venue=meeting.venue,
        race_date=meeting.race_date,
        last_sync=format_hk(now_hk()),
        last_message=f"賽果寫入 {added} 列",
    )
    gitops.persist_and_push("data: official race results")
    return "results"


def run_auto(cfg: dict[str, Any] | None = None, race_date: str | None = None) -> str:
    cfg = cfg or load_config()
    client = HKJCClient()
    meeting = client.detect_today_meeting(race_date or today_hk())
    if not meeting:
        # still try yesterday results in case night racing closed after midnight UTC
        return run_results(cfg, race_date)
    posts = [client.scheduled_datetime(meeting, r) for r in meeting.races]
    posts = [p for p in posts if p]
    now = now_hk()
    lead = int(cfg["data"].get("monitor_lead_minutes", 20))
    trail = int(cfg["data"].get("monitor_trail_minutes", 25))
    if posts:
        start_watch = plus_minutes(min(posts), -lead)
        end_watch = plus_minutes(max(posts), trail)
        if start_watch <= now <= end_watch:
            return run_monitor(cfg, meeting.race_date)
        if now > end_watch:
            return run_results(cfg, meeting.race_date)
        log(f"Race day {meeting.race_date} {meeting.venue} starts {format_hk(min(posts))} — waiting in monitor")
        return run_monitor(cfg, meeting.race_date)
    return run_monitor(cfg, meeting.race_date)
