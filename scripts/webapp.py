#!/usr/bin/env python3
"""Launch the StockLong dashboard on http://localhost:8080

Everything is driven from the browser: Upstox login (automatic OAuth
callback - no code copying), the auto-refreshing confluence scoreboard
(long CE / short PE), the hourly engine loop, positions and logs.

On startup the F&O stock universe is refreshed from the exchange's live
instrument master - no hardcoded stock lists.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from stocklong.config import Config
from stocklong.web.app import create_app

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    app = create_app(Config.load())
    print("\n  StockLong dashboard:  http://localhost:8080\n")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
