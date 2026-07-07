"""Ichimoku Kinko Hyo (9, 26, 52).

Returns spans aligned to the *current* bar: senkou_a/senkou_b at index i are
the cloud values in effect at bar i (i.e. computed 26 bars ago and projected
forward), which is what "price above the cloud" tests need.
"""

from __future__ import annotations

import pandas as pd


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    tenkan = _midline(high, low, tenkan_period)
    kijun = _midline(high, low, kijun_period)
    senkou_a = ((tenkan + kijun) / 2).shift(displacement)
    senkou_b = _midline(high, low, senkou_b_period).shift(displacement)
    chikou = close.shift(-displacement)
    return pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "chikou": chikou,
        }
    )


def _midline(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def price_above_cloud(close: pd.Series, ich: pd.DataFrame) -> pd.Series:
    """True where price is completely above the cloud."""
    cloud_top = ich[["senkou_a", "senkou_b"]].max(axis=1)
    return close > cloud_top


def bullish_cloud(ich: pd.DataFrame) -> pd.Series:
    """True where the cloud is green (Span A above Span B)."""
    return ich["senkou_a"] > ich["senkou_b"]


def price_below_cloud(close: pd.Series, ich: pd.DataFrame) -> pd.Series:
    """True where price is completely below the cloud."""
    cloud_bottom = ich[["senkou_a", "senkou_b"]].min(axis=1)
    return close < cloud_bottom


def bearish_cloud(ich: pd.DataFrame) -> pd.Series:
    """True where the cloud is red (Span A below Span B)."""
    return ich["senkou_a"] < ich["senkou_b"]


def tk_cross_up(ich: pd.DataFrame) -> pd.Series:
    """True on bars where Tenkan-sen crosses above Kijun-sen."""
    above = ich["tenkan"] > ich["kijun"]
    return above & ~above.shift(1, fill_value=False)


def tk_cross_down(ich: pd.DataFrame) -> pd.Series:
    """True on bars where Tenkan-sen crosses below Kijun-sen."""
    below = ich["tenkan"] < ich["kijun"]
    return below & ~below.shift(1, fill_value=False)
