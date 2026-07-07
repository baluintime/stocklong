"""Option chain with greeks from the Upstox API.

GET /v2/option/chain returns, per strike, market data and greeks (delta, theta,
gamma, vega, IV) for both call and put. The risk module uses delta to select
the blueprint's ITM 0.70-0.85 delta band.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

from ..auth import UpstoxAuth

CHAIN_URL = "https://api.upstox.com/v2/option/chain"


@dataclass(frozen=True)
class ChainEntry:
    instrument_key: str
    strike: float
    expiry: dt.date
    option_type: str  # "CE" | "PE"
    ltp: float
    delta: float
    theta: float
    iv: float
    oi: float
    volume: float


class OptionChain:
    def __init__(self, auth: UpstoxAuth):
        self.auth = auth

    def fetch(self, instrument_key: str, expiry: dt.date) -> list[ChainEntry]:
        resp = requests.get(
            CHAIN_URL,
            headers=self.auth.headers(),
            params={"instrument_key": instrument_key, "expiry_date": expiry.isoformat()},
            timeout=30,
        )
        resp.raise_for_status()
        entries: list[ChainEntry] = []
        for row in resp.json().get("data", []):
            strike = float(row.get("strike_price", 0))
            for leg_key, opt_type in (("call_options", "CE"), ("put_options", "PE")):
                leg = row.get(leg_key) or {}
                md = leg.get("market_data") or {}
                greeks = leg.get("option_greeks") or {}
                if not leg.get("instrument_key"):
                    continue
                entries.append(
                    ChainEntry(
                        instrument_key=leg["instrument_key"],
                        strike=strike,
                        expiry=expiry,
                        option_type=opt_type,
                        ltp=float(md.get("ltp") or 0),
                        delta=float(greeks.get("delta") or 0),
                        theta=float(greeks.get("theta") or 0),
                        iv=float(greeks.get("iv") or 0),
                        oi=float(md.get("oi") or 0),
                        volume=float(md.get("volume") or 0),
                    )
                )
        return entries
