#!/usr/bin/env python3
"""Inspect or manually close persisted positions.

  python scripts/positions.py                 # list all positions
  python scripts/positions.py close <id> <price> [reason]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong.config import Config
from stocklong.portfolio.positions import PositionStore


def main() -> None:
    store = PositionStore(Config.load().get("store.db_path", "data/positions.db"))
    if len(sys.argv) >= 4 and sys.argv[1] == "close":
        pos_id, price = int(sys.argv[2]), float(sys.argv[3])
        reason = sys.argv[4] if len(sys.argv) > 4 else "manual close"
        store.close_position(pos_id, exit_price=price, exit_reason=reason)
        print(f"position #{pos_id} closed @ {price}")
        return

    rows = store.all_positions()
    if not rows:
        print("no positions recorded")
        return
    print(f"{'ID':<4} {'ST':<6} {'SYMBOL':<11} {'CONTRACT':<26} {'QTY':<6} "
          f"{'ENTRY':<9} {'EXIT':<9} {'EXPIRY':<11} STRATEGY")
    for p in rows:
        print(f"{p.id:<4} {p.status:<6} {p.symbol:<11} {p.trading_symbol:<26} "
              f"{p.quantity:<6} {p.entry_price:<9.2f} "
              f"{(p.exit_price if p.exit_price else 0):<9.2f} "
              f"{p.expiry.isoformat():<11} {p.strategy}")


if __name__ == "__main__":
    main()
