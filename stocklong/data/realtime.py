"""Real-time market data.

Two access paths:

1. `LiveFeed` - Upstox V3 market-data websocket via the official SDK
   (`upstox-python-sdk`). Push-based LTP/full quotes; the SDK handles the
   protobuf decoding and reconnects.

2. `RestQuotes` - simple REST LTP polling fallback (GET /v2/market-quote/ltp)
   for environments where the websocket is unavailable.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import requests

from ..auth import UpstoxAuth

log = logging.getLogger(__name__)

LTP_URL = "https://api.upstox.com/v2/market-quote/ltp"

TickHandler = Callable[[str, float], None]  # (instrument_key, ltp)


class RestQuotes:
    """Polling quotes over REST - works everywhere, ~1 req/sec rate limits apply."""

    def __init__(self, auth: UpstoxAuth):
        self.auth = auth

    def ltp(self, instrument_keys: list[str]) -> dict[str, float]:
        resp = requests.get(
            LTP_URL,
            headers=self.auth.headers(),
            params={"instrument_key": ",".join(instrument_keys)},
            timeout=15,
        )
        resp.raise_for_status()
        out: dict[str, float] = {}
        for item in (resp.json().get("data") or {}).values():
            key = item.get("instrument_token")
            if key:
                out[key] = float(item.get("last_price") or 0)
        return out


class LiveFeed:
    """Websocket LTP stream. Register a handler, call start(); ticks arrive on a
    background thread. Requires the `upstox-python-sdk` package."""

    def __init__(self, auth: UpstoxAuth, instrument_keys: list[str], mode: str = "ltpc"):
        self.auth = auth
        self.instrument_keys = list(instrument_keys)
        self.mode = mode
        self._handlers: list[TickHandler] = []
        self._streamer = None
        self._lock = threading.Lock()
        self.latest: dict[str, float] = {}

    def on_tick(self, handler: TickHandler) -> None:
        self._handlers.append(handler)

    def start(self) -> None:
        try:
            import upstox_client
        except ImportError as exc:
            raise RuntimeError(
                "upstox-python-sdk is required for the websocket feed. "
                "Install it or use RestQuotes instead."
            ) from exc

        configuration = upstox_client.Configuration()
        configuration.access_token = self.auth.access_token()
        self._streamer = upstox_client.MarketDataStreamerV3(
            upstox_client.ApiClient(configuration), self.instrument_keys, self.mode
        )
        self._streamer.on("message", self._on_message)
        self._streamer.on("error", lambda err: log.error("feed error: %s", err))
        self._streamer.auto_reconnect(True, 5, 10)
        self._streamer.connect()

    def subscribe(self, instrument_keys: list[str]) -> None:
        if self._streamer:
            self._streamer.subscribe(instrument_keys, self.mode)
        self.instrument_keys.extend(k for k in instrument_keys if k not in self.instrument_keys)

    def stop(self) -> None:
        if self._streamer:
            self._streamer.disconnect()

    def _on_message(self, message: dict) -> None:
        feeds = (message or {}).get("feeds") or {}
        for key, payload in feeds.items():
            ltp = self._extract_ltp(payload)
            if ltp is None:
                continue
            with self._lock:
                self.latest[key] = ltp
            for handler in self._handlers:
                try:
                    handler(key, ltp)
                except Exception:
                    log.exception("tick handler failed for %s", key)

    @staticmethod
    def _extract_ltp(payload: dict) -> float | None:
        ltpc = payload.get("ltpc")
        if ltpc is None:
            full = payload.get("fullFeed") or {}
            ltpc = (full.get("marketFF") or full.get("indexFF") or {}).get("ltpc")
        if ltpc and ltpc.get("ltp") is not None:
            return float(ltpc["ltp"])
        return None
