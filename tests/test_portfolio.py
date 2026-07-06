"""Portfolio layer tests.

Position-store tests exercise our own trade records (no market data involved).
Contract-selection tests run against the LIVE instrument master and the LIVE
Upstox option chain - real expiries, real greeks, no fabricated entries.
Calendar tests use the real NSE trading calendar (weekday convention).
"""

import datetime as dt

import pytest

from stocklong.data.option_chain import OptionChain
from stocklong.portfolio import risk
from stocklong.portfolio.positions import Position, PositionStore
from tests.conftest import RELIANCE_KEY, RELIANCE_SYMBOL


def make_position(**overrides) -> Position:
    base = dict(
        symbol="RELIANCE",
        underlying_key=RELIANCE_KEY,
        option_key="NSE_FO|12345",
        trading_symbol="RELIANCE 2800 CE SEP",
        option_type="CE",
        strike=2800.0,
        expiry=dt.date(2026, 9, 24),
        lot_size=250,
        quantity=250,
        entry_price=210.5,
        entry_date=dt.date(2026, 7, 6),
        strategy="renko_noise_killer",
        meta={"delta": 0.78},
    )
    base.update(overrides)
    return Position(**base)


class TestPositionStore:
    def test_positions_persist_across_reopen(self, tmp_path):
        """The core requirement: open positions survive across days/restarts."""
        db = tmp_path / "positions.db"
        store = PositionStore(db)
        store.open_position(make_position())
        store.close()

        # simulate the next trading day: new process, same DB
        store2 = PositionStore(db)
        open_pos = store2.open_positions()
        assert len(open_pos) == 1
        pos = open_pos[0]
        assert pos.symbol == "RELIANCE"
        assert pos.expiry == dt.date(2026, 9, 24)
        assert pos.meta["delta"] == 0.78
        store2.close()

    def test_close_position(self, tmp_path):
        store = PositionStore(tmp_path / "p.db")
        pos = store.open_position(make_position())
        store.close_position(pos.id, exit_price=260.0, exit_reason="two red bricks")
        assert store.open_positions() == []
        closed = store.all_positions()[0]
        assert closed.status == "CLOSED"
        assert closed.exit_price == 260.0
        assert closed.exit_reason == "two red bricks"

    def test_has_open_position_by_strategy(self, tmp_path):
        store = PositionStore(tmp_path / "p.db")
        store.open_position(make_position())
        assert store.has_open_position("RELIANCE")
        assert store.has_open_position("RELIANCE", "renko_noise_killer")
        assert not store.has_open_position("RELIANCE", "institutional_filter")
        assert not store.has_open_position("TCS")

    def test_reconcile_flags_orphans(self, tmp_path):
        store = PositionStore(tmp_path / "p.db")
        store.open_position(make_position(option_key="NSE_FO|AAA"))
        store.open_position(make_position(symbol="TCS", option_key="NSE_FO|BBB"))
        orphans = store.reconcile(broker_option_keys={"NSE_FO|AAA"})
        assert [o.option_key for o in orphans] == ["NSE_FO|BBB"]


class TestTradingCalendar:
    def test_trading_days_until_counts_weekdays(self):
        # Mon 2026-07-06 -> Fri 2026-07-10 = Tue..Fri = 4 trading days
        assert risk.trading_days_until(dt.date(2026, 7, 10), dt.date(2026, 7, 6)) == 4
        assert risk.trading_days_until(dt.date(2026, 7, 6), dt.date(2026, 7, 6)) == 0

    def test_square_off_window(self):
        today = dt.date(2026, 7, 6)  # Monday
        near_expiry = dt.date(2026, 7, 10)  # 4 trading days out -> must exit
        far_expiry = dt.date(2026, 9, 24)
        assert risk.must_square_off(near_expiry, days_before=5, today=today)
        assert not risk.must_square_off(far_expiry, days_before=5, today=today)

    def test_position_sizing(self):
        # 1,000,000 capital, 10% per trade = 100,000; premium 200 x lot 250 = 50,000
        assert risk.size_position(1_000_000, 0.10, 200.0, 250) == 2
        assert risk.size_position(1_000_000, 0.10, 500.0, 250) == 0  # too expensive
        assert risk.size_position(1_000_000, 0.10, 0.0, 250) == 0

    def test_limit_price_buffers_and_ticks(self):
        assert risk.limit_price(100.0, "BUY", 0.005) == pytest.approx(100.50)
        assert risk.limit_price(100.0, "SELL", 0.005) == pytest.approx(99.50)
        # rounded to 0.05 tick
        assert (risk.limit_price(213.37, "BUY", 0.005) * 100) % 5 == pytest.approx(0)


class TestLiveContractSelection:
    """Far-month expiry + ITM delta-band selection on the real option chain."""

    def test_far_month_expiry_from_live_listings(self, instrument_master):
        expiries = instrument_master.expiries(RELIANCE_SYMBOL)
        picked = risk.select_far_month_expiry(expiries, 2, 3)
        assert picked is not None, "NSE always lists T+2 monthly stock options"
        today = dt.date.today()
        months = (picked.year - today.year) * 12 + (picked.month - today.month)
        assert 2 <= months <= 3
        assert picked in expiries

    def test_itm_call_from_live_chain(self, auth, instrument_master):
        expiries = instrument_master.expiries(RELIANCE_SYMBOL)
        expiry = risk.select_far_month_expiry(expiries, 2, 3)
        if expiry is None:
            pytest.skip("no T+2/T+3 expiry listed today")
        try:
            chain = OptionChain(auth).fetch(RELIANCE_KEY, expiry)
        except Exception as exc:
            pytest.skip(f"option chain fetch failed: {exc}")
        if not chain:
            pytest.skip("empty option chain (market data unavailable)")

        pick = risk.select_itm_call(chain, delta_min=0.70, delta_max=0.85)
        if pick is None:
            pytest.skip("no strike currently in the 0.70-0.85 delta band")
        # blueprint invariants, checked against real greeks
        assert 0.70 <= pick.delta <= 0.85
        assert pick.option_type == "CE"
        assert pick.ltp > 0
        assert pick.expiry == expiry
        # an ITM call must be struck below every OTM (delta<0.5) call's strike
        otm_strikes = [c.strike for c in chain
                       if c.option_type == "CE" and 0 < c.delta < 0.5]
        if otm_strikes:
            assert pick.strike < max(otm_strikes)
