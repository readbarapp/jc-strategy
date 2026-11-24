"""Race-day detection, high-frequency odds capture, results harvest."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import csv_store, gitops, telegram_notify
from .config import brown_grid_threshold, brown_hold_required, load_config, scrape_interval
from .hkjc_client import HKJCClient, Meeting
from .logger import log, log_exception
from .capture import best_tick_for_target, due_targets, in_tick_window
from .odds_math import (
    DEFAULT_CHECKPOINTS,
    checkpoint_label,
    brown_hold_seconds,
    held_brown,
    stored_grid,
    parse_odds,
    win_drop_pct,
)
from .race_events import (
    KEEP_ALIVE_MINUTES,
    MAX_DELAY_EXTEND_MINUTES,
    is_horse_scratched,
    is_meeting_off,
    is_race_off,
    is_race_resulted,
    post_times_shifted,
    race_is_over,
    should_extend_watch,
    should_write_runner,
)
from .status import load_status, write_status
from .timeutil import format_hk, minutes_until, now_hk, plus_minutes, to_hk, today_hk

CHECKPOINT_ORDER = {"T-15": 0, "T-10": 1, "T-5": 2, "T-1": 3, "T-0": 4}
DEFAULT_JOB_BUDGET_SECONDS = 330 * 60
_JOB_START = time.monotonic()


def mark_job_start() -> None:
    global _JOB_START
    _JOB_START = time.monotonic()


def job_seconds_used() -> float:
    return time.monotonic() - _JOB_START


def should_handoff(elapsed_seconds: float | None = None, budget_seconds: float | None = None) -> bool:
    """True when this Actions job should exit and start a successor before the 6h kill."""
    elapsed = job_seconds_used() if elapsed_seconds is None else elapsed_seconds
    if budget_seconds is None:
        budget_seconds = float(os.environ.get("HKJC_JOB_BUDGET_SECONDS") or DEFAULT_JOB_BUDGET_SECONDS)
    return elapsed >= float(budget_seconds)


def restore_monitor_state(
    meeting: Meeting,
) -> tuple[
    dict[tuple[int, int], float],
    set[tuple[int, int, str]],
    set[tuple[int, int]],
    dict[tuple[int, int, str], float],
]:
    """Reload today's snapshots so a continuation job does not recapture or re-alert."""
    checkpoint_odds: dict[tuple[int, int], float] = {}
    captured: set[tuple[int, int, str]] = set()
    alerted: set[tuple[int, int]] = set()
    written_minutes: dict[tuple[int, int, str], float] = {}
    rows = [
        row
        for row in csv_store.load_odds()
        if str(row.get("race_date")) == meeting.race_date and str(row.get("venue")) == meeting.venue
    ]
    rows.sort(
        key=lambda row: (
            int(float(row.get("race_no") or 0)),
            int(float(row.get("horse_no") or 0)),
            CHECKPOINT_ORDER.get(str(row.get("checkpoint") or ""), 99),
        )
    )
    by_horse: dict[tuple[int, int], dict[str, float]] = {}
    for row in rows:
        try:
            race_no = int(float(row.get("race_no") or 0))
            horse_no = int(float(row.get("horse_no") or 0))
        except (TypeError, ValueError):
            continue
        checkpoint = str(row.get("checkpoint") or "")
        if not race_no or not horse_no or not checkpoint:
            continue
        captured.add((race_no, horse_no, checkpoint))
        try:
            written_minutes[(race_no, horse_no, checkpoint)] = float(row.get("minutes_to_post"))
        except (TypeError, ValueError):
            pass
        win = parse_odds(row.get("win_odds"))
        if win is not None:
            by_horse.setdefault((race_no, horse_no), {})[checkpoint] = win
    for key, cps in by_horse.items():
        if "T-0" in cps and "T-1" in cps:
            checkpoint_odds[key] = cps["T-1"]
            continue
        sequence = [cps[name] for name in ("T-15", "T-10", "T-5", "T-1", "T-0") if name in cps]
        if len(sequence) >= 2:
            checkpoint_odds[key] = sequence[-2]
        elif sequence:
            checkpoint_odds[key] = sequence[-1]
    if captured:
        log(f"Restored {len(captured)} captured checkpoints from CSV for continuation")
    return checkpoint_odds, captured, alerted, written_minutes


def _handoff(meeting: Meeting) -> str:
    gitops.persist_and_push("data: handoff before Actions 6h limit")
    ok = gitops.dispatch_monitor("auto", meeting.race_date)
    msg = (
        "已接近 GitHub Actions 6 小時上限，已開下一段繼續監控"
        if ok
        else "已接近 6 小時上限；若未能自動續跑，半小時排程會接"
    )
    log(msg, level="WARN" if not ok else "INFO")
    write_status(
        state="idle",
        is_race_day=True,
        venue=meeting.venue,
        race_date=meeting.race_date,
        last_message=msg,
        last_sync=format_hk(now_hk()),
    )
    gitops.persist_and_push("status: monitor handoff")
    return "handoff"


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def _clear_race_capture(
    captured: set[tuple[int, int, str]],
    checkpoint_odds: dict[tuple[int, int], float],
    race_no: int,
) -> None:
    captured.difference_update({ck for ck in list(captured) if ck[0] == race_no})
    for key in [item for item in list(checkpoint_odds) if item[0] == race_no]:
        del checkpoint_odds[key]


def refresh_meeting_schedule(
    client: HKJCClient,
    meeting: Meeting,
    captured: set[tuple[int, int, str]],
    checkpoint_odds: dict[tuple[int, int], float],
) -> tuple[Meeting | None, bool]:
    """Re-read official postTime/status. True = meeting cancelled or vanished."""
    latest = client.fetch_meeting(meeting.race_date, meeting.venue)
    if latest is None or not latest.races or is_meeting_off(latest.status):
        log(
            f"Meeting {meeting.race_date} {meeting.venue} gone or off "
            f"(status={getattr(latest, 'status', '') or 'missing'})"
        )
        return latest, True
    old_by_no = {race.race_no: race for race in meeting.races}
    for race in latest.races:
        prev = old_by_no.get(race.race_no)
        if prev is None:
            continue
        if post_times_shifted(
            client.scheduled_datetime(meeting, prev),
            client.scheduled_datetime(latest, race),
        ):
            log(
                f"R{race.race_no} postTime {prev.post_time or '—'} → {race.post_time or '—'}; "
                "drop stale checkpoints and recapture"
            )
            csv_store.drop_odds_for_race(latest.race_date, latest.venue, race.race_no)
            _clear_race_capture(captured, checkpoint_odds, race.race_no)
        if is_race_off(race.status) and not is_race_off(prev.status):
            log(f"R{race.race_no} marked {race.status} — stop capturing this race")
    return latest, False


def refresh_stored_results(client: HKJCClient | None = None, threshold: float = 50.0) -> int:
    """Re-fetch official LocalResults for every race already in race_results.csv."""
    client = client or HKJCClient()
    existing = csv_store.load_results()
    races = sorted(
        {
            (
                str(row.get("race_date") or ""),
                str(row.get("venue") or ""),
                int(float(row.get("race_no") or 0)),
            )
            for row in existing
            if row.get("race_date") and row.get("venue") and row.get("race_no")
        }
    )
    all_rows: list[dict] = []
    for race_date, venue, race_no in races:
        try:
            rows = client.fetch_results(Meeting(race_date=race_date, venue=venue), race_no)
        except Exception as exc:
            log_exception(f"repair results {race_date} {venue} R{race_no}", exc)
            continue
        if rows:
            log(f"Repair results {race_date} {venue} R{race_no}: {len(rows)} runners")
            all_rows.extend(rows)
        time.sleep(0.35)
    if not all_rows:
        return 0
    added = csv_store.upsert_results(all_rows)
    csv_store.apply_official_sp(all_rows, threshold)
    csv_store.copy_to_docs()
    return added


def collect_results(client: HKJCClient, meeting: Meeting, threshold: float = 50.0) -> int:
    all_rows: list[dict] = []
    for race in meeting.races:
        if is_race_off(race.status) or is_meeting_off(meeting.status):
            log(f"Skip results R{race.race_no}: status={race.status or meeting.status or 'off'}")
            continue
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
    csv_store.apply_official_sp(all_rows, threshold)
    csv_store.copy_to_docs()
    return added


def restore_tick_bank(meeting: Meeting) -> dict[tuple[int, int], list[dict]]:
    bank: dict[tuple[int, int], list[dict]] = {}
    for row in csv_store.load_ticks():
        if str(row.get("race_date")) != meeting.race_date or str(row.get("venue")) != meeting.venue:
            continue
        try:
            race_no = int(float(row.get("race_no") or 0))
            horse_no = int(float(row.get("horse_no") or 0))
            minutes = float(row.get("minutes_to_post"))
        except (TypeError, ValueError):
            continue
        win = parse_odds(row.get("win_odds"))
        if not race_no or not horse_no or win is None:
            continue
        bank.setdefault((race_no, horse_no), []).append(
            {
                "minutes": minutes,
                "win": win,
                "pla": parse_odds(row.get("place_odds")),
                "ts": row.get("capture_timestamp") or "",
                "horse_no": horse_no,
                "horse_name": row.get("horse_name") or "",
                "scheduled": row.get("scheduled_time") or "",
            }
        )
    return bank


def snapshot_race(
    cfg: dict[str, Any],
    meeting: Meeting,
    race,
    runners,
    checkpoint_odds: dict[tuple[int, int], float],
    captured: set[tuple[int, int, str]],
    alerted: set[tuple[int, int]],
    tick_bank: dict[tuple[int, int], list[dict]] | None = None,
    written_minutes: dict[tuple[int, int, str], float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Record a 10s tick and emit checkpoints from the closest sample to each mark."""
    if is_race_off(getattr(race, "status", "")) or is_meeting_off(getattr(meeting, "status", "")):
        return [], []
    now = now_hk()
    post = HKJCClient.scheduled_datetime(meeting, race)
    if not post:
        return [], []
    minutes = minutes_until(post, now)
    if not in_tick_window(minutes):
        return [], []
    points = [int(x) for x in (cfg.get("data", {}).get("checkpoints_minutes") or DEFAULT_CHECKPOINTS)]
    threshold = brown_grid_threshold(cfg)
    hold_need = brown_hold_required(cfg)
    scheduled = post.strftime("%H:%M:%S")
    capture_ts = format_hk(now)
    bank = tick_bank if tick_bank is not None else {}
    written = written_minutes if written_minutes is not None else {}
    out: list[dict] = []
    tick_rows: list[dict] = []
    runner_status = getattr(race, "runner_status", {}) or {}
    due = due_targets(minutes, points)
    for runner in runners:
        status = getattr(runner, "status", "") or runner_status.get(runner.horse_no, "")
        win = parse_odds(runner.win_odds)
        pla = parse_odds(runner.place_odds)
        key = (race.race_no, runner.horse_no)
        if is_horse_scratched(status):
            stale = {ck for ck in captured if ck[0] == race.race_no and ck[1] == runner.horse_no}
            if stale:
                csv_store.drop_horse_odds(meeting.race_date, meeting.venue, race.race_no, runner.horse_no)
                captured.difference_update(stale)
                checkpoint_odds.pop(key, None)
            continue
        if not should_write_runner(status, win):
            continue
        tick = {
            "minutes": minutes,
            "win": win,
            "pla": pla,
            "ts": capture_ts,
            "horse_no": runner.horse_no,
            "horse_name": runner.horse_name,
            "scheduled": scheduled,
            "win_grid": stored_grid(runner.win_grid),
            "place_grid": stored_grid(runner.place_grid),
        }
        bank.setdefault(key, []).append(tick)
        tick_rows.append(
            {
                "race_date": meeting.race_date,
                "venue": meeting.venue,
                "race_no": race.race_no,
                "scheduled_time": scheduled,
                "capture_timestamp": capture_ts,
                "minutes_to_post": round(minutes, 3),
                "horse_no": runner.horse_no,
                "horse_name": runner.horse_name,
                "win_odds": win,
                "place_odds": "" if pla is None else pla,
                "hkjc_grid": stored_grid(runner.win_grid),
                "place_grid": stored_grid(runner.place_grid),
            }
        )
        for target in due:
            checkpoint = checkpoint_label(target)
            best = best_tick_for_target(bank[key], target)
            if not best:
                continue
            ck = (race.race_no, runner.horse_no, checkpoint)
            prev_m = written.get(ck)
            if ck in captured and prev_m is not None:
                if target == 0:
                    if float(best["minutes"]) >= prev_m:
                        continue
                elif abs(float(best["minutes"]) - target) >= abs(prev_m - target) - 1e-9:
                    continue
            elif ck in captured and prev_m is None and target != 0:
                continue
            prev = checkpoint_odds.get(key)
            drop = win_drop_pct(prev, best["win"]) if prev is not None else 0.0
            win_grid = stored_grid(best.get("win_grid"))
            place_grid = stored_grid(best.get("place_grid"))
            hold = brown_hold_seconds(bank[key], best)
            brown = held_brown(win_grid, drop, threshold, hold, hold_need)
            if checkpoint != "T-0":
                checkpoint_odds[key] = best["win"]
            captured.add(ck)
            written[ck] = float(best["minutes"])
            row = {
                "race_date": meeting.race_date,
                "venue": meeting.venue,
                "race_no": race.race_no,
                "scheduled_time": scheduled,
                "checkpoint": checkpoint,
                "capture_timestamp": best["ts"],
                "minutes_to_post": round(float(best["minutes"]), 3),
                "horse_no": runner.horse_no,
                "horse_name": best.get("horse_name") or runner.horse_name,
                "win_odds": best["win"],
                "place_odds": "" if best.get("pla") is None else best["pla"],
                "prev_win_odds": "" if prev is None else prev,
                "win_drop_pct": drop,
                "is_brown_grid": _bool_str(brown),
                "hkjc_grid": win_grid,
                "place_grid": place_grid,
                "brown_hold_seconds": hold,
            }
            out.append(row)
            alert_key = (race.race_no, runner.horse_no)
            if alert_key not in alerted and telegram_notify.should_alert(cfg, row):
                telegram_notify.send_message(cfg, telegram_notify.format_alert(cfg, row))
                alerted.add(alert_key)
    return out, tick_rows


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
    max_delay = int(cfg["data"].get("max_delay_extend_minutes", MAX_DELAY_EXTEND_MINUTES))
    start_at = min(posts) if posts else now
    end_at = plus_minutes(max(posts), trail) if posts else plus_minutes(now, 4 * 60)
    hard_stop = plus_minutes(max(posts), max_delay) if posts else plus_minutes(now, max_delay)
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
            if should_handoff():
                return _handoff(meeting)
            time.sleep(min(60, max(5, (first_watch - now_hk()).total_seconds())))

    checkpoint_odds, captured, alerted, written_minutes = restore_monitor_state(meeting)
    tick_bank = restore_tick_bank(meeting)
    monitored: list[int] = []
    last_commit = time.time()
    last_refresh = 0.0
    log(
        f"High-frequency monitor start {meeting.race_date} {meeting.venue} "
        f"interval={scrape_interval(cfg)}s until {format_hk(end_at)}"
    )

    while now_hk() <= end_at and now_hk() <= hard_stop:
        if should_handoff():
            return _handoff(meeting)
        cfg = load_config()
        interval = scrape_interval(cfg)
        idle = max(interval, int(cfg["data"].get("idle_poll_seconds", 60)))
        if time.time() - last_refresh >= 45:
            latest, cancelled = refresh_meeting_schedule(client, meeting, captured, checkpoint_odds)
            last_refresh = time.time()
            if cancelled:
                write_status(
                    state="running",
                    is_race_day=True,
                    venue=meeting.venue,
                    race_date=meeting.race_date,
                    last_message="馬會賽程取消或消失，停止抄賠率、改收賽果",
                    last_sync=format_hk(now_hk()),
                )
                break
            if latest:
                meeting = latest
        live_races = [
            race
            for race in meeting.races
            if not is_race_off(race.status) and not is_race_resulted(race.status)
        ]
        if not live_races:
            log("All remaining races cancelled or resulted — stop odds loop")
            break
        checkpoint_rows: list[dict] = []
        raw_ticks: list[dict] = []
        nearest = None
        for race in live_races:
            post = client.scheduled_datetime(meeting, race)
            delta = minutes_until(post, now_hk()) if post else None
            if delta is not None and (nearest is None or abs(delta) < abs(nearest)):
                nearest = delta
            if race_is_over(race.status, delta):
                continue
            if not in_tick_window(delta):
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
            snaps, ticks = snapshot_race(
                cfg,
                meeting,
                race,
                runners,
                checkpoint_odds,
                captured,
                alerted,
                tick_bank,
                written_minutes,
            )
            checkpoint_rows.extend(snaps)
            raw_ticks.extend(ticks)
            time.sleep(0.15)

        if raw_ticks:
            csv_store.upsert_ticks(raw_ticks)
        if checkpoint_rows:
            csv_store.upsert_odds(checkpoint_rows)
            log(f"Wrote {len(checkpoint_rows)} checkpoint rows from {len(raw_ticks)} ticks (races={monitored})")

        active_posts = [
            dt
            for race in live_races
            if (dt := client.scheduled_datetime(meeting, race))
        ]
        if active_posts:
            end_at = plus_minutes(max(active_posts), trail)
        if any(
            should_extend_watch(
                race.status,
                minutes_until(client.scheduled_datetime(meeting, race), now_hk())
                if client.scheduled_datetime(meeting, race)
                else None,
            )
            for race in live_races
        ):
            end_at = max(end_at, plus_minutes(now_hk(), KEEP_ALIVE_MINUTES))
        end_at = min(end_at, hard_stop)

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

        sleep_for = interval if nearest is not None and nearest <= 20 else idle
        time.sleep(client.recommended_sleep(sleep_for))

    log("Odds loop finished — harvesting official results")
    collect_results(client, meeting, brown_grid_threshold(cfg))
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
    written_minutes: dict[tuple[int, int, str], float] = {}
    tick_bank: dict[tuple[int, int], list[dict]] = {}
    rows: list[dict] = []
    ticks: list[dict] = []
    for race in meeting.races:
        if is_race_off(race.status):
            continue
        runners = client.fetch_win_place_odds(meeting, race.race_no)
        snaps, raw = snapshot_race(
            cfg,
            meeting,
            race,
            runners,
            checkpoint_odds,
            captured,
            alerted,
            tick_bank,
            written_minutes,
        )
        rows.extend(snaps)
        ticks.extend(raw)
        time.sleep(0.2)
    if ticks:
        csv_store.upsert_ticks(ticks)
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
    added = collect_results(client, meeting, brown_grid_threshold(cfg))
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


@dataclass(frozen=True)
class AutoPlan:
    """What a scheduled `auto` tick should do, given today's official post times."""

    action: str
    first_post: datetime | None = None
    last_post: datetime | None = None
    start_watch: datetime | None = None
    end_watch: datetime | None = None
    wait_minutes: float = 0.0


def plan_auto(
    now: datetime,
    posts: list[datetime],
    lead_minutes: int = 20,
    trail_minutes: int = 25,
    max_wait_minutes: int = 45,
) -> AutoPlan:
    """Decide from actual first/last postTime — never from a hardcoded ST/HV clock.

    GitHub Actions jobs time out at 6 hours, so a tick that is still far from
    first_watch must exit (`defer`) and let the next detector cron pick it up.
    """
    now = to_hk(now)
    if not posts:
        return AutoPlan(action="monitor")
    first = min(posts)
    last = max(posts)
    start_watch = plus_minutes(first, -int(lead_minutes))
    end_watch = plus_minutes(last, int(trail_minutes))
    if now > end_watch:
        return AutoPlan(
            action="results",
            first_post=first,
            last_post=last,
            start_watch=start_watch,
            end_watch=end_watch,
        )
    if now >= start_watch:
        return AutoPlan(
            action="monitor",
            first_post=first,
            last_post=last,
            start_watch=start_watch,
            end_watch=end_watch,
        )
    wait_min = (start_watch - now).total_seconds() / 60.0
    if wait_min <= max(0, int(max_wait_minutes)):
        return AutoPlan(
            action="monitor",
            first_post=first,
            last_post=last,
            start_watch=start_watch,
            end_watch=end_watch,
            wait_minutes=wait_min,
        )
    return AutoPlan(
        action="defer",
        first_post=first,
        last_post=last,
        start_watch=start_watch,
        end_watch=end_watch,
        wait_minutes=wait_min,
    )


def _status_if_changed(*, commit_message: str, **kwargs: Any) -> None:
    """Avoid a git commit every 30-minute idle poll when nothing meaningful changed."""
    prev = load_status()
    keys = ("state", "is_race_day", "venue", "race_date", "last_message")
    if all(k not in kwargs or prev.get(k) == kwargs.get(k) for k in keys):
        log("Status unchanged — skip commit")
        return
    write_status(**kwargs)
    gitops.persist_and_push(commit_message)


def _idle_no_meeting(race_date: str) -> str:
    msg = "今日香港無賽馬日"
    log(msg)
    _status_if_changed(
        state="idle",
        is_race_day=False,
        venue="",
        race_date=race_date,
        last_message=msg,
        last_sync=format_hk(now_hk()),
        commit_message="status: no HKJC meeting today",
    )
    return "idle"


def run_auto(cfg: dict[str, Any] | None = None, race_date: str | None = None) -> str:
    cfg = cfg or load_config()
    client = HKJCClient()
    now = now_hk()
    meeting = client.detect_today_meeting(race_date or today_hk())
    if not meeting:
        # Night meetings can finish after midnight HKT; the 00:20 harvest uses this path.
        if now.hour == 0 and not race_date:
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            log(f"No meeting on {today_hk()} — trying results for {yesterday}")
            return run_results(cfg, yesterday)
        return _idle_no_meeting(race_date or today_hk())

    posts = [p for p in (client.scheduled_datetime(meeting, r) for r in meeting.races) if p]
    lead = int(cfg["data"].get("monitor_lead_minutes", 20))
    trail = int(cfg["data"].get("monitor_trail_minutes", 25))
    max_wait = int(cfg["data"].get("max_wait_before_monitor_minutes", 45))
    plan = plan_auto(now, posts, lead, trail, max_wait)
    forced = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    if plan.action == "defer" and forced:
        log("手動觸發：即使第一場仍遠，亦進入監控等待")
        return run_monitor(cfg, meeting.race_date)

    if plan.action == "defer":
        first_txt = format_hk(plan.first_post, with_seconds=False) if plan.first_post else "?"
        watch_txt = format_hk(plan.start_watch, with_seconds=False) if plan.start_watch else "?"
        msg = (
            f"偵測到 {meeting.venue} 賽馬日，第一場 {first_txt}，"
            f"監控窗 {watch_txt} 開始；距離仍有 {plan.wait_minutes:.0f} 分鐘，稍後排程再啟動"
        )
        log(msg)
        _status_if_changed(
            state="idle",
            is_race_day=True,
            venue=meeting.venue,
            race_date=meeting.race_date,
            last_message=msg,
            last_sync=format_hk(now),
            commit_message="status: race day detected, waiting for first post time",
        )
        return "defer"

    if plan.action == "results":
        return run_results(cfg, meeting.race_date)

    if plan.first_post:
        log(
            f"Race day {meeting.race_date} {meeting.venue} first post "
            f"{format_hk(plan.first_post, with_seconds=False)} — start monitor"
        )
    return run_monitor(cfg, meeting.race_date)
