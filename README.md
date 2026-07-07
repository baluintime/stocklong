# StockLong — NSE Options Buying System (Upstox API)

Systematic long-options engine for NSE stock options, implementing the
**NSE Options Buying Blueprint**:

| Blueprint element | Where it lives |
|---|---|
| Strategy 1: Multi-Timeframe Institutional Filter — long AND short mirrors (Daily Ichimoku cloud + hourly TK cross + hourly MACD near zero) | `stocklong/strategies/institutional_filter.py` |
| Strategy 2: Daily Renko Noise-Killer — long AND short mirrors (ATR/1% bricks + Renko-MACD, 2-brick entry/exit) | `stocklong/strategies/renko_noise_killer.py` |
| Confluence scanner: 0–100 score per stock on BOTH sides, ranked scoreboard | `stocklong/scanner.py` |
| **Live F&O universe** from the exchange instrument master at every start — no hardcoded stock lists | `stocklong/data/instruments.py` (`fo_underlyings`) |
| Ichimoku (9, 26, 52), MACD (12, 26, 9), Renko engine | `stocklong/indicators/` |
| Historical candles (daily + hourly, Upstox V3 API) | `stocklong/data/historical.py` |
| Real-time data (V3 websocket via official SDK + REST LTP fallback) | `stocklong/data/realtime.py` |
| Option chain greeks → ITM \|delta\| 0.70–0.85 (calls for long, puts for short) | `stocklong/data/option_chain.py`, `stocklong/portfolio/risk.py` |
| Far-month (T+2/T+3) expiry selection, limit-orders-only, position sizing | `stocklong/portfolio/risk.py` |
| **Multi-day position persistence** (SQLite, survives restarts; broker reconciliation) | `stocklong/portfolio/positions.py` |
| Mandatory square-off ≥5 trading days before expiry (physical settlement rule) | `stocklong/portfolio/risk.py` + `stocklong/runner.py` |
| Orders (LIMIT only, product `D` carry-forward, paper mode) | `stocklong/broker/upstox_broker.py` |
| FastAPI dashboard, auto-refreshing (OAuth, scoreboard, engine, positions, logs) | `stocklong/web/` |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env    # then edit .env with your Upstox app key/secret
```

Credentials live in the git-ignored `.env` file at the project root (loaded
automatically on startup); shell environment variables with the same names
take precedence if set:

```
UPSTOX_API_KEY=your-app-api-key
UPSTOX_API_SECRET=your-app-secret
UPSTOX_REDIRECT_URI=http://localhost:8080/callback   # must match your app
```

## Web dashboard (FastAPI, recommended)

Everything runs from the browser — including the daily Upstox login, with no
manual code copying:

```bash
python scripts/webapp.py       # then open http://localhost:8080
```

- **Startup**: the F&O stock universe is rebuilt from the exchange's live
  instrument master — no stock list is hardcoded anywhere.
- **Login with Upstox** button → the OAuth redirect lands on
  `http://localhost:8080/callback` and the day's token is cached
  automatically. Set exactly that redirect URI on your Upstox app
  (https://account.upstox.com/developer/apps) and in `.env`.
- **Confluence scoreboard**: every stock scored 0–100 on BOTH sides
  (LONG = buy ITM call, SHORT = buy ITM put), ranked by the stronger side —
  the highest-success setups float to the top. Component breakdown per row
  (Macro cloud 30 / TK 20 / MACD 20 / Renko 30).
- **Two full scans a day, one pick**: the full universe is fetched only at
  the **opening** and again near the **close** (`scan.closing_scan_time`).
  The opening scan's #1 setup is locked in as **today's pick** and tracked
  every `scan.track_interval_minutes` for the rest of the session (LTP +
  fresh score snapshots in the "Today's pick" panel). The engine's entry
  hunting narrows to the pick too, so intraday API load is just a few calls
  per interval instead of hundreds. The page refreshes itself, no reloads.
- **Start engine loop** → hourly blueprint cycle (exits → entries, both
  directions) during market hours; positions persist in SQLite across
  days/restarts.
- Live positions table (with LONG/SHORT badges) and streaming engine log.

Upstox tokens expire daily (~3:30 AM IST) — each morning is just one click on
the dashboard's login button.

## CLI usage (headless alternative)

```bash
python scripts/login.py            # prints the authorization URL
# open it, authorize, copy the ?code=... value from the redirect
python scripts/login.py <code>     # caches data/access_token.json

# Dry scan: run both screeners across the Nifty-50 universe, print signals only
python scripts/screener.py

# Full live-data validation: prints every indicator input (cloud position,
# TK lines, hourly MACD, Renko bricks) and both strategies' verdicts per symbol
python scripts/validate_live.py

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

## Tests — real live data only

```bash
python scripts/login.py <code>   # market-data tests need a live token
pytest
```

There is **no synthetic price data anywhere** — the engine trades only on
live Upstox data, and the test suite validates against it too:

- Indicator tests fetch real RELIANCE daily/hourly candles and verify the
  math by closed-form recomputation and structural invariants.
- Strategy tests re-derive the blueprint conditions from the same real data
  and assert the strategy's verdict agrees, whatever the market is doing.
- Contract-selection tests hit the live instrument master and the live
  option chain (real expiries, real delta greeks).
- Position-store and paper-broker tests exercise our own trade records
  (no market data involved).

Live-data tests skip with an explanatory message when no token is cached or
the API is unreachable; the position-store/calendar/broker tests always run.

## Disclaimer

Educational/algorithmic implementation of a trading blueprint. Options buying
carries a high probability of loss; nothing here is investment advice. Test in
paper mode extensively before deploying real capital.
