import numpy as np
import pandas as pd
import pytest

from stocklong.indicators.ichimoku import (
    bullish_cloud, ichimoku, price_above_cloud, tk_cross_up,
)
from stocklong.indicators.macd import macd, macd_cross_up
from stocklong.indicators.renko import atr, renko_bricks, renko_from_ohlc


def make_ohlc(closes: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(closes), freq="D"),
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": 1000,
    })


def test_ichimoku_uptrend_is_above_green_cloud():
    closes = np.linspace(100, 200, 120)
    df = make_ohlc(closes)
    ich = ichimoku(df["high"], df["low"], df["close"])
    assert bool(price_above_cloud(df["close"], ich).iloc[-1])
    assert bool(bullish_cloud(ich).iloc[-1])


def test_ichimoku_downtrend_is_below_cloud():
    closes = np.linspace(200, 100, 120)
    df = make_ohlc(closes)
    ich = ichimoku(df["high"], df["low"], df["close"])
    assert not bool(price_above_cloud(df["close"], ich).iloc[-1])


def test_tk_cross_fires_on_v_recovery():
    closes = np.concatenate([np.linspace(200, 150, 40), np.linspace(150, 210, 40)])
    df = make_ohlc(closes)
    ich = ichimoku(df["high"], df["low"], df["close"])
    assert tk_cross_up(ich).any()


def test_macd_matches_ewm_reference():
    closes = pd.Series(np.random.default_rng(7).normal(0, 1, 200).cumsum() + 100)
    out = macd(closes)
    ref = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
    pd.testing.assert_series_equal(out["macd"], ref, check_names=False)
    assert np.allclose(out["histogram"], out["macd"] - out["signal"])


def test_macd_cross_up_detects_turn():
    closes = pd.Series(
        np.concatenate([np.linspace(100, 80, 60), np.linspace(80, 110, 60)]))
    assert macd_cross_up(macd(closes)).any()


def test_atr_constant_range():
    n = 50
    df = pd.DataFrame({"high": [102.0] * n, "low": [98.0] * n, "close": [100.0] * n})
    val = atr(df["high"], df["low"], df["close"]).iloc[-1]
    assert val == pytest.approx(4.0, rel=0.01)


def test_renko_up_move_prints_green_bricks():
    closes = pd.Series(np.linspace(100, 130, 300))
    bricks = renko_bricks(closes, box_size=2.0)
    assert len(bricks) >= 10
    assert (bricks["direction"] == 1).all()
    # each brick body is exactly one box
    assert np.allclose(bricks["close"] - bricks["open"], 2.0)


def test_renko_reversal_needs_two_boxes():
    # up to 120 then crash to 100: red bricks must appear after the reversal
    closes = pd.Series(np.concatenate([np.linspace(100, 120, 100),
                                       np.linspace(120, 100, 100)]))
    bricks = renko_bricks(closes, box_size=2.0)
    dirs = bricks["direction"].tolist()
    assert 1 in dirs and -1 in dirs
    # bricks alternate only via full reversals; last run must be red
    assert dirs[-1] == -1


def test_renko_sideways_prints_few_bricks():
    rng = np.random.default_rng(3)
    closes = pd.Series(100 + rng.normal(0, 0.3, 500))  # tight range vs box 2.0
    bricks = renko_bricks(closes, box_size=2.0)
    assert len(bricks) <= 2


def test_renko_from_ohlc_percent_box():
    closes = np.linspace(100, 140, 200)
    df = make_ohlc(closes)
    result = renko_from_ohlc(df, box_mode="percent", percent_box=0.01)
    assert result.box_size == pytest.approx(1.4)
    assert len(result.bricks) > 0
