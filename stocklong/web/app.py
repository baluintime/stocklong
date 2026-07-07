"""Web dashboard: full control of the system from the browser.

Runs on http://localhost:8080 and automates everything that used to be
manual, including the daily Upstox OAuth:

  * "Login with Upstox" -> the Upstox dialog redirects straight back to
    /callback, the token is exchanged and cached automatically. No copying
    codes around. (Set your Upstox app's redirect URI to
    http://localhost:8080/callback.)
  * Run the screener, start/stop the hourly engine loop, inspect open and
    closed positions, and tail the engine logs - all from the dashboard.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections import deque
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template, request

from ..auth import UpstoxAuth
from ..config import Config
from ..runner import Engine
from ..strategies import SignalAction

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)
CYCLE_SECONDS = 3600  # hourly cadence matches the 1H trigger timeframe

log = logging.getLogger(__name__)


class RingBufferHandler(logging.Handler):
    def __init__(self, maxlen: int = 400):
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append(self.format(record))


class DashboardState:
    def __init__(self, config: Config):
        self.config = config
        self.auth = UpstoxAuth(config)
        self._engine: Engine | None = None
        self._engine_lock = threading.Lock()

        self.screener = {"status": "idle", "results": [], "finished_at": None}
        self._screener_lock = threading.Lock()

        self.loop_running = False
        self.last_cycle: dt.datetime | None = None
        self._loop_thread: threading.Thread | None = None

        self.log_handler = RingBufferHandler()
        logging.getLogger("stocklong").addHandler(self.log_handler)
        logging.getLogger("stocklong").setLevel(logging.INFO)

    # --- engine -------------------------------------------------------- #
    def engine(self) -> Engine:
        with self._engine_lock:
            if self._engine is None:
                self._engine = Engine(self.config)
            return self._engine

    def token_status(self) -> dict:
        try:
            self.auth.access_token()
            return {"ok": True, "detail": "token valid for today"}
        except RuntimeError as exc:
            return {"ok": False, "detail": str(exc)}

    @staticmethod
    def market_open(now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now(IST)
        return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE

    # --- screener ------------------------------------------------------ #
    def run_screener_async(self) -> bool:
        with self._screener_lock:
            if self.screener["status"] == "running":
                return False
            self.screener = {"status": "running", "results": [], "finished_at": None}
        threading.Thread(target=self._screener_worker, daemon=True).start()
        return True

    def _screener_worker(self) -> None:
        results = []
        try:
            engine = self.engine()
            for entry in self.config.get("universe", []):
                symbol, key = entry["symbol"], entry["instrument_key"]
                try:
                    df_d = engine.history.daily(
                        key, self.config.get("history.daily_lookback_days", 400))
                    df_h = engine.history.hourly(
                        key, self.config.get("history.hourly_lookback_days", 60))
                    signals = [
                        engine.institutional.evaluate(symbol, df_d, df_h),
                        engine.renko.evaluate(symbol, df_d),
                    ]
                    for s in signals:
                        results.append({
                            "symbol": symbol, "strategy": s.strategy,
                            "action": s.action.value, "reason": s.reason,
                            "entry": s.action is SignalAction.ENTER_LONG,
                        })
                except Exception as exc:
                    results.append({"symbol": symbol, "strategy": "-",
                                    "action": "ERROR", "reason": str(exc),
                                    "entry": False})
            status = "done"
        except Exception as exc:
            log.exception("screener failed")
            results = [{"symbol": "-", "strategy": "-", "action": "ERROR",
                        "reason": str(exc), "entry": False}]
            status = "error"
        with self._screener_lock:
            self.screener = {"status": status, "results": results,
                             "finished_at": dt.datetime.now(IST).isoformat(timespec="seconds")}

    # --- engine loop ---------------------------------------------------- #
    def start_loop(self) -> bool:
        if self.loop_running:
            return False
        self.loop_running = True
        self._loop_thread = threading.Thread(target=self._loop_worker, daemon=True)
        self._loop_thread.start()
        return True

    def stop_loop(self) -> None:
        self.loop_running = False

    def _loop_worker(self) -> None:
        log.info("engine loop started (paper=%s)", self.config.paper_trading)
        while self.loop_running:
            now = dt.datetime.now(IST)
            due = (self.last_cycle is None
                   or (now - self.last_cycle).total_seconds() >= CYCLE_SECONDS)
            if self.market_open(now) and due and self.token_status()["ok"]:
                try:
                    self.engine().run_cycle()
                except Exception:
                    log.exception("engine cycle failed")
                self.last_cycle = now
            time.sleep(15)
        log.info("engine loop stopped")


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.load()
    state = DashboardState(config)
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("index.html",
                               redirect_uri=config.redirect_uri,
                               paper=config.paper_trading)

    # ---- fully automated OAuth: no manual code copying ---------------- #
    @app.get("/login")
    def login():
        return redirect(state.auth.login_url())

    @app.get("/callback")
    def callback():
        error = request.args.get("error")
        if error:
            return render_template("index.html", oauth_error=error,
                                   redirect_uri=config.redirect_uri,
                                   paper=config.paper_trading)
        code = request.args.get("code")
        if not code:
            return redirect("/")
        try:
            state.auth.exchange_code(code)
            log.info("Upstox login successful; token cached")
        except Exception as exc:
            log.exception("token exchange failed")
            return render_template("index.html", oauth_error=str(exc),
                                   redirect_uri=config.redirect_uri,
                                   paper=config.paper_trading)
        return redirect("/")

    # ---- JSON API ------------------------------------------------------ #
    @app.get("/api/status")
    def api_status():
        now = dt.datetime.now(IST)
        return jsonify({
            "token": state.token_status(),
            "paper_trading": config.paper_trading,
            "market_open": state.market_open(now),
            "ist_time": now.isoformat(timespec="seconds"),
            "engine_running": state.loop_running,
            "last_cycle": state.last_cycle.isoformat(timespec="seconds")
                          if state.last_cycle else None,
            "screener_status": state.screener["status"],
        })

    @app.get("/api/positions")
    def api_positions():
        positions = state.engine().store.all_positions()
        return jsonify([{
            "id": p.id, "status": p.status, "symbol": p.symbol,
            "contract": p.trading_symbol, "qty": p.quantity,
            "entry_price": p.entry_price, "entry_date": p.entry_date.isoformat(),
            "exit_price": p.exit_price, "exit_reason": p.exit_reason,
            "expiry": p.expiry.isoformat(), "strategy": p.strategy,
        } for p in positions])

    @app.post("/api/screener")
    def api_screener_run():
        started = state.run_screener_async()
        return jsonify({"started": started, "status": state.screener["status"]})

    @app.get("/api/screener")
    def api_screener_results():
        return jsonify(state.screener)

    @app.post("/api/engine/start")
    def api_engine_start():
        return jsonify({"running": state.start_loop() or state.loop_running})

    @app.post("/api/engine/stop")
    def api_engine_stop():
        state.stop_loop()
        return jsonify({"running": False})

    @app.get("/api/logs")
    def api_logs():
        return jsonify(list(state.log_handler.buffer))

    return app
