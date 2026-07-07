"""Historical candle data from the Upstox V3 historical API.

Endpoints used:
  GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to}/{from}
  GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}

Candles arrive as [timestamp, open, high, low, close, volume, open_interest]
in *descending* time order; we return an ascending, indexed DataFrame ready
for indicator math.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from ..auth import UpstoxAuth

BASE = "https://api.upstox.com/v3/historical-candle"
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


class HistoricalData:
    def __init__(self, auth: UpstoxAuth):
        self.auth = auth

    def candles(
        self,
        instrument_key: str,
        unit: str,
        interval: int,
        days_back: int,
        include_today: bool = True,
    ) -> pd.DataFrame:
        """Fetch `days_back` calendar days of candles, optionally merged with
        today's live intraday candles so signals use the latest completed bar."""
        to_date = dt.date.today()
        from_date = to_date - dt.timedelta(days=days_back)
        url = f"{BASE}/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}"
        frames = [self._fetch(url)]

        if include_today and unit in ("minutes", "hours"):
            intraday_url = f"{BASE}/intraday/{instrument_key}/{unit}/{interval}"
            try:
                frames.append(self._fetch(intraday_url))
            except requests.HTTPError:
                pass  # market closed / no intraday data yet

        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
        return df.reset_index(drop=True)

    def daily(self, instrument_key: str, days_back: int = 400) -> pd.DataFrame:
        return self.candles(instrument_key, "days", 1, days_back, include_today=False)

    def hourly(self, instrument_key: str, days_back: int = 60) -> pd.DataFrame:
        return self.candles(instrument_key, "hours", 1, days_back)

    def _fetch(self, url: str) -> pd.DataFrame:
        resp = requests.get(url, headers=self.auth.headers(), timeout=30)
        resp.raise_for_status()
        candles = resp.json().get("data", {}).get("candles", [])
        df = pd.DataFrame(candles, columns=COLUMNS)
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
