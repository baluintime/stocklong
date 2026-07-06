#!/usr/bin/env python3
"""Live engine loop.

Runs one full blueprint cycle (exits -> entries) every hour during NSE market
hours (09:15-15:30 IST), and streams real-time LTPs for the underlyings and
any open option positions over the Upstox websocket in between.

Positions persist in SQLite across restarts and across days; each new day just
needs a fresh login (scripts/login.py) before starting this loop.
"""

import datetime as dt
import logging
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong.config import Config
from stocklong.data.realtime import LiveFeed
from stocklong.runner import Engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run_live")

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)


def market_is_open(now: dt.datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def main() -> None:
    cfg = Config.load()
    engine = Engine(cfg)

    keys = [e["instrument_key"] for e in cfg.get("universe", [])]
    keys += [p.option_key for p in engine.store.open_positions()]
    feed = None
    try:
        feed = LiveFeed(engine.auth, keys)
        feed.on_tick(lambda key, ltp: log.debug("tick %s = %s", key, ltp))
        feed.start()
        log.info("websocket feed started for %d instruments", len(keys))
    except Exception as exc:
        log.warning("websocket unavailable (%s); continuing with REST quotes", exc)

    try:
        while True:
            now = dt.datetime.now(IST)
            if market_is_open(now):
                engine.run_cycle()
                # refresh feed subscriptions with any newly opened option legs
                if feed:
                    new_keys = [p.option_key for p in engine.store.open_positions()
                                if p.option_key not in feed.instrument_keys]
                    if new_keys:
                        feed.subscribe(new_keys)
                time.sleep(3600)  # hourly cadence matches the 1H trigger timeframe
            else:
                log.info("market closed (%s); sleeping 5 min", now.time())
                time.sleep(300)
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        if feed:
            feed.stop()


if __name__ == "__main__":
    main()
