"""Strategy behavior on REAL market data.

Live candles have no scripted outcome, so each test independently re-derives
the blueprint conditions from the raw data and asserts the strategy's verdict
agrees. Whatever the market is actually doing today, the signal must be the
one the rules dictate.
"""

from stocklong.indicators.ichimoku import bullish_cloud, ichimoku, price_above_cloud
from stocklong.indicators.macd import macd
from stocklong.indicators.renko import renko_from_ohlc
from stocklong.strategies import InstitutionalFilter, RenkoNoiseKiller, SignalAction


class TestInstitutionalFilterOnRealData:
    def test_verdict_agrees_with_rederived_conditions(self, daily_real, hourly_real):
        strat = InstitutionalFilter(trigger_lookback_bars=3)
        sig = strat.evaluate("RELIANCE", daily_real, hourly_real)
        assert sig.action in (SignalAction.ENTER_LONG, SignalAction.HOLD)
        assert sig.strategy == "institutional_filter"
        assert sig.reason

        # Re-derive Filter 1 (daily macro trend) straight from the data
        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        macro_ok = bool(
            price_above_cloud(daily_real["close"], ich_d).iloc[-1]
            and bullish_cloud(ich_d).iloc[-1]
        )
        if not macro_ok:
            assert sig.action is SignalAction.HOLD, \
                "must never enter against the daily cloud"

        if sig.action is SignalAction.ENTER_LONG:
            # an entry requires macro alignment AND live bullish hourly state
            assert macro_ok
            ich_h = ichimoku(hourly_real["high"], hourly_real["low"], hourly_real["close"])
            assert ich_h["tenkan"].iloc[-1] > ich_h["kijun"].iloc[-1]
            macd_h = macd(hourly_real["close"])
            assert macd_h["macd"].iloc[-1] > macd_h["signal"].iloc[-1]

    def test_exit_verdict_matches_cloud_position(self, daily_real):
        strat = InstitutionalFilter()
        sig = strat.check_exit("RELIANCE", daily_real)
        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        above = bool(price_above_cloud(daily_real["close"], ich_d).iloc[-1])
        assert sig.action is (SignalAction.HOLD if above else SignalAction.EXIT)

    def test_universe_scan_returns_valid_signals(self, universe_daily, hourly_real):
        strat = InstitutionalFilter()
        for symbol, df_daily in universe_daily.items():
            sig = strat.evaluate(symbol, df_daily, hourly_real)
            assert sig.symbol == symbol
            assert sig.action in (SignalAction.ENTER_LONG, SignalAction.HOLD)


class TestRenkoNoiseKillerOnRealData:
    def test_exit_verdict_matches_actual_bricks(self, universe_daily):
        strat = RenkoNoiseKiller(box_mode="atr", atr_period=14)
        for symbol, df_daily in universe_daily.items():
            bricks = renko_from_ohlc(df_daily, box_mode="atr", atr_period=14).bricks
            two_red = len(bricks) >= 2 and bool(
                (bricks["direction"].iloc[-2:] == -1).all())
            sig = strat.check_exit(symbol, df_daily)
            assert sig.action is (SignalAction.EXIT if two_red else SignalAction.HOLD), \
                f"{symbol}: exit verdict must mirror the real brick sequence"

    def test_entry_verdict_agrees_with_rederived_conditions(self, universe_daily):
        strat = RenkoNoiseKiller(box_mode="atr", atr_period=14)
        for symbol, df_daily in universe_daily.items():
            sig = strat.evaluate(symbol, df_daily)
            assert sig.action in (SignalAction.ENTER_LONG, SignalAction.HOLD)
            if sig.action is SignalAction.ENTER_LONG:
                bricks = renko_from_ohlc(df_daily, box_mode="atr", atr_period=14).bricks
                assert (bricks["direction"].iloc[-2:] == 1).all()
                hist = macd(bricks["close"])["histogram"]
                assert hist.iloc[-1] > 0

    def test_percent_box_mode_also_runs_on_real_data(self, daily_real):
        strat = RenkoNoiseKiller(box_mode="percent", percent_box=0.01)
        sig = strat.evaluate("RELIANCE", daily_real)
        assert sig.action in (SignalAction.ENTER_LONG, SignalAction.HOLD)
