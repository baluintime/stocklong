"""StockLong - NSE options buying system on the Upstox API.

Implements the "NSE Options Buying Blueprint":
  * Strategy 1: Multi-Timeframe Institutional Filter (Daily Ichimoku + hourly TK cross + hourly MACD)
  * Strategy 2: Daily Renko Noise-Killer (ATR/percent bricks + Renko MACD)
  * Risk guardrails: deep ITM (delta 0.70-0.85), far-month expiry, limit orders only,
    mandatory square-off 5 trading days before expiry, positions persisted across days.
"""

__version__ = "0.1.0"
