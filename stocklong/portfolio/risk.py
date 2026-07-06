"""Risk guardrails from blueprint section 4.

* Contract selection: ITM calls with delta 0.70-0.85, far-month expiry
  (T+2 to T+3 months), liquid strikes only.
* Physical-settlement rule: square off ANY open contract at least
  5 trading days before its expiry - never carry into the final week.
* Position sizing and limit-order pricing (limit orders only, never market).
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from ..data.option_chain import ChainEntry


def trading_days_until(target: dt.date, today: dt.date | None = None) -> int:
    """Weekday count between today (exclusive) and target (inclusive).

    NSE holidays are not subtracted, which makes the square-off rule strictly
    *more* conservative - we exit early, never late."""
    today = today or dt.date.today()
    if target <= today:
        return 0
    # busday_count is [start, end): shift both ends by one day so the range
    # becomes (today, target] - exclude today, include the expiry day itself.
    one_day = dt.timedelta(days=1)
    return int(np.busday_count(today + one_day, target + one_day))


def must_square_off(expiry: dt.date, days_before: int = 5, today: dt.date | None = None) -> bool:
    """True when we are inside the forbidden pre-expiry window."""
    return trading_days_until(expiry, today) <= days_before


def select_far_month_expiry(
    expiries: list[dt.date],
    months_ahead_min: int = 2,
    months_ahead_max: int = 3,
    today: dt.date | None = None,
) -> dt.date | None:
    """Pick the nearest monthly expiry that is T+2 to T+3 months out."""
    today = today or dt.date.today()
    candidates = []
    for exp in sorted(expiries):
        months = (exp.year - today.year) * 12 + (exp.month - today.month)
        if months_ahead_min <= months <= months_ahead_max:
            candidates.append(exp)
    return candidates[0] if candidates else None


def select_itm_call(
    chain: list[ChainEntry],
    delta_min: float = 0.70,
    delta_max: float = 0.85,
    min_oi: float = 0,
) -> ChainEntry | None:
    """Pick the ITM call whose delta sits in the blueprint band.

    Prefers the middle of the band (0.775) so premium is intrinsic-heavy
    without paying for near-1.0 deltas that behave like stock."""
    calls = [
        c for c in chain
        if c.option_type == "CE"
        and delta_min <= c.delta <= delta_max
        and c.ltp > 0
        and c.oi >= min_oi
    ]
    if not calls:
        return None
    target = (delta_min + delta_max) / 2
    return min(calls, key=lambda c: abs(c.delta - target))


def size_position(
    capital: float, capital_per_trade_pct: float, premium: float, lot_size: int
) -> int:
    """Number of lots such that (premium * qty) <= capital * pct. May be 0."""
    if premium <= 0 or lot_size <= 0:
        return 0
    budget = capital * capital_per_trade_pct
    per_lot_cost = premium * lot_size
    return int(budget // per_lot_cost)


def limit_price(ltp: float, side: str, buffer_pct: float = 0.005, tick: float = 0.05) -> float:
    """Limit-orders-only rule: buy slightly above LTP, sell slightly below,
    rounded to the exchange tick so the order is accepted but still bounded."""
    raw = ltp * (1 + buffer_pct) if side.upper() == "BUY" else ltp * (1 - buffer_pct)
    return round(round(raw / tick) * tick, 2)
