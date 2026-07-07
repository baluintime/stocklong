"""Trading engine: orchestrates the daily blueprint cycle.

Each run (typically once after the first hourly candle closes, then hourly):

  1. Reload OPEN positions from SQLite (positions persist across days) and
     reconcile them against the broker's carry-forward positions.
  2. EXITS first - defense before offense:
       a. Ironclad expiry rule: square off <= 5 trading days before expiry.
       b. Renko rule: two consecutive bricks against the position -> liquidate.
       c. Institutional-filter rule: daily close back inside the cloud -> exit.
  3. ENTRIES - scan the LIVE F&O universe (refreshed from the exchange's
     instrument master, never hardcoded) with both strategies in BOTH
     directions; a long signal buys a far-month ITM call, a short signal buys
     a far-month ITM put (delta magnitude 0.70-0.85), always via limit order.
"""

from __future__ import annotations

import datetime as dt
import logging

from .auth import UpstoxAuth
from .broker.upstox_broker import UpstoxBroker
from .config import Config
from .data.historical import HistoricalData
from .data.instruments import InstrumentMaster
from .data.option_chain import OptionChain
from .data.realtime import RestQuotes
from .portfolio import risk
from .portfolio.positions import Position, PositionStore
from .strategies import LONG, SHORT, InstitutionalFilter, RenkoNoiseKiller, SignalAction

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: Config):
        self.config = config
        self.auth = UpstoxAuth(config)
        self.history = HistoricalData(self.auth)
        self.instruments: InstrumentMaster | None = None
        self.universe: list[dict] = []
        self.chain = OptionChain(self.auth)
        self.quotes = RestQuotes(self.auth)
        self.broker = UpstoxBroker(self.auth, paper_trading=config.paper_trading)
        self.store = PositionStore(config.get("store.db_path", "data/positions.db"))

        sf = config.get("strategies.institutional_filter", {})
        self.institutional = InstitutionalFilter(
            trigger_lookback_bars=sf.get("trigger_lookback_bars", 3),
            macd_zero_tolerance_pct=sf.get("macd_zero_tolerance_pct", 0.001),
        )
        sr = config.get("strategies.renko_noise_killer", {})
        self.renko = RenkoNoiseKiller(
            box_mode=sr.get("box_mode", "atr"),
            atr_period=sr.get("atr_period", 14),
            percent_box=sr.get("percent_box", 0.01),
        )

    # ------------------------------------------------------------------ #
    def load_universe(self, force_refresh: bool | None = None) -> list[dict]:
        """Pull the live F&O stock universe from the exchange instrument
        master. Called at application start - the list is never hardcoded."""
        if force_refresh is None:
            force_refresh = bool(self.config.get("universe.refresh_on_start", True))
        self.instruments = InstrumentMaster(force_refresh=force_refresh)
        universe = self.instruments.fo_underlyings()
        max_symbols = int(self.config.get("universe.max_symbols", 0))
        if max_symbols > 0:
            universe = universe[:max_symbols]
        self.universe = universe
        log.info("universe loaded from instrument master: %d F&O underlyings%s",
                 len(universe),
                 f" (capped at {max_symbols})" if max_symbols else "")
        return universe

    def ensure_universe(self) -> list[dict]:
        if not self.universe:
            self.load_universe()
        return self.universe

    def _master(self) -> InstrumentMaster:
        if self.instruments is None:
            self.instruments = InstrumentMaster()
        return self.instruments

    # ------------------------------------------------------------------ #
    def run_cycle(self) -> None:
        log.info("=== cycle start (%s, paper=%s) ===",
                 dt.datetime.now().isoformat(timespec="seconds"),
                 self.config.paper_trading)
        self._reconcile()
        self._manage_exits()
        self._scan_entries()
        log.info("=== cycle end ===")

    # ------------------------------------------------------------------ #
    def _reconcile(self) -> None:
        """Flag locally-open positions the broker no longer holds."""
        if self.config.paper_trading:
            return  # broker book won't contain paper positions
        try:
            broker_keys = self.broker.position_keys()
        except Exception:
            log.exception("could not fetch broker positions; skipping reconcile")
            return
        for orphan in self.store.reconcile(broker_keys):
            log.warning(
                "position #%s (%s %s) is OPEN locally but missing at the broker - "
                "was it squared off manually? Close it via scripts/positions.py.",
                orphan.id, orphan.symbol, orphan.trading_symbol,
            )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _position_direction(pos: Position) -> int:
        return LONG if pos.option_type == "CE" else SHORT

    def _manage_exits(self) -> None:
        days_before = int(self.config.get("risk.square_off_days_before_expiry", 5))
        for pos in self.store.open_positions():
            reason = None

            # (a) Ironclad physical-settlement rule - checked before anything else.
            if risk.must_square_off(pos.expiry, days_before=days_before):
                reason = (f"expiry {pos.expiry} is within {days_before} trading days "
                          "(mandatory pre-physical-settlement square-off)")
            else:
                # (b)/(c) strategy-specific exit on the underlying's daily chart
                try:
                    df_daily = self.history.daily(
                        pos.underlying_key,
                        self.config.get("history.daily_lookback_days", 400),
                    )
                except Exception:
                    log.exception("daily data fetch failed for %s; keeping position", pos.symbol)
                    continue
                direction = self._position_direction(pos)
                strategy = self.renko if pos.strategy == self.renko.name else self.institutional
                signal = strategy.check_exit(pos.symbol, df_daily, direction)
                if signal.action is SignalAction.EXIT:
                    reason = signal.reason

            if reason:
                self._exit_position(pos, reason)

    def _exit_position(self, pos: Position, reason: str) -> None:
        try:
            ltp = self.quotes.ltp([pos.option_key]).get(pos.option_key, 0.0)
        except Exception:
            log.exception("LTP fetch failed for %s", pos.option_key)
            ltp = 0.0
        if ltp <= 0:
            log.error("no LTP for %s; NOT exiting automatically", pos.trading_symbol)
            return
        price = risk.limit_price(
            ltp, "SELL", self.config.get("risk.limit_order_buffer_pct", 0.005)
        )
        result = self.broker.place_limit_order(
            pos.option_key, pos.quantity, "SELL", price, tag=f"exit-{pos.strategy}"
        )
        self.store.close_position(pos.id, exit_price=price, exit_reason=reason)
        log.info("EXIT %s %s x%s @ %s | %s | order=%s",
                 pos.symbol, pos.trading_symbol, pos.quantity, price, reason,
                 result.order_id)

    # ------------------------------------------------------------------ #
    def _scan_entries(self) -> None:
        max_open = int(self.config.get("risk.max_open_positions", 4))
        open_count = len(self.store.open_positions())
        if open_count >= max_open:
            log.info("max open positions reached (%s); skipping entry scan", open_count)
            return

        for entry in self.ensure_universe():
            symbol, key = entry["symbol"], entry["instrument_key"]
            if open_count >= max_open:
                break
            try:
                df_daily = self.history.daily(
                    key, self.config.get("history.daily_lookback_days", 400))
                df_hourly = self.history.hourly(
                    key, self.config.get("history.hourly_lookback_days", 60))
            except Exception:
                log.exception("history fetch failed for %s; skipping", symbol)
                continue

            signals = []
            for direction in (LONG, SHORT):
                if self.config.get("strategies.institutional_filter.enabled", True):
                    signals.append(self.institutional.evaluate(
                        symbol, df_daily, df_hourly, direction))
                if self.config.get("strategies.renko_noise_killer.enabled", True):
                    signals.append(self.renko.evaluate(symbol, df_daily, direction))

            for signal in signals:
                if signal.action not in (SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT):
                    log.debug("%s/%s: %s", symbol, signal.strategy, signal.reason)
                    continue
                if self.store.has_open_position(symbol, signal.strategy):
                    continue
                if self._enter_position(symbol, key, signal.strategy,
                                        signal.reason, signal.direction):
                    open_count += 1

    def _enter_position(self, symbol: str, underlying_key: str,
                        strategy: str, reason: str, direction: int = LONG) -> bool:
        cfg = self.config
        option_type = "CE" if direction == LONG else "PE"
        # 1. far-month expiry (T+2..T+3)
        expiries = self._master().expiries(symbol)
        expiry = risk.select_far_month_expiry(
            expiries,
            months_ahead_min=int(cfg.get("risk.expiry_months_ahead_min", 2)),
            months_ahead_max=int(cfg.get("risk.expiry_months_ahead_max", 3)),
        )
        if not expiry:
            log.warning("%s: no T+2/T+3 month expiry listed; skipping", symbol)
            return False

        # 2. ITM option in the delta band from the option chain greeks
        try:
            chain = self.chain.fetch(underlying_key, expiry)
        except Exception:
            log.exception("%s: option chain fetch failed", symbol)
            return False
        pick = risk.select_itm_option(
            chain,
            option_type=option_type,
            delta_min=float(cfg.get("risk.delta_min", 0.70)),
            delta_max=float(cfg.get("risk.delta_max", 0.85)),
        )
        if not pick:
            log.warning("%s: no %s with |delta| in band for %s; skipping",
                        symbol, option_type, expiry)
            return False

        contracts = {c.instrument_key: c for c in
                     self._master().option_contracts(symbol, option_type)}
        contract = contracts.get(pick.instrument_key)
        if not contract:
            log.warning("%s: %s missing from instrument master", symbol, pick.instrument_key)
            return False

        # 3. size off capital, price as a bounded limit order
        try:
            capital = self.broker.available_capital() if not cfg.paper_trading else \
                float(cfg.get("paper_capital", 1_000_000))
        except Exception:
            log.exception("funds fetch failed; skipping entry")
            return False
        lots = risk.size_position(
            capital, float(cfg.get("risk.capital_per_trade_pct", 0.10)),
            pick.ltp, contract.lot_size,
        )
        if lots < 1:
            log.warning("%s: premium %.2f x lot %s exceeds per-trade budget; skipping",
                        symbol, pick.ltp, contract.lot_size)
            return False
        quantity = lots * contract.lot_size
        price = risk.limit_price(
            pick.ltp, "BUY", float(cfg.get("risk.limit_order_buffer_pct", 0.005)))

        result = self.broker.place_limit_order(
            pick.instrument_key, quantity, "BUY", price, tag=f"entry-{strategy}")
        self.store.open_position(Position(
            symbol=symbol,
            underlying_key=underlying_key,
            option_key=pick.instrument_key,
            trading_symbol=contract.trading_symbol,
            option_type=option_type,
            strike=pick.strike,
            expiry=expiry,
            lot_size=contract.lot_size,
            quantity=quantity,
            entry_price=price,
            entry_date=dt.date.today(),
            strategy=strategy,
            meta={"reason": reason, "delta": pick.delta, "iv": pick.iv,
                  "direction": "LONG" if direction == LONG else "SHORT",
                  "order_id": result.order_id, "paper": result.paper},
        ))
        log.info("ENTER %s %s %s x%s @ %s (delta=%.2f, expiry=%s) | %s | order=%s",
                 "LONG" if direction == LONG else "SHORT", symbol,
                 contract.trading_symbol, quantity, price, pick.delta,
                 expiry, reason, result.order_id)
        return True
