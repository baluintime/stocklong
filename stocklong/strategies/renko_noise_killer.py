"""Strategy 2: The Daily Renko Noise-Killer Framework (long AND short setups).

Bricks from daily closes, ATR(14) or 1%-of-spot box; MACD (12, 26, 9) over the
brick close sequence.

Long entry:   two consecutive green bricks + Renko-MACD histogram shifting
              positive.
Short entry:  two consecutive red bricks + histogram shifting negative
              (mirror; the position is a bought PUT, never a short option).
Exit:         two consecutive bricks against the position - liquidate
              instantly (blueprint's premium-preservation rule).
"""

from __future__ import annotations

import pandas as pd

from ..indicators.macd import macd
from ..indicators.renko import renko_from_ohlc
from .base import LONG, Signal, SignalAction, entry_action


class RenkoNoiseKiller:
    name = "renko_noise_killer"

    def __init__(self, box_mode: str = "atr", atr_period: int = 14, percent_box: float = 0.01):
        self.box_mode = box_mode
        self.atr_period = atr_period
        self.percent_box = percent_box

    def _bricks(self, df_daily: pd.DataFrame) -> tuple[pd.DataFrame, float]:
        result = renko_from_ohlc(
            df_daily,
            box_mode=self.box_mode,
            atr_period=self.atr_period,
            percent_box=self.percent_box,
        )
        return result.bricks, result.box_size

    def evaluate(self, symbol: str, df_daily: pd.DataFrame, direction: int = LONG) -> Signal:
        if len(df_daily) < 60:
            return self._hold(symbol, "insufficient history", direction)
        bricks, box = self._bricks(df_daily)
        if len(bricks) < 40:
            return self._hold(symbol, "not enough Renko bricks for MACD", direction)
        side = "long" if direction == LONG else "short"

        two_with = bool((bricks["direction"].iloc[-2:] == direction).all())
        macd_r = macd(bricks["close"])
        hist_now = float(macd_r["histogram"].iloc[-1])
        hist_prev = float(macd_r["histogram"].iloc[-2])
        # histogram shifting in the trade direction (sign-mirrored for shorts)
        macro_shift = hist_now * direction > 0 and (
            hist_prev * direction <= 0 or (hist_now - hist_prev) * direction > 0)

        if two_with and macro_shift:
            color = "green" if direction == LONG else "red"
            return Signal(
                symbol=symbol,
                action=entry_action(direction),
                strategy=self.name,
                direction=direction,
                reason=f"{side}: two consecutive {color} bricks + Renko-MACD shift",
                context={"box_size": box, "hist": hist_now, "bricks": len(bricks)},
            )
        return self._hold(
            symbol, f"no {side} breakout: need 2 bricks with trend + MACD shift", direction)

    def check_exit(self, symbol: str, df_daily: pd.DataFrame, direction: int = LONG) -> Signal:
        """Two consecutive bricks against the position => liquidate immediately."""
        bricks, _ = self._bricks(df_daily)
        if len(bricks) >= 2 and bool((bricks["direction"].iloc[-2:] == -direction).all()):
            color = "red" if direction == LONG else "green"
            return Signal(
                symbol=symbol, action=SignalAction.EXIT, strategy=self.name,
                direction=direction,
                reason=f"two consecutive {color} Renko bricks against the position",
            )
        return self._hold(symbol, "no two-brick breakdown against the position", direction)

    def _hold(self, symbol: str, reason: str, direction: int) -> Signal:
        return Signal(symbol=symbol, action=SignalAction.HOLD, strategy=self.name,
                      direction=direction, reason=reason)
