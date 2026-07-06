import numpy as np
import pandas as pd

from stocklong.strategies import InstitutionalFilter, RenkoNoiseKiller, SignalAction


def make_ohlc(closes: np.ndarray, freq: str = "D") -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=len(closes), freq=freq),
        "open": closes,
        "high": closes * 1.005,
        "low": closes * 0.995,
        "close": closes,
        "volume": 1000,
    })


def strong_uptrend_daily(n: int = 300) -> pd.DataFrame:
    return make_ohlc(np.linspace(100, 300, n))


def pullback_then_turn_hourly() -> pd.DataFrame:
    # long rally, shallow pullback, fresh turn up -> TK cross + MACD cross near zero
    closes = np.concatenate([
        np.linspace(250, 290, 120),
        np.linspace(290, 278, 40),
        np.linspace(278, 288, 12),
    ])
    return make_ohlc(closes, freq="h")


class TestInstitutionalFilter:
    def test_full_alignment_enters(self):
        # the MACD cross fires ~10 bars before the series end on this shape
        strat = InstitutionalFilter(trigger_lookback_bars=10)
        sig = strat.evaluate("TEST", strong_uptrend_daily(), pullback_then_turn_hourly())
        assert sig.action is SignalAction.ENTER_LONG

    def test_bearish_daily_blocks_entry(self):
        strat = InstitutionalFilter(trigger_lookback_bars=6)
        daily = make_ohlc(np.linspace(300, 100, 300))  # downtrend: below cloud
        sig = strat.evaluate("TEST", daily, pullback_then_turn_hourly())
        assert sig.action is SignalAction.HOLD
        assert "cloud" in sig.reason

    def test_overextended_macd_blocks_entry(self):
        strat = InstitutionalFilter(trigger_lookback_bars=6, macd_zero_tolerance_pct=0.0)
        # V-shaped hourly: MACD cross happens far below zero is fine, but force
        # a cross far ABOVE zero: steady rally then tiny dip then continuation
        closes = np.concatenate([
            np.linspace(200, 300, 150),
            np.linspace(300, 298, 3),
            np.linspace(298, 306, 5),
        ])
        sig = strat.evaluate("TEST", strong_uptrend_daily(), make_ohlc(closes, freq="h"))
        assert sig.action is SignalAction.HOLD

    def test_exit_when_price_falls_into_cloud(self):
        strat = InstitutionalFilter()
        closes = np.concatenate([np.linspace(100, 300, 250), np.linspace(300, 180, 50)])
        sig = strat.check_exit("TEST", make_ohlc(closes))
        assert sig.action is SignalAction.EXIT

    def test_insufficient_history_holds(self):
        strat = InstitutionalFilter()
        short = make_ohlc(np.linspace(100, 110, 10))
        assert strat.evaluate("TEST", short, short).action is SignalAction.HOLD


class TestRenkoNoiseKiller:
    def test_breakout_after_range_enters(self):
        # long sideways range then a hard breakout -> 2 green bricks + MACD shift
        rng = np.random.default_rng(11)
        closes = np.concatenate([
            250 + rng.normal(0, 2.0, 400),
            np.linspace(252, 320, 60),
        ])[:420]  # evaluate shortly after the breakout begins, not 20 bricks deep
        strat = RenkoNoiseKiller(box_mode="percent", percent_box=0.01)
        sig = strat.evaluate("TEST", make_ohlc(closes))
        assert sig.action is SignalAction.ENTER_LONG

    def test_two_red_bricks_exit(self):
        closes = np.concatenate([np.linspace(200, 300, 300), np.linspace(300, 240, 60)])
        strat = RenkoNoiseKiller(box_mode="percent", percent_box=0.01)
        sig = strat.check_exit("TEST", make_ohlc(closes))
        assert sig.action is SignalAction.EXIT
        assert "red Renko bricks" in sig.reason

    def test_uptrend_intact_holds(self):
        closes = np.linspace(200, 320, 300)
        strat = RenkoNoiseKiller(box_mode="percent", percent_box=0.01)
        sig = strat.check_exit("TEST", make_ohlc(closes))
        assert sig.action is SignalAction.HOLD
