"""Strategy 1: Multi-Timeframe Institutional Filter.

Entry only when all three align (blueprint section 2):
  Filter 1 - Daily: price completely above a green Ichimoku cloud
             (close > max(Span A, Span B) and Span A > Span B).
  Filter 2 - Hourly: Tenkan-sen crosses above Kijun-sen (TK cross) after a pullback.
  Filter 3 - Hourly: MACD line crosses above the signal line, with the MACD line
             near or below the zero line (blocks chasing overextended rallies).

The two hourly triggers must both have fired within `trigger_lookback_bars`
recent bars, with both conditions still bullish on the latest bar.
"""

from __future__ import annotations

import pandas as pd

from ..indicators.ichimoku import bullish_cloud, ichimoku, price_above_cloud, tk_cross_up
from ..indicators.macd import macd, macd_cross_up
from .base import Signal, SignalAction


class InstitutionalFilter:
    name = "institutional_filter"

    def __init__(self, trigger_lookback_bars: int = 3, macd_zero_tolerance_pct: float = 0.001):
        self.trigger_lookback_bars = trigger_lookback_bars
        self.macd_zero_tolerance_pct = macd_zero_tolerance_pct

    def evaluate(self, symbol: str, df_daily: pd.DataFrame, df_hourly: pd.DataFrame) -> Signal:
        if len(df_daily) < 80 or len(df_hourly) < 60:
            return self._hold(symbol, "insufficient history")

        # --- Filter 1: macro trend on the daily chart ---
        ich_d = ichimoku(df_daily["high"], df_daily["low"], df_daily["close"])
        macro_ok = bool(
            price_above_cloud(df_daily["close"], ich_d).iloc[-1]
            and bullish_cloud(ich_d).iloc[-1]
        )
        if not macro_ok:
            return self._hold(symbol, "daily price not above green Ichimoku cloud")

        # --- Filter 2: hourly TK cross within the lookback window ---
        ich_h = ichimoku(df_hourly["high"], df_hourly["low"], df_hourly["close"])
        lb = self.trigger_lookback_bars
        tk_fired = bool(tk_cross_up(ich_h).iloc[-lb:].any())
        tk_bullish_now = bool(ich_h["tenkan"].iloc[-1] > ich_h["kijun"].iloc[-1])
        if not (tk_fired and tk_bullish_now):
            return self._hold(symbol, "no recent hourly TK cross")

        # --- Filter 3: hourly MACD cross near/below the zero line ---
        macd_h = macd(df_hourly["close"])
        crosses = macd_cross_up(macd_h)
        recent = crosses.iloc[-lb:]
        if not recent.any():
            return self._hold(symbol, "no recent hourly MACD bullish cross")
        cross_idx = recent[recent].index[-1]
        zero_tolerance = float(df_hourly["close"].iloc[-1]) * self.macd_zero_tolerance_pct
        near_zero = bool(macd_h["macd"].loc[cross_idx] <= zero_tolerance)
        macd_bullish_now = bool(macd_h["macd"].iloc[-1] > macd_h["signal"].iloc[-1])
        if not near_zero:
            return self._hold(symbol, "MACD cross happened too far above zero (overextended)")
        if not macd_bullish_now:
            return self._hold(symbol, "MACD no longer bullish")

        return Signal(
            symbol=symbol,
            action=SignalAction.ENTER_LONG,
            strategy=self.name,
            reason="daily above green cloud + hourly TK cross + MACD cross near zero",
            context={
                "daily_close": float(df_daily["close"].iloc[-1]),
                "tenkan": float(ich_h["tenkan"].iloc[-1]),
                "kijun": float(ich_h["kijun"].iloc[-1]),
                "macd_at_cross": float(macd_h["macd"].loc[cross_idx]),
            },
        )

    def check_exit(self, symbol: str, df_daily: pd.DataFrame) -> Signal:
        """Macro-trend failure exit: daily close falls back into/below the cloud."""
        ich_d = ichimoku(df_daily["high"], df_daily["low"], df_daily["close"])
        if not price_above_cloud(df_daily["close"], ich_d).iloc[-1]:
            return Signal(
                symbol=symbol,
                action=SignalAction.EXIT,
                strategy=self.name,
                reason="daily close fell back into the Ichimoku cloud",
            )
        return self._hold(symbol, "macro trend intact")

    def _hold(self, symbol: str, reason: str) -> Signal:
        return Signal(symbol=symbol, action=SignalAction.HOLD, strategy=self.name, reason=reason)
