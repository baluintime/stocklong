#!/usr/bin/env python3
"""CLI confluence scan: score the live F&O universe on both sides and print
the ranked scoreboard. Read-only - no orders, no position-store writes.

The stock list is pulled from the exchange's instrument master at startup;
nothing is hardcoded.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong import scanner
from stocklong.config import Config
from stocklong.runner import Engine

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    cfg = Config.load()
    engine = Engine(cfg)
    universe = engine.load_universe()
    print(f"scanning {len(universe)} F&O underlyings (live list from exchange)...\n")

    rows = []
    for i, entry in enumerate(universe, 1):
        symbol, key = entry["symbol"], entry["instrument_key"]
        print(f"\r  {i}/{len(universe)} {symbol:<16}", end="", flush=True)
        try:
            df_d = engine.history.daily(key, cfg.get("history.daily_lookback_days", 400))
            df_h = engine.history.hourly(key, cfg.get("history.hourly_lookback_days", 60))
            best = scanner.best_side(scanner.score_both_sides(symbol, key, df_d, df_h))
            rows.append(best)
        except Exception as exc:
            print(f"\r  {symbol}: ERROR {exc}")
    print("\r" + " " * 40 + "\r", end="")

    rows.sort(key=lambda r: r.score, reverse=True)
    top_n = int(cfg.get("scan.top_n", 25)) or len(rows)
    print(f"{'#':<4}{'SYMBOL':<16}{'SIDE':<7}{'SCORE':<7}{'CLOSE':<10}COMPONENTS")
    print("-" * 78)
    for i, r in enumerate(rows[:top_n], 1):
        c = r.components
        comps = (f"M{c['macro']:>2} TK{c['tk_state']+c['tk_cross']:>2} "
                 f"MACD{c['macd_state']+c['macd_cross']:>2} "
                 f"R{c['renko_bricks']+c['renko_hist']+c['renko_rising']:>2}")
        print(f"{i:<4}{r.symbol:<16}{r.side:<7}{r.score:<7}{r.close:<10.2f}{comps}")


if __name__ == "__main__":
    main()
