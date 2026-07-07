"""NSE instrument master: lookup of option contracts for an underlying.

Upstox publishes a daily instrument master. We use the NSE JSON dump to map an
underlying symbol to its stock option contracts (strike, expiry, lot size,
instrument_key) so the risk module can pick a far-month ITM contract.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
from dataclasses import dataclass
from pathlib import Path

import requests

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"


@dataclass(frozen=True)
class OptionContract:
    instrument_key: str
    trading_symbol: str
    underlying_symbol: str
    strike: float
    expiry: dt.date
    option_type: str  # "CE" | "PE"
    lot_size: int


class InstrumentMaster:
    def __init__(self, cache_dir: str | Path = "data", force_refresh: bool = False):
        self.cache_path = Path(cache_dir) / f"nse_instruments_{dt.date.today()}.json"
        if force_refresh and self.cache_path.exists():
            self.cache_path.unlink()
        self._records: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._records is not None:
            return self._records
        if self.cache_path.exists():
            self._records = json.loads(self.cache_path.read_text())
            return self._records
        resp = requests.get(INSTRUMENTS_URL, timeout=120)
        resp.raise_for_status()
        raw = gzip.GzipFile(fileobj=io.BytesIO(resp.content)).read()
        self._records = json.loads(raw)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._records))
        return self._records

    def option_contracts(
        self, underlying_symbol: str, option_type: str = "CE"
    ) -> list[OptionContract]:
        """All listed stock option contracts for an underlying, sorted by expiry/strike."""
        out: list[OptionContract] = []
        for rec in self._load():
            if rec.get("segment") != "NSE_FO":
                continue
            if rec.get("instrument_type") != option_type:
                continue
            if rec.get("asset_symbol") != underlying_symbol:
                continue
            expiry_ms = rec.get("expiry")
            if expiry_ms is None:
                continue
            out.append(
                OptionContract(
                    instrument_key=rec["instrument_key"],
                    trading_symbol=rec.get("trading_symbol", ""),
                    underlying_symbol=underlying_symbol,
                    strike=float(rec.get("strike_price", 0)),
                    expiry=dt.datetime.fromtimestamp(expiry_ms / 1000).date(),
                    option_type=option_type,
                    lot_size=int(rec.get("lot_size", 0)),
                )
            )
        out.sort(key=lambda c: (c.expiry, c.strike))
        return out

    def expiries(self, underlying_symbol: str) -> list[dt.date]:
        return sorted({c.expiry for c in self.option_contracts(underlying_symbol)})

    def fo_underlyings(self) -> list[dict]:
        """The live NSE F&O stock universe, derived from listed option contracts.

        Nothing is hardcoded: every equity underlying that currently has stock
        options listed on NSE is returned, straight from the day's instrument
        master. Each entry: {symbol, instrument_key (NSE_EQ|...), lot_size}."""
        seen: dict[str, dict] = {}
        for rec in self._load():
            if rec.get("segment") != "NSE_FO":
                continue
            if rec.get("instrument_type") not in ("CE", "PE"):
                continue
            symbol = rec.get("asset_symbol")
            underlying_key = rec.get("underlying_key", "")
            if not symbol or not underlying_key.startswith("NSE_EQ"):
                continue  # index options (NIFTY etc.) have no NSE_EQ underlying
            if symbol not in seen:
                seen[symbol] = {
                    "symbol": symbol,
                    "instrument_key": underlying_key,
                    "lot_size": int(rec.get("lot_size", 0)),
                }
        return sorted(seen.values(), key=lambda x: x["symbol"])
