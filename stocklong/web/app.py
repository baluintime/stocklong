"""FastAPI dashboard: full control of the system from the browser.

Runs on http://localhost:8080 and automates everything:

  * Startup: the F&O stock universe is refreshed from the exchange's live
    instrument master - nothing hardcoded in config files.
  * "Login with Upstox" -> the OAuth dialog redirects back to /callback and
    the day's token is exchanged and cached automatically.
  * Confluence scanner scores every stock 0-100 in BOTH directions (long =
    buy CE, short = buy PE) and the scoreboard ranks the best side first.
    Scans re-run automatically on an interval; the page refreshes itself.
  * Hourly engine loop (exits -> entries), positions, and live logs.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections import deque
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import scanner
from ..auth import UpstoxAuth
from ..config import Config
from ..runner import Engine

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)
CYCLE_SECONDS = 3600  # hourly engine cadence matches the 1H trigger timeframe

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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

        self.universe_status = {"count": 0, "loaded_at": None, "error": None}
        self.scan = {"status": "idle", "progress": 0, "total": 0,
                     "rows": [], "updated_at": None}
        self._scan_lock = threading.Lock()

        self.loop_running = False
        self.last_cycle: dt.datetime | None = None

        self._auto_thread: threading.Thread | None = None
        self._auto_running = False

        self.log_handler = RingBufferHandler()
        logging.getLogger("stocklong").addHandler(self.log_handler)
        logging.getLogger("stocklong").setLevel(logging.INFO)

    # --- engine / universe ---------------------------------------------- #
    def engine(self) -> Engine:
        with self._engine_lock:
            if self._engine is None:
                self._engine = Engine(self.config)
            return self._engine

    def load_universe_async(self) -> None:
        threading.Thread(target=self._load_universe, daemon=True).start()

    def _load_universe(self) -> None:
        try:
            universe = self.engine().load_universe()
            self.universe_status = {
                "count": len(universe),
                "loaded_at": dt.datetime.now(IST).isoformat(timespec="seconds"),
                "error": None,
            }
        except Exception as exc:
            log.exception("universe refresh failed")
            self.universe_status = {"count": 0, "loaded_at": None, "error": str(exc)}

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

    # --- scanner ---------------------------------------------------------- #
    def run_scan_async(self) -> bool:
        with self._scan_lock:
            if self.scan["status"] == "running":
                return False
            self.scan = {"status": "running", "progress": 0, "total": 0,
                         "rows": self.scan["rows"], "updated_at": self.scan["updated_at"]}
        threading.Thread(target=self._scan_worker, daemon=True).start()
        return True

    def _scan_worker(self) -> None:
        try:
            engine = self.engine()
            universe = engine.ensure_universe()
            self.scan["total"] = len(universe)
            cfg = self.config
            lb = int(cfg.get("strategies.institutional_filter.trigger_lookback_bars", 3))
            tol = float(cfg.get("strategies.institutional_filter.macd_zero_tolerance_pct", 0.001))
            rows = []
            for i, entry in enumerate(universe, 1):
                symbol, key = entry["symbol"], entry["instrument_key"]
                self.scan["progress"] = i
                try:
                    df_d = engine.history.daily(
                        key, cfg.get("history.daily_lookback_days", 400))
                    df_h = engine.history.hourly(
                        key, cfg.get("history.hourly_lookback_days", 60))
                    both = scanner.score_both_sides(
                        symbol, key, df_d, df_h,
                        lookback_bars=lb, macd_zero_tolerance_pct=tol)
                    best = scanner.best_side(both)
                    rows.append({
                        "symbol": best.symbol, "side": best.side,
                        "score": best.score, "close": round(best.close, 2),
                        "components": best.components,
                        "long_score": both[0].score, "short_score": both[1].score,
                    })
                except Exception as exc:
                    log.warning("scan %s failed: %s", symbol, exc)
            rows.sort(key=lambda r: r["score"], reverse=True)
            top_n = int(self.config.get("scan.top_n", 25))
            with self._scan_lock:
                self.scan = {
                    "status": "done", "progress": len(universe), "total": len(universe),
                    "rows": rows[:top_n] if top_n else rows,
                    "updated_at": dt.datetime.now(IST).isoformat(timespec="seconds"),
                }
            log.info("scan complete: %d symbols scored", len(rows))
        except Exception as exc:
            log.exception("scan failed")
            with self._scan_lock:
                self.scan = {"status": "error", "progress": 0, "total": 0,
                             "rows": [], "updated_at": None, "error": str(exc)}

    # --- automatic re-scan ------------------------------------------------ #
    def start_auto_scan(self) -> None:
        if self._auto_running:
            return
        self._auto_running = True
        self._auto_thread = threading.Thread(target=self._auto_worker, daemon=True)
        self._auto_thread.start()

    def _auto_worker(self) -> None:
        interval = int(self.config.get("scan.auto_interval_minutes", 15)) * 60
        last_scan = 0.0
        while self._auto_running:
            now = time.time()
            token_ok = self.token_status()["ok"]
            never_ran = self.scan["updated_at"] is None
            due = now - last_scan >= interval
            if token_ok and (never_ran or (due and self.market_open())):
                if self.run_scan_async():
                    last_scan = now
            time.sleep(20)

    # --- engine loop -------------------------------------------------------- #
    def start_loop(self) -> bool:
        if self.loop_running:
            return False
        self.loop_running = True
        threading.Thread(target=self._loop_worker, daemon=True).start()
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


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    state = DashboardState(config)
    app = FastAPI(title="StockLong", docs_url=None, redoc_url=None)
    app.state.dashboard = state

    @app.on_event("startup")
    def _startup() -> None:
        # Refresh the F&O universe from the exchange on every application
        # start (universe.refresh_on_start) and begin the auto-scan loop.
        state.load_universe_async()
        state.start_auto_scan()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return TEMPLATES.TemplateResponse(request, "index.html", {
            "redirect_uri": config.redirect_uri,
            "paper": config.paper_trading,
            "oauth_error": None,
        })

    # ---- fully automated OAuth: no manual code copying ----------------- #
    @app.get("/login")
    def login():
        return RedirectResponse(state.auth.login_url())

    @app.get("/callback")
    def callback(request: Request, code: str | None = None, error: str | None = None):
        if error or not code:
            return TEMPLATES.TemplateResponse(request, "index.html", {
                "redirect_uri": config.redirect_uri,
                "paper": config.paper_trading,
                "oauth_error": error or "no authorization code returned",
            })
        try:
            state.auth.exchange_code(code)
            log.info("Upstox login successful; token cached")
        except Exception as exc:
            log.exception("token exchange failed")
            return TEMPLATES.TemplateResponse(request, "index.html", {
                "redirect_uri": config.redirect_uri,
                "paper": config.paper_trading,
                "oauth_error": str(exc),
            })
        return RedirectResponse("/")

    # ---- JSON API -------------------------------------------------------- #
    @app.get("/api/status")
    def api_status():
        now = dt.datetime.now(IST)
        return {
            "token": state.token_status(),
            "paper_trading": config.paper_trading,
            "market_open": state.market_open(now),
            "ist_time": now.isoformat(timespec="seconds"),
            "engine_running": state.loop_running,
            "last_cycle": state.last_cycle.isoformat(timespec="seconds")
                          if state.last_cycle else None,
            "universe": state.universe_status,
            "scan_status": state.scan["status"],
            "scan_progress": state.scan["progress"],
            "scan_total": state.scan["total"],
        }

    @app.get("/api/scan")
    def api_scan():
        return state.scan

    @app.post("/api/scan")
    def api_scan_run():
        return {"started": state.run_scan_async(), "status": state.scan["status"]}

    @app.get("/api/positions")
    def api_positions():
        positions = state.engine().store.all_positions()
        return [{
            "id": p.id, "status": p.status, "symbol": p.symbol,
            "contract": p.trading_symbol, "side": p.meta.get("direction", "LONG"),
            "qty": p.quantity,
            "entry_price": p.entry_price, "entry_date": p.entry_date.isoformat(),
            "exit_price": p.exit_price, "exit_reason": p.exit_reason,
            "expiry": p.expiry.isoformat(), "strategy": p.strategy,
        } for p in positions]

    @app.post("/api/engine/start")
    def api_engine_start():
        state.start_loop()
        return {"running": state.loop_running}

    @app.post("/api/engine/stop")
    def api_engine_stop():
        state.stop_loop()
        return {"running": False}

    @app.get("/api/logs")
    def api_logs():
        return list(state.log_handler.buffer)

    return app
