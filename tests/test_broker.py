import pytest

from stocklong.broker.upstox_broker import UpstoxBroker


class TestPaperBroker:
    def setup_method(self):
        # auth is never touched in paper mode
        self.broker = UpstoxBroker(auth=None, paper_trading=True)

    def test_paper_order_never_hits_network(self):
        result = self.broker.place_limit_order("NSE_FO|12345", 250, "BUY", 210.5)
        assert result.paper
        assert result.order_id.startswith("PAPER-")

    def test_rejects_bad_side(self):
        with pytest.raises(ValueError):
            self.broker.place_limit_order("NSE_FO|12345", 250, "SHORT", 210.5)

    def test_rejects_non_positive_quantity(self):
        with pytest.raises(ValueError):
            self.broker.place_limit_order("NSE_FO|12345", 0, "BUY", 210.5)

    def test_no_market_order_path_exists(self):
        # blueprint guardrail: strict limit orders only
        assert not hasattr(self.broker, "place_market_order")
