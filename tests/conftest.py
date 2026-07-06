"""Live-data test fixtures.

All market-data tests run against REAL Upstox data - no synthetic price
series anywhere. That means the suite needs a valid access token
(python scripts/login.py) and network access to api.upstox.com; tests that
need live data skip with an explanatory message when either is missing.
"""

from __future__ import annotations

import pytest

from stocklong.auth import UpstoxAuth
from stocklong.config import Config
from stocklong.data.historical import HistoricalData
from stocklong.data.instruments import InstrumentMaster

RELIANCE_KEY = "NSE_EQ|INE002A01018"
RELIANCE_SYMBOL = "RELIANCE"


@pytest.fixture(scope="session")
def config() -> Config:
    return Config.load()


@pytest.fixture(scope="session")
def auth(config) -> UpstoxAuth:
    a = UpstoxAuth(config)
    try:
        a.access_token()
    except RuntimeError as exc:
        pytest.skip(f"live Upstox data unavailable: {exc}")
    return a


@pytest.fixture(scope="session")
def history(auth) -> HistoricalData:
    return HistoricalData(auth)


def _fetch_or_skip(fn, what: str):
    try:
        df = fn()
    except Exception as exc:  # network / API failure -> skip, don't fail
        pytest.skip(f"could not fetch {what}: {exc}")
    if len(df) < 100:
        pytest.skip(f"{what}: only {len(df)} candles returned")
    return df


@pytest.fixture(scope="session")
def daily_real(history):
    """~400 calendar days of real RELIANCE daily candles."""
    return _fetch_or_skip(lambda: history.daily(RELIANCE_KEY, 400), "RELIANCE daily")


@pytest.fixture(scope="session")
def hourly_real(history):
    """~60 calendar days of real RELIANCE hourly candles."""
    return _fetch_or_skip(lambda: history.hourly(RELIANCE_KEY, 60), "RELIANCE hourly")


@pytest.fixture(scope="session")
def universe_daily(history, config):
    """Real daily candles for the first three universe symbols."""
    out = {}
    for entry in config.get("universe", [])[:3]:
        out[entry["symbol"]] = _fetch_or_skip(
            lambda key=entry["instrument_key"]: history.daily(key, 400),
            f"{entry['symbol']} daily",
        )
    return out


@pytest.fixture(scope="session")
def instrument_master():
    master = InstrumentMaster()
    try:
        expiries = master.expiries(RELIANCE_SYMBOL)
    except Exception as exc:
        pytest.skip(f"instrument master unavailable: {exc}")
    if not expiries:
        pytest.skip("no RELIANCE option expiries in instrument master")
    return master
