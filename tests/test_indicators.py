"""Indicator correctness on REAL market data.

Every test here runs on live RELIANCE candles fetched from the Upstox API.
Because real data has no known "expected outcome", the assertions verify the
math itself: closed-form recomputation, structural invariants, and internal
consistency - properties that must hold on any genuine price series.
"""

import numpy as np
import pandas as pd

from stocklong.indicators.ichimoku import (
    bullish_cloud, ichimoku, price_above_cloud, tk_cross_up,
)
from stocklong.indicators.macd import macd, macd_cross_up
from stocklong.indicators.renko import atr, renko_from_ohlc


class TestIchimokuOnRealData:
    def test_lines_match_closed_form_recomputation(self, daily_real):
        ich = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        h, l = daily_real["high"], daily_real["low"]
        # Tenkan-sen at the last bar == 9-period midline recomputed by hand
        assert ich["tenkan"].iloc[-1] == (h.iloc[-9:].max() + l.iloc[-9:].min()) / 2
        # Kijun-sen == 26-period midline
        assert ich["kijun"].iloc[-1] == (h.iloc[-26:].max() + l.iloc[-26:].min()) / 2
        # Span A in effect today was computed 26 bars ago
        expected_span_a = (ich["tenkan"].iloc[-27] + ich["kijun"].iloc[-27]) / 2
        assert ich["senkou_a"].iloc[-1] == expected_span_a
        # Span B == 52-period midline from 26 bars ago
        expected_span_b = (h.iloc[-78:-26].max() + l.iloc[-78:-26].min()) / 2
        assert ich["senkou_b"].iloc[-1] == expected_span_b

    def test_cloud_tests_are_boolean_and_consistent(self, daily_real):
        ich = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        above = price_above_cloud(daily_real["close"], ich)
        green = bullish_cloud(ich)
        assert above.dtype == bool and green.dtype == bool
        # "above the cloud" must imply close > both spans on every real bar
        valid = ich["senkou_a"].notna() & ich["senkou_b"].notna()
        implied = (daily_real["close"] > ich["senkou_a"]) & (
            daily_real["close"] > ich["senkou_b"])
        assert (above[valid] == implied[valid]).all()

    def test_tk_cross_only_fires_on_state_change(self, hourly_real):
        ich = ichimoku(hourly_real["high"], hourly_real["low"], hourly_real["close"])
        crosses = tk_cross_up(ich)
        above = ich["tenkan"] > ich["kijun"]
        assert crosses.dtype == bool
        # a cross bar must be bullish now and not bullish on the previous bar
        for i in np.where(crosses)[0]:
            assert bool(above.iloc[i])
            assert i == 0 or not bool(above.iloc[i - 1])
        # crosses are rare events, not a per-bar condition (the regression this
        # guards against: object-dtype negation made every bullish bar a cross)
        assert crosses.sum() <= above.sum() / 2 or above.sum() == 0


class TestMacdOnRealData:
    def test_matches_ewm_closed_form(self, hourly_real):
        close = hourly_real["close"]
        out = macd(close)
        ref = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        pd.testing.assert_series_equal(out["macd"], ref, check_names=False)
        ref_signal = ref.ewm(span=9, adjust=False).mean()
        pd.testing.assert_series_equal(out["signal"], ref_signal, check_names=False)
        assert np.allclose(out["histogram"], out["macd"] - out["signal"])

    def test_cross_up_only_fires_on_state_change(self, hourly_real):
        out = macd(hourly_real["close"])
        crosses = macd_cross_up(out)
        above = out["macd"] > out["signal"]
        for i in np.where(crosses)[0]:
            assert bool(above.iloc[i])
            assert i == 0 or not bool(above.iloc[i - 1])


class TestAtrAndRenkoOnRealData:
    def test_atr_bounded_by_true_range(self, daily_real):
        val = atr(daily_real["high"], daily_real["low"], daily_real["close"])
        assert (val.dropna() > 0).all()
        # smoothed ATR can never exceed the largest single true range seen
        prev_close = daily_real["close"].shift(1)
        tr = pd.concat([
            daily_real["high"] - daily_real["low"],
            (daily_real["high"] - prev_close).abs(),
            (daily_real["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        assert val.iloc[-1] <= tr.max()

    def test_renko_brick_invariants(self, daily_real):
        result = renko_from_ohlc(daily_real, box_mode="atr", atr_period=14)
        bricks, box = result.bricks, result.box_size
        assert box > 0
        assert len(bricks) > 0, "a year of real daily data must print bricks"
        # every brick body is exactly one box
        assert np.allclose((bricks["close"] - bricks["open"]).abs(), box)
        # directions match the brick geometry
        assert ((bricks["close"] > bricks["open"]) == (bricks["direction"] == 1)).all()
        # Renko compresses: far fewer bricks than daily bars
        assert len(bricks) < len(daily_real)

    def test_renko_percent_box_is_one_percent_of_spot(self, daily_real):
        result = renko_from_ohlc(daily_real, box_mode="percent", percent_box=0.01)
        assert result.box_size == float(daily_real["close"].iloc[-1]) * 0.01
