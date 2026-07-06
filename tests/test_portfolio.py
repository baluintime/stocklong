import datetime as dt

import pytest

from stocklong.data.option_chain import ChainEntry
from stocklong.portfolio import risk
from stocklong.portfolio.positions import Position, PositionStore


def make_position(**overrides) -> Position:
    base = dict(
        symbol="RELIANCE",
        underlying_key="NSE_EQ|INE002A01018",
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


class TestRisk:
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

    def test_far_month_expiry_selection(self):
        today = dt.date(2026, 7, 6)
        expiries = [
            dt.date(2026, 7, 30), dt.date(2026, 8, 27),
            dt.date(2026, 9, 24), dt.date(2026, 10, 29),
        ]
        picked = risk.select_far_month_expiry(expiries, 2, 3, today=today)
        assert picked == dt.date(2026, 9, 24)  # T+2 months, nearest in band

    def test_far_month_expiry_none_when_missing(self):
        assert risk.select_far_month_expiry(
            [dt.date(2026, 7, 30)], 2, 3, today=dt.date(2026, 7, 6)) is None

    def test_itm_call_selection_prefers_band_middle(self):
        def entry(delta, strike):
            return ChainEntry(
                instrument_key=f"NSE_FO|{strike}", strike=strike,
                expiry=dt.date(2026, 9, 24), option_type="CE",
                ltp=100.0, delta=delta, theta=-1.0, iv=20.0, oi=5000, volume=100,
            )
        chain = [entry(0.55, 3000), entry(0.72, 2800), entry(0.78, 2700),
                 entry(0.84, 2600), entry(0.95, 2400)]
        pick = risk.select_itm_call(chain)
        assert pick.delta == 0.78  # closest to band middle 0.775

    def test_itm_call_selection_rejects_out_of_band(self):
        otm = ChainEntry(
            instrument_key="NSE_FO|X", strike=3000, expiry=dt.date(2026, 9, 24),
            option_type="CE", ltp=40.0, delta=0.30, theta=-2.0, iv=25.0,
            oi=1000, volume=50,
        )
        assert risk.select_itm_call([otm]) is None

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
