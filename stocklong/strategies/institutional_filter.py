"""Strategy 1: Multi-Timeframe Institutional Filter (long AND short setups).

Long (buy CE), all three must align (blueprint section 2):
  Filter 1 - Daily: price completely above a green Ichimoku cloud.
  Filter 2 - Hourly: Tenkan-sen crosses above Kijun-sen (TK cross).
  Filter 3 - Hourly: MACD line crosses above signal, near or below zero.

Short (buy PE) is the exact mirror: price completely below a red cloud,
TK cross down, MACD cross down near or above the zero line. The zero-line
constraint blocks chasing overextended moves in either direction.
"""

from __future__ import annotations

import pandas as pd

from ..indicators.ichimoku import (
    bearish_cloud, bullish_cloud, ichimoku, price_above_cloud,
    price_below_cloud, tk_cross_down, tk_cross_up,
)
from ..indicators.macd import macd, macd_cross_down, macd_cross_up
from .base import LONG, Signal, SignalAction, entry_action


class InstitutionalFilter:
    name = "institutional_filter"

    def __init__(self, trigger_lookback_bars: int = 3, macd_zero_tolerance_pct: float = 0.001):
        self.trigger_lookback_bars = trigger_lookback_bars
        self.macd_zero_tolerance_pct = macd_zero_tolerance_pct

    def evaluate(
        self, symbol: str, df_daily: pd.DataFrame, df_hourly: pd.DataFrame,
        direction: int = LONG,
    ) -> Signal:
        if len(df_daily) < 80 or len(df_hourly) < 60:
            return self._hold(symbol, "insufficient history", direction)
        side = "long" if direction == LONG else "short"

        # --- Filter 1: macro trend on the daily chart ---
        ich_d = ichimoku(df_daily["high"], df_daily["low"], df_daily["close"])
        if direction == LONG:
            macro_ok = bool(price_above_cloud(df_daily["close"], ich_d).iloc[-1]
                            and bullish_cloud(ich_d).iloc[-1])
        else:
            macro_ok = bool(price_below_cloud(df_daily["close"], ich_d).iloc[-1]
                            and bearish_cloud(ich_d).iloc[-1])
        if not macro_ok:
            return self._hold(
                symbol, f"daily trend not aligned for {side} (Ichimoku cloud)", direction)

        # --- Filter 2: hourly TK cross within the lookback window ---
        ich_h = ichimoku(df_hourly["high"], df_hourly["low"], df_hourly["close"])
        lb = self.trigger_lookback_bars
        crosses_tk = tk_cross_up(ich_h) if direction == LONG else tk_cross_down(ich_h)
        tk_state_ok = bool((ich_h["tenkan"].iloc[-1] - ich_h["kijun"].iloc[-1]) * direction > 0)
        if not (bool(crosses_tk.iloc[-lb:].any()) and tk_state_ok):
            return self._hold(symbol, f"no recent hourly TK cross ({side})", direction)

        # --- Filter 3: hourly MACD cross near the zero line ---
        macd_h = macd(df_hourly["close"])
        crosses_m = macd_cross_up(macd_h) if direction == LONG else macd_cross_down(macd_h)
        recent = crosses_m.iloc[-lb:]
        if not recent.any():
            return self._hold(symbol, f"no recent hourly MACD cross ({side})", direction)
        cross_idx = recent[recent].index[-1]
        tol = float(df_hourly["close"].iloc[-1]) * self.macd_zero_tolerance_pct
        macd_at_cross = float(macd_h["macd"].loc[cross_idx])
        # long: cross at/below zero; short: cross at/above zero (mirror)
        near_zero = macd_at_cross * direction <= tol
        macd_state_ok = bool(
            (macd_h["macd"].iloc[-1] - macd_h["signal"].iloc[-1]) * direction > 0)
        if not near_zero:
            return self._hold(
                symbol, f"MACD cross too far past zero (overextended {side})", direction)
        if not macd_state_ok:
            return self._hold(symbol, f"MACD no longer aligned ({side})", direction)

        return Signal(
            symbol=symbol,
            action=entry_action(direction),
            strategy=self.name,
            direction=direction,
            reason=(f"{side}: daily cloud aligned + hourly TK cross "
                    "+ MACD cross near zero"),
            context={
                "daily_close": float(df_daily["close"].iloc[-1]),
                "tenkan": float(ich_h["tenkan"].iloc[-1]),
                "kijun": float(ich_h["kijun"].iloc[-1]),
                "macd_at_cross": macd_at_cross,
            },
        )

    def check_exit(self, symbol: str, df_daily: pd.DataFrame, direction: int = LONG) -> Signal:
        """Macro-trend failure exit: daily close falls back into the cloud."""
        ich_d = ichimoku(df_daily["high"], df_daily["low"], df_daily["close"])
        if direction == LONG:
            intact = bool(price_above_cloud(df_daily["close"], ich_d).iloc[-1])
        else:
            intact = bool(price_below_cloud(df_daily["close"], ich_d).iloc[-1])
        if not intact:
            return Signal(
                symbol=symbol, action=SignalAction.EXIT, strategy=self.name,
                direction=direction,
                reason="daily close fell back into the Ichimoku cloud",
            )
        return self._hold(symbol, "macro trend intact", direction)

    def _hold(self, symbol: str, reason: str, direction: int) -> Signal:
        return Signal(symbol=symbol, action=SignalAction.HOLD, strategy=self.name,
                      direction=direction, reason=reason)
