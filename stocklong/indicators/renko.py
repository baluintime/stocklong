"""Renko brick engine.

Bricks print only when price travels a fixed box distance, isolating structure
from time. Box size is either ATR(14) of the source data or a fixed percent of
spot (blueprint: 1%). A reversal requires 2x the box size, standard Renko.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    # Wilder's smoothing
    return tr.ewm(alpha=1 / period, adjust=False).mean()


@dataclass
class RenkoResult:
    bricks: pd.DataFrame  # columns: open, close, direction (+1/-1), timestamp
    box_size: float


def renko_bricks(
    close: pd.Series,
    box_size: float,
    timestamps: pd.Series | None = None,
) -> pd.DataFrame:
    """Build Renko bricks from a close-price series.

    Returns a DataFrame with one row per brick:
      open, close, direction (+1 green / -1 red), timestamp of the tick that
      completed the brick.
    """
    if box_size <= 0:
        raise ValueError("box_size must be positive")
    prices = close.to_numpy(dtype=float)
    if timestamps is None:
        timestamps = pd.Series(range(len(prices)))
    ts = timestamps.reset_index(drop=True)

    bricks: list[dict] = []
    if len(prices) == 0:
        return pd.DataFrame(columns=["open", "close", "direction", "timestamp"])

    # Anchor the first brick boundary on the first price, snapped to the grid.
    anchor = np.floor(prices[0] / box_size) * box_size
    last_top = anchor + box_size
    last_bottom = anchor
    direction = 0

    for i in range(1, len(prices)):
        price = prices[i]
        while True:
            if direction >= 0 and price >= last_top + box_size:
                bricks.append(
                    {"open": last_top, "close": last_top + box_size,
                     "direction": 1, "timestamp": ts.iloc[i]}
                )
                last_bottom = last_top
                last_top += box_size
                direction = 1
            elif direction <= 0 and price <= last_bottom - box_size:
                bricks.append(
                    {"open": last_bottom, "close": last_bottom - box_size,
                     "direction": -1, "timestamp": ts.iloc[i]}
                )
                last_top = last_bottom
                last_bottom -= box_size
                direction = -1
            # Reversals need to clear the opposite boundary by 2 boxes.
            elif direction == 1 and price <= last_bottom - box_size:
                bricks.append(
                    {"open": last_bottom, "close": last_bottom - box_size,
                     "direction": -1, "timestamp": ts.iloc[i]}
                )
                last_top = last_bottom
                last_bottom -= box_size
                direction = -1
            elif direction == -1 and price >= last_top + box_size:
                bricks.append(
                    {"open": last_top, "close": last_top + box_size,
                     "direction": 1, "timestamp": ts.iloc[i]}
                )
                last_bottom = last_top
                last_top += box_size
                direction = 1
            else:
                break

    return pd.DataFrame(bricks, columns=["open", "close", "direction", "timestamp"])


def renko_from_ohlc(
    df: pd.DataFrame,
    box_mode: str = "atr",
    atr_period: int = 14,
    percent_box: float = 0.01,
) -> RenkoResult:
    """Build bricks from an OHLC DataFrame using the blueprint's box sizing:
    ATR(14) or a fixed 1% of the latest spot price."""
    if box_mode == "atr":
        box = float(atr(df["high"], df["low"], df["close"], atr_period).iloc[-1])
    elif box_mode == "percent":
        box = float(df["close"].iloc[-1]) * percent_box
    else:
        raise ValueError(f"unknown box_mode: {box_mode}")
    bricks = renko_bricks(df["close"], box, timestamps=df["timestamp"] if "timestamp" in df else None)
    return RenkoResult(bricks=bricks, box_size=box)
