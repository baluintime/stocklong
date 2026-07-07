"""Strategy behavior on REAL market data - both directions.

Live candles have no scripted outcome, so each test independently re-derives
the blueprint conditions from the raw data and asserts the strategy's verdict
agrees. Whatever the market is actually doing today, the signal must be the
one the rules dictate - for the long (buy CE) and short (buy PE) side alike.
"""

from stocklong.indicators.ichimoku import (
    bearish_cloud, bullish_cloud, ichimoku, price_above_cloud, price_below_cloud,
)
from stocklong.indicators.macd import macd
from stocklong.indicators.renko import renko_from_ohlc
from stocklong.strategies import (
    LONG, SHORT, InstitutionalFilter, RenkoNoiseKiller, SignalAction,
)


class TestInstitutionalFilterOnRealData:
    def test_long_verdict_agrees_with_rederived_conditions(self, daily_real, hourly_real):
        strat = InstitutionalFilter(trigger_lookback_bars=3)
        sig = strat.evaluate("RELIANCE", daily_real, hourly_real, LONG)
        assert sig.action in (SignalAction.ENTER_LONG, SignalAction.HOLD)
        assert sig.strategy == "institutional_filter"

        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        macro_ok = bool(
            price_above_cloud(daily_real["close"], ich_d).iloc[-1]
            and bullish_cloud(ich_d).iloc[-1])
        if not macro_ok:
            assert sig.action is SignalAction.HOLD, \
                "must never enter long against the daily cloud"
        if sig.action is SignalAction.ENTER_LONG:
            assert macro_ok
            ich_h = ichimoku(hourly_real["high"], hourly_real["low"], hourly_real["close"])
            assert ich_h["tenkan"].iloc[-1] > ich_h["kijun"].iloc[-1]
            macd_h = macd(hourly_real["close"])
            assert macd_h["macd"].iloc[-1] > macd_h["signal"].iloc[-1]

    def test_short_verdict_agrees_with_rederived_conditions(self, daily_real, hourly_real):
        strat = InstitutionalFilter(trigger_lookback_bars=3)
        sig = strat.evaluate("RELIANCE", daily_real, hourly_real, SHORT)
        assert sig.action in (SignalAction.ENTER_SHORT, SignalAction.HOLD)

        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        macro_ok = bool(
            price_below_cloud(daily_real["close"], ich_d).iloc[-1]
            and bearish_cloud(ich_d).iloc[-1])
        if not macro_ok:
            assert sig.action is SignalAction.HOLD, \
                "must never enter short against the daily cloud"
        if sig.action is SignalAction.ENTER_SHORT:
            assert macro_ok
            ich_h = ichimoku(hourly_real["high"], hourly_real["low"], hourly_real["close"])
            assert ich_h["tenkan"].iloc[-1] < ich_h["kijun"].iloc[-1]

    def test_long_and_short_never_both_fire(self, universe_daily, hourly_real):
        """The mirrored macro filters are mutually exclusive on any real chart."""
        strat = InstitutionalFilter()
        for symbol, df_daily in universe_daily.items():
            long_sig = strat.evaluate(symbol, df_daily, hourly_real, LONG)
            short_sig = strat.evaluate(symbol, df_daily, hourly_real, SHORT)
            assert not (long_sig.action is SignalAction.ENTER_LONG
                        and short_sig.action is SignalAction.ENTER_SHORT)

    def test_exit_verdict_matches_cloud_position(self, daily_real):
        strat = InstitutionalFilter()
        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        above = bool(price_above_cloud(daily_real["close"], ich_d).iloc[-1])
        below = bool(price_below_cloud(daily_real["close"], ich_d).iloc[-1])
        long_exit = strat.check_exit("RELIANCE", daily_real, LONG)
        short_exit = strat.check_exit("RELIANCE", daily_real, SHORT)
        assert long_exit.action is (SignalAction.HOLD if above else SignalAction.EXIT)
        assert short_exit.action is (SignalAction.HOLD if below else SignalAction.EXIT)


class TestRenkoNoiseKillerOnRealData:
    def test_exit_verdicts_match_actual_bricks(self, universe_daily):
        strat = RenkoNoiseKiller(box_mode="atr", atr_period=14)
        for symbol, df_daily in universe_daily.items():
            bricks = renko_from_ohlc(df_daily, box_mode="atr", atr_period=14).bricks
            last_two = bricks["direction"].iloc[-2:]
            two_red = len(bricks) >= 2 and bool((last_two == -1).all())
            two_green = len(bricks) >= 2 and bool((last_two == 1).all())
            long_exit = strat.check_exit(symbol, df_daily, LONG)
            short_exit = strat.check_exit(symbol, df_daily, SHORT)
            assert long_exit.action is (SignalAction.EXIT if two_red else SignalAction.HOLD)
            assert short_exit.action is (SignalAction.EXIT if two_green else SignalAction.HOLD)

    def test_entry_verdicts_agree_with_rederived_conditions(self, universe_daily):
        strat = RenkoNoiseKiller(box_mode="atr", atr_period=14)
        for symbol, df_daily in universe_daily.items():
            for direction, action in ((LONG, SignalAction.ENTER_LONG),
                                      (SHORT, SignalAction.ENTER_SHORT)):
                sig = strat.evaluate(symbol, df_daily, direction)
                assert sig.action in (action, SignalAction.HOLD)
                if sig.action is action:
                    bricks = renko_from_ohlc(df_daily, box_mode="atr",
                                             atr_period=14).bricks
                    assert (bricks["direction"].iloc[-2:] == direction).all()
                    hist = macd(bricks["close"])["histogram"]
                    assert hist.iloc[-1] * direction > 0

    def test_long_and_short_entries_are_exclusive(self, daily_real):
        strat = RenkoNoiseKiller()
        long_sig = strat.evaluate("RELIANCE", daily_real, LONG)
        short_sig = strat.evaluate("RELIANCE", daily_real, SHORT)
        assert not (long_sig.action is SignalAction.ENTER_LONG
                    and short_sig.action is SignalAction.ENTER_SHORT)
