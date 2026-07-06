"""Order execution and account state on the Upstox REST API.

Blueprint rules enforced here:
  * LIMIT orders only - `place_limit_order` is the only order path; there is
    deliberately no market-order method.
  * product "D" (delivery/carry-forward) so F&O positions are NOT auto-squared
    intraday and persist across days.
  * paper_trading mode (default ON) logs the order instead of sending it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import requests

from ..auth import UpstoxAuth

log = logging.getLogger(__name__)

PLACE_ORDER_URL = "https://api-hft.upstox.com/v3/order/place"
POSITIONS_URL = "https://api.upstox.com/v2/portfolio/short-term-positions"
FUNDS_URL = "https://api.upstox.com/v2/user/get-funds-and-margin"


@dataclass
class OrderResult:
    order_id: str
    paper: bool


class UpstoxBroker:
    def __init__(self, auth: UpstoxAuth, paper_trading: bool = True):
        self.auth = auth
        self.paper_trading = paper_trading

    def place_limit_order(
        self,
        instrument_key: str,
        quantity: int,
        side: str,          # BUY | SELL
        limit_price: float,
        tag: str = "stocklong",
    ) -> OrderResult:
        if side.upper() not in ("BUY", "SELL"):
            raise ValueError(f"invalid side: {side}")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        body = {
            "quantity": quantity,
            "product": "D",            # carry-forward: hold across days
            "validity": "DAY",
            "price": limit_price,
            "tag": tag,
            "instrument_token": instrument_key,
            "order_type": "LIMIT",     # blueprint: strict limit orders only
            "transaction_type": side.upper(),
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }
        if self.paper_trading:
            order_id = f"PAPER-{uuid.uuid4().hex[:10]}"
            log.info("[PAPER] %s %s x%s @ %s (%s)", side, instrument_key, quantity,
                     limit_price, order_id)
            return OrderResult(order_id=order_id, paper=True)

        resp = requests.post(
            PLACE_ORDER_URL,
            headers={**self.auth.headers(), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        order_ids = data.get("order_ids") or [data.get("order_id")]
        return OrderResult(order_id=str(order_ids[0]), paper=False)

    def positions(self) -> list[dict]:
        """Broker-reported positions (includes carried-forward F&O positions)."""
        resp = requests.get(POSITIONS_URL, headers=self.auth.headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", []) or []

    def position_keys(self) -> set[str]:
        return {
            p.get("instrument_token", "")
            for p in self.positions()
            if p.get("quantity", 0) != 0
        }

    def available_capital(self) -> float:
        resp = requests.get(FUNDS_URL, headers=self.auth.headers(), timeout=30)
        resp.raise_for_status()
        equity = (resp.json().get("data") or {}).get("equity") or {}
        return float(equity.get("available_margin") or 0)
