# StockLong — NSE Options Buying System (Upstox API)

Systematic long-options engine for NSE stock options, implementing the
**NSE Options Buying Blueprint**:

| Blueprint element | Where it lives |
|---|---|
| Strategy 1: Multi-Timeframe Institutional Filter (Daily Ichimoku cloud + hourly TK cross + hourly MACD near zero) | `stocklong/strategies/institutional_filter.py` |
| Strategy 2: Daily Renko Noise-Killer (ATR/1% bricks + Renko-MACD, 2-green entry / 2-red exit) | `stocklong/strategies/renko_noise_killer.py` |
| Ichimoku (9, 26, 52), MACD (12, 26, 9), Renko engine | `stocklong/indicators/` |
| Historical candles (daily + hourly, Upstox V3 API) | `stocklong/data/historical.py` |
| Real-time data (V3 websocket via official SDK + REST LTP fallback) | `stocklong/data/realtime.py` |
| Option chain greeks → ITM delta 0.70–0.85 selection | `stocklong/data/option_chain.py`, `stocklong/portfolio/risk.py` |
| Far-month (T+2/T+3) expiry selection, limit-orders-only, position sizing | `stocklong/portfolio/risk.py` |
| **Multi-day position persistence** (SQLite, survives restarts; broker reconciliation) | `stocklong/portfolio/positions.py` |
| Mandatory square-off ≥5 trading days before expiry (physical settlement rule) | `stocklong/portfolio/risk.py` + `stocklong/runner.py` |
| Orders (LIMIT only, product `D` carry-forward, paper mode) | `stocklong/broker/upstox_broker.py` |

## Setup

```bash
pip install -r requirements.txt
export UPSTOX_API_KEY="your-app-key"
export UPSTOX_API_SECRET="your-app-secret"
export UPSTOX_REDIRECT_URI="http://127.0.0.1:5000/callback"   # must match your app
```

Upstox access tokens expire daily (~3:30 AM IST), so log in each morning:

```bash
python scripts/login.py            # prints the authorization URL
# open it, authorize, copy the ?code=... value from the redirect
python scripts/login.py <code>     # caches data/access_token.json
```

## Usage

```bash
# Dry scan: run both screeners across the Nifty-50 universe, print signals only
python scripts/screener.py

# Full engine: hourly cycle during market hours (exits first, then entries),
# with a live websocket LTP feed. Positions persist in data/positions.db
# across restarts AND across days.
python scripts/run_live.py

# Inspect / manually close persisted positions
python scripts/positions.py
python scripts/positions.py close 3 245.50 "manual square-off"
```

## How a position lives across multiple days

1. Orders are placed with product **`D` (carry-forward)** so the broker does
   not auto-square them at 3:20 PM.
2. Every entry/exit is recorded in **SQLite (`data/positions.db`)** — the
   process can stop, the token can expire, the machine can reboot; the next
   run reloads the open book.
3. On each cycle the engine **reconciles** the local book against the broker's
   carry-forward positions and warns about anything squared off manually.
4. Exits are evaluated **before** entries on every cycle:
   - expiry within 5 trading days → mandatory square-off (physical-settlement rule),
   - two consecutive red daily Renko bricks → liquidate (Renko strategy),
   - daily close back inside the Ichimoku cloud → exit (institutional filter).

## Safety

- **`paper_trading: true` is the default** in `config.yaml`. No real order is
  sent until you flip it to `false`.
- The broker wrapper has **no market-order method** — limit orders only, with
  a configurable price buffer rounded to the exchange tick.
- Credentials come from environment variables only; the token cache and the
  position DB live under `data/`, which is git-ignored.

## Tests

```bash
pytest
```

Covers the indicator math (Ichimoku/MACD/Renko), both strategies' entry/exit
logic, the risk guardrails (expiry window, delta band, sizing, limit pricing),
and multi-day persistence of the position store.

## Disclaimer

Educational/algorithmic implementation of a trading blueprint. Options buying
carries a high probability of loss; nothing here is investment advice. Test in
paper mode extensively before deploying real capital.
