#!/usr/bin/env python3
"""End-to-end validation on LIVE market data.

For every symbol in the configured universe, fetches real daily + hourly
candles from Upstox and prints the current state of every blueprint input:
Ichimoku cloud position, TK lines, hourly MACD, Renko brick sequence and
Renko-MACD histogram - plus both strategies' verdicts. Read-only: no orders,
no position-store writes.

Requires a valid daily token: python scripts/login.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong.config import Config
from stocklong.data.historical import HistoricalData
from stocklong.auth import UpstoxAuth
from stocklong.indicators.ichimoku import (
    bullish_cloud, ichimoku, price_above_cloud, tk_cross_up,
)
from stocklong.indicators.macd import macd
from stocklong.indicators.renko import renko_from_ohlc
from stocklong.strategies import InstitutionalFilter, RenkoNoiseKiller

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    cfg = Config.load()
    history = HistoricalData(UpstoxAuth(cfg))
    s1 = InstitutionalFilter()
    s2 = RenkoNoiseKiller()

    from stocklong.runner import Engine
    engine = Engine(cfg)
    universe = engine.load_universe()  # live F&O list from the exchange
    limit = int(cfg.get("scan.top_n", 25)) or len(universe)

    for entry in universe[:limit]:
        symbol, key = entry["symbol"], entry["instrument_key"]
        print(f"\n=== {symbol} ({key}) " + "=" * max(0, 50 - len(symbol)))
        try:
            df_d = history.daily(key, cfg.get("history.daily_lookback_days", 400))
            df_h = history.hourly(key, cfg.get("history.hourly_lookback_days", 60))
        except Exception as exc:
            print(f"  DATA ERROR: {exc}")
            continue
        print(f"  daily candles: {len(df_d)}  (latest {df_d['timestamp'].iloc[-1].date()}"
              f" close {df_d['close'].iloc[-1]:.2f})")
        print(f"  hourly candles: {len(df_h)}")

        ich_d = ichimoku(df_d["high"], df_d["low"], df_d["close"])
        print(f"  [daily ichimoku] above cloud: "
              f"{bool(price_above_cloud(df_d['close'], ich_d).iloc[-1])}, "
              f"green cloud: {bool(bullish_cloud(ich_d).iloc[-1])}, "
              f"spanA {ich_d['senkou_a'].iloc[-1]:.2f} / spanB {ich_d['senkou_b'].iloc[-1]:.2f}")

        ich_h = ichimoku(df_h["high"], df_h["low"], df_h["close"])
        macd_h = macd(df_h["close"])
        tk_recent = int(tk_cross_up(ich_h).iloc[-5:].sum())
        print(f"  [hourly] tenkan {ich_h['tenkan'].iloc[-1]:.2f} vs kijun "
              f"{ich_h['kijun'].iloc[-1]:.2f} (TK crosses last 5 bars: {tk_recent}), "
              f"macd {macd_h['macd'].iloc[-1]:.3f} vs signal {macd_h['signal'].iloc[-1]:.3f}")

        renko = renko_from_ohlc(df_d)
        seq = "".join("G" if d == 1 else "R" for d in renko.bricks["direction"].iloc[-10:])
        macd_r = macd(renko.bricks["close"]) if len(renko.bricks) >= 2 else None
        hist = f"{macd_r['histogram'].iloc[-1]:.3f}" if macd_r is not None else "n/a"
        print(f"  [renko] box {renko.box_size:.2f} (ATR14), {len(renko.bricks)} bricks, "
              f"last 10: {seq or '-'}, renko-MACD hist: {hist}")

        for sig in (s1.evaluate(symbol, df_d, df_h), s2.evaluate(symbol, df_d)):
            print(f"  -> {sig.strategy}: {sig.action.value} | {sig.reason}")


if __name__ == "__main__":
    main()
