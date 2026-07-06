"""MACD (12, 26, 9) on any close series - time candles or Renko brick closes."""

from __future__ import annotations

import pandas as pd


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }
    )


def macd_cross_up(macd_df: pd.DataFrame) -> pd.Series:
    """True on bars where the MACD line crosses above the signal line."""
    above = macd_df["macd"] > macd_df["signal"]
    return above & ~above.shift(1, fill_value=False)
