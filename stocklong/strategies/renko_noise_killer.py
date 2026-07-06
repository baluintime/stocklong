"""Strategy 2: The Daily Renko Noise-Killer Framework.

Bricks are built from daily closes with an ATR(14) or 1%-of-spot box.
MACD (12, 26, 9) is computed over the *brick close sequence*, not time candles.

Entry:  two consecutive green bricks AND the Renko-MACD histogram turning
        positive (positive now, non-positive on the previous brick or rising).
Exit:   two consecutive red bricks against the position - liquidate instantly
        (blueprint's premium-preservation rule).
"""

from __future__ import annotations

import pandas as pd

from ..indicators.macd import macd
from ..indicators.renko import renko_from_ohlc
from .base import Signal, SignalAction


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

    def evaluate(self, symbol: str, df_daily: pd.DataFrame) -> Signal:
        if len(df_daily) < 60:
            return self._hold(symbol, "insufficient history")
        bricks, box = self._bricks(df_daily)
        if len(bricks) < 40:
            return self._hold(symbol, "not enough Renko bricks for MACD")

        two_green = bool((bricks["direction"].iloc[-2:] == 1).all())
        macd_r = macd(bricks["close"])
        hist_now = float(macd_r["histogram"].iloc[-1])
        hist_prev = float(macd_r["histogram"].iloc[-2])
        macro_shift = hist_now > 0 and (hist_prev <= 0 or hist_now > hist_prev)

        if two_green and macro_shift:
            return Signal(
                symbol=symbol,
                action=SignalAction.ENTER_LONG,
                strategy=self.name,
                reason="two consecutive green bricks + positive Renko-MACD shift",
                context={"box_size": box, "hist": hist_now, "bricks": len(bricks)},
            )
        return self._hold(symbol, "no breakout: need 2 green bricks + MACD histogram shift")

    def check_exit(self, symbol: str, df_daily: pd.DataFrame) -> Signal:
        """Two consecutive red bricks => liquidate immediately."""
        bricks, _ = self._bricks(df_daily)
        if len(bricks) >= 2 and bool((bricks["direction"].iloc[-2:] == -1).all()):
            return Signal(
                symbol=symbol,
                action=SignalAction.EXIT,
                strategy=self.name,
                reason="two consecutive red Renko bricks against the position",
            )
        return self._hold(symbol, "no two-red-brick breakdown")

    def _hold(self, symbol: str, reason: str) -> Signal:
        return Signal(symbol=symbol, action=SignalAction.HOLD, strategy=self.name, reason=reason)
