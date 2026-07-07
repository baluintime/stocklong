"""Confluence scanner: scores every F&O stock 0-100 in BOTH directions.

The score measures how many blueprint conditions currently align, weighted by
importance. LONG scores a call-buying setup, SHORT scores a put-buying setup
(the mirror conditions). The dashboard ranks all stocks by their best side so
the highest-confluence opportunities - long or short - surface first.

Components (max 100):
  macro  30  daily price beyond the Ichimoku cloud, cloud color aligned
  tk     20  hourly Tenkan/Kijun state (10) + fresh TK cross (10)
  macd   20  hourly MACD state (10) + fresh cross near the zero line (10)
  renko  30  two bricks with trend (15) + histogram sign (10) + rising (5)

A score >= 70 means macro alignment plus at least two active triggers - the
kind of stacked setup the blueprint calls high-probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .indicators.ichimoku import (
    bearish_cloud, bullish_cloud, ichimoku, price_above_cloud,
    price_below_cloud, tk_cross_down, tk_cross_up,
)
from .indicators.macd import macd, macd_cross_down, macd_cross_up
from .indicators.renko import renko_from_ohlc
from .strategies.base import LONG, SHORT

WEIGHTS = {"macro": 30, "tk_state": 10, "tk_cross": 10,
           "macd_state": 10, "macd_cross": 10,
           "renko_bricks": 15, "renko_hist": 10, "renko_rising": 5}


@dataclass
class ScanScore:
    symbol: str
    instrument_key: str
    direction: int              # LONG (+1) or SHORT (-1)
    score: int
    close: float
    components: dict = field(default_factory=dict)

    @property
    def side(self) -> str:
        return "LONG" if self.direction == LONG else "SHORT"


def score_direction(
    symbol: str,
    instrument_key: str,
    df_daily: pd.DataFrame,
    df_hourly: pd.DataFrame,
    direction: int,
    lookback_bars: int = 3,
    macd_zero_tolerance_pct: float = 0.001,
) -> ScanScore:
    close = float(df_daily["close"].iloc[-1])
    comp = {k: 0 for k in WEIGHTS}

    if len(df_daily) >= 80 and len(df_hourly) >= 60:
        # macro: daily cloud
        ich_d = ichimoku(df_daily["high"], df_daily["low"], df_daily["close"])
        if direction == LONG:
            aligned = bool(price_above_cloud(df_daily["close"], ich_d).iloc[-1]
                           and bullish_cloud(ich_d).iloc[-1])
        else:
            aligned = bool(price_below_cloud(df_daily["close"], ich_d).iloc[-1]
                           and bearish_cloud(ich_d).iloc[-1])
        comp["macro"] = WEIGHTS["macro"] if aligned else 0

        # hourly TK
        ich_h = ichimoku(df_hourly["high"], df_hourly["low"], df_hourly["close"])
        tk_diff = float(ich_h["tenkan"].iloc[-1] - ich_h["kijun"].iloc[-1])
        if tk_diff * direction > 0:
            comp["tk_state"] = WEIGHTS["tk_state"]
        crosses_tk = tk_cross_up(ich_h) if direction == LONG else tk_cross_down(ich_h)
        if bool(crosses_tk.iloc[-lookback_bars:].any()):
            comp["tk_cross"] = WEIGHTS["tk_cross"]

        # hourly MACD
        macd_h = macd(df_hourly["close"])
        macd_diff = float(macd_h["macd"].iloc[-1] - macd_h["signal"].iloc[-1])
        if macd_diff * direction > 0:
            comp["macd_state"] = WEIGHTS["macd_state"]
        crosses_m = macd_cross_up(macd_h) if direction == LONG else macd_cross_down(macd_h)
        recent = crosses_m.iloc[-lookback_bars:]
        if recent.any():
            cross_idx = recent[recent].index[-1]
            tol = float(df_hourly["close"].iloc[-1]) * macd_zero_tolerance_pct
            if float(macd_h["macd"].loc[cross_idx]) * direction <= tol:
                comp["macd_cross"] = WEIGHTS["macd_cross"]

        # daily renko
        bricks = renko_from_ohlc(df_daily).bricks
        if len(bricks) >= 40:
            if bool((bricks["direction"].iloc[-2:] == direction).all()):
                comp["renko_bricks"] = WEIGHTS["renko_bricks"]
            hist = macd(bricks["close"])["histogram"]
            hist_now, hist_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
            if hist_now * direction > 0:
                comp["renko_hist"] = WEIGHTS["renko_hist"]
            if (hist_now - hist_prev) * direction > 0:
                comp["renko_rising"] = WEIGHTS["renko_rising"]

    return ScanScore(
        symbol=symbol, instrument_key=instrument_key, direction=direction,
        score=sum(comp.values()), close=close, components=comp,
    )


def score_both_sides(
    symbol: str, instrument_key: str,
    df_daily: pd.DataFrame, df_hourly: pd.DataFrame, **kwargs,
) -> list[ScanScore]:
    return [
        score_direction(symbol, instrument_key, df_daily, df_hourly, LONG, **kwargs),
        score_direction(symbol, instrument_key, df_daily, df_hourly, SHORT, **kwargs),
    ]


def best_side(scores: list[ScanScore]) -> ScanScore:
    return max(scores, key=lambda s: s.score)
