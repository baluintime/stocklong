#!/usr/bin/env python3
"""Run both blueprint screeners across the configured universe and print
signals without touching orders or the position store."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong.config import Config
from stocklong.runner import Engine
from stocklong.strategies import SignalAction

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    cfg = Config.load()
    engine = Engine(cfg)
    print(f"{'SYMBOL':<12} {'STRATEGY':<24} {'ACTION':<12} REASON")
    print("-" * 90)
    for entry in cfg.get("universe", []):
        symbol, key = entry["symbol"], entry["instrument_key"]
        try:
            df_daily = engine.history.daily(key, cfg.get("history.daily_lookback_days", 400))
            df_hourly = engine.history.hourly(key, cfg.get("history.hourly_lookback_days", 60))
        except Exception as exc:
            print(f"{symbol:<12} {'-':<24} {'ERROR':<12} {exc}")
            continue
        for signal in (
            engine.institutional.evaluate(symbol, df_daily, df_hourly),
            engine.renko.evaluate(symbol, df_daily),
        ):
            marker = ">>" if signal.action is SignalAction.ENTER_LONG else "  "
            print(f"{marker} {symbol:<10} {signal.strategy:<24} "
                  f"{signal.action.value:<12} {signal.reason}")


if __name__ == "__main__":
    main()
