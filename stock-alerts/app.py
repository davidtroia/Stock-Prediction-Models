"""
Stock alert app — notifies you when a stock is about to meet (or meets) your
criteria.

Usage:
    python app.py --once                 # one pass, then exit (ideal for cron)
    python app.py --loop --interval 300  # poll every 5 minutes
    python app.py --once --dry-run       # print to console instead of Telegram
    python app.py --list-rule-types      # show supported rule types

Config is read from config.yaml (override with --config). Telegram credentials
come from the environment (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) or the config
file; the environment wins.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import yaml

import rules as R
from notifier import build_notifier, format_signal
from state import AlertState


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        sys.exit(f"Config file not found: {path} (copy config.example.yaml to config.yaml)")
    with open(path) as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("settings", {})
    cfg.setdefault("watch", [])
    return cfg


def resolve_settings(cfg: dict, cli) -> dict:
    s = dict(cfg.get("settings", {}))
    # Environment overrides config for secrets.
    s["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", s.get("telegram_bot_token", ""))
    s["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", s.get("telegram_chat_id", ""))
    s.setdefault("channel", "telegram")
    s.setdefault("cooldown_minutes", 60)
    s.setdefault("history_period", "1y")
    s.setdefault("state_file", "state.json")
    if cli.dry_run:
        s["channel"] = "console"
    return s


def within_market_hours(settings: dict) -> bool:
    """Optional weekday 09:30-16:00 US/Eastern gate (best-effort, no tz deps)."""
    if not settings.get("market_hours_only"):
        return True
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone.utc)  # fall back to UTC if tz data missing
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def run_once(cfg: dict, settings: dict, notifier, state: AlertState) -> int:
    from datafeed import build_market_data  # lazy import (needs yfinance)

    sent = 0
    for entry in cfg["watch"]:
        symbol = entry.get("symbol")
        rule_list = entry.get("rules", [])
        if not symbol or not rule_list:
            continue
        md = build_market_data(symbol, period=settings["history_period"])
        if md is None:
            continue
        for sig in R.evaluate(md, rule_list):
            if not state.should_send(sig):
                continue
            text = format_signal(sig)
            if notifier.send(text):
                state.record(sig)
                sent += 1
    state.save()
    return sent


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Stock alert notifier")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument("--loop", action="store_true", help="poll continuously")
    p.add_argument("--interval", type=int, default=300, help="seconds between polls in --loop mode")
    p.add_argument("--dry-run", action="store_true", help="print to console instead of sending")
    p.add_argument("--list-rule-types", action="store_true")
    cli = p.parse_args(argv)

    if cli.list_rule_types:
        print("Supported rule types:")
        for t in R.supported_types():
            print(f"  - {t}")
        return 0

    if not cli.once and not cli.loop:
        cli.once = True  # default to a single pass

    cfg = load_config(cli.config)
    settings = resolve_settings(cfg, cli)
    notifier = build_notifier(settings["channel"], settings)
    state = AlertState(settings["state_file"], cooldown_minutes=settings["cooldown_minutes"])

    def one_pass():
        if not within_market_hours(settings):
            print("[info] outside market hours; skipping pass")
            return
        n = run_once(cfg, settings, notifier, state)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{stamp}] pass complete via {notifier.channel}: {n} notification(s) sent")

    if cli.once:
        one_pass()
        return 0

    print(f"[info] polling every {cli.interval}s (Ctrl-C to stop)")
    try:
        while True:
            one_pass()
            time.sleep(cli.interval)
    except KeyboardInterrupt:
        print("\n[info] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
