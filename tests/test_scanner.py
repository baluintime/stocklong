"""Confluence scanner on REAL market data.

The score has no scripted outcome on live candles, so these tests verify the
scoring contract: component weights, bounds, mutual exclusivity of the two
sides' macro components, and agreement with independently re-derived
indicator states.
"""

from stocklong import scanner
from stocklong.indicators.ichimoku import (
    bearish_cloud, bullish_cloud, ichimoku, price_above_cloud, price_below_cloud,
)
from stocklong.strategies import LONG, SHORT
from tests.conftest import RELIANCE_KEY


class TestScannerOnRealData:
    def test_scores_are_bounded_and_complete(self, daily_real, hourly_real):
        both = scanner.score_both_sides("RELIANCE", RELIANCE_KEY, daily_real, hourly_real)
        assert [s.direction for s in both] == [LONG, SHORT]
        for s in both:
            assert 0 <= s.score <= 100
            assert s.score == sum(s.components.values())
            assert set(s.components) == set(scanner.WEIGHTS)
            for name, value in s.components.items():
                assert value in (0, scanner.WEIGHTS[name])
            assert s.close == float(daily_real["close"].iloc[-1])

    def test_macro_component_matches_cloud_and_is_exclusive(self, daily_real, hourly_real):
        both = scanner.score_both_sides("RELIANCE", RELIANCE_KEY, daily_real, hourly_real)
        long_s, short_s = both
        ich_d = ichimoku(daily_real["high"], daily_real["low"], daily_real["close"])
        long_macro = bool(price_above_cloud(daily_real["close"], ich_d).iloc[-1]
                          and bullish_cloud(ich_d).iloc[-1])
        short_macro = bool(price_below_cloud(daily_real["close"], ich_d).iloc[-1]
                           and bearish_cloud(ich_d).iloc[-1])
        assert long_s.components["macro"] == (30 if long_macro else 0)
        assert short_s.components["macro"] == (30 if short_macro else 0)
        # price cannot be both above and below the cloud
        assert not (long_s.components["macro"] and short_s.components["macro"])

    def test_best_side_picks_higher_score(self, universe_daily, hourly_real):
        for symbol, df_daily in universe_daily.items():
            both = scanner.score_both_sides(symbol, "x", df_daily, hourly_real)
            best = scanner.best_side(both)
            assert best.score == max(s.score for s in both)
            assert best.side in ("LONG", "SHORT")
