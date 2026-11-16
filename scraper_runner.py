#!/usr/bin/env python3
"""HKJC monitor entrypoint used by GitHub Actions and local CLI.

Commands:
  auto            Detect race day, then monitor or harvest results
  monitor         High-frequency odds capture until the last local race
  results         Official dividends / finishing order
  once            Single odds snapshot
  test-telegram   Send a Telegram connectivity test
  demo-data       Regenerate sample historical CSVs for the dashboard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.logger import log, log_exception  # noqa: E402
from src.monitor import mark_job_start, run_auto, run_monitor, run_once, run_results  # noqa: E402
from src.status import write_status  # noqa: E402
from src.telegram_notify import send_test  # noqa: E402
from src.timeutil import format_hk, now_hk, today_hk  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HKJC GitHub-hosted racing desk")
    parser.add_argument(
        "command",
        nargs="?",
        default="auto",
        choices=["auto", "monitor", "results", "once", "test-telegram", "demo-data"],
    )
    parser.add_argument("--date", dest="race_date", default="", help="YYYY-MM-DD (Hong Kong)")
    args = parser.parse_args(argv)
    race_date = args.race_date.strip() or None
    cfg = load_config()
    mark_job_start()
    log(f"scraper_runner command={args.command} date={race_date or today_hk()} tz=Asia/Hong_Kong")
    write_status(state="running", last_message=f"command {args.command}", workflow="hkjc_monitor")
    try:
        if args.command == "test-telegram":
            ok = send_test(cfg)
            write_status(
                state="idle",
                last_sync=format_hk(now_hk()),
                last_message="Telegram 測試成功" if ok else "Telegram 測試失敗",
            )
            return 0 if ok else 2
        if args.command == "demo-data":
            from scripts.generate_sample_data import generate

            generate()
            write_status(state="idle", last_message="已產生示範數據", last_sync=format_hk(now_hk()))
            return 0
        if args.command == "monitor":
            run_monitor(cfg, race_date)
        elif args.command == "results":
            run_results(cfg, race_date)
        elif args.command == "once":
            run_once(cfg, race_date)
        else:
            run_auto(cfg, race_date)
        return 0
    except KeyboardInterrupt:
        log("Interrupted", level="WARN")
        write_status(state="idle", last_message="interrupted")
        return 130
    except Exception as exc:
        log_exception("scraper_runner crashed", exc)
        write_status(state="error", error=str(exc), last_message="runner error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
