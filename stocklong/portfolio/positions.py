"""Persistent position store.

Open option positions live in SQLite so they survive process restarts and
carry across trading days (the strategies here hold for days to weeks).
Each morning the runner reloads open positions, re-evaluates exits, and
reconciles against the broker's own position/holdings report.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,                -- underlying, e.g. RELIANCE
    underlying_key TEXT NOT NULL,        -- NSE_EQ|...
    option_key TEXT NOT NULL,            -- NSE_FO|...
    trading_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,           -- CE / PE
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,                -- ISO date
    lot_size INTEGER NOT NULL,
    quantity INTEGER NOT NULL,           -- total quantity (lots * lot_size)
    entry_price REAL NOT NULL,
    entry_date TEXT NOT NULL,            -- ISO date
    strategy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN / CLOSED
    exit_price REAL,
    exit_date TEXT,
    exit_reason TEXT,
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


@dataclass
class Position:
    symbol: str
    underlying_key: str
    option_key: str
    trading_symbol: str
    option_type: str
    strike: float
    expiry: dt.date
    lot_size: int
    quantity: int
    entry_price: float
    entry_date: dt.date
    strategy: str
    status: str = "OPEN"
    exit_price: float | None = None
    exit_date: dt.date | None = None
    exit_reason: str | None = None
    meta: dict = field(default_factory=dict)
    id: int | None = None


class PositionStore:
    def __init__(self, db_path: str | Path = "data/positions.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def open_position(self, pos: Position) -> Position:
        cur = self._conn.execute(
            """INSERT INTO positions
               (symbol, underlying_key, option_key, trading_symbol, option_type,
                strike, expiry, lot_size, quantity, entry_price, entry_date,
                strategy, status, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)""",
            (
                pos.symbol, pos.underlying_key, pos.option_key, pos.trading_symbol,
                pos.option_type, pos.strike, pos.expiry.isoformat(), pos.lot_size,
                pos.quantity, pos.entry_price, pos.entry_date.isoformat(),
                pos.strategy, json.dumps(pos.meta),
            ),
        )
        self._conn.commit()
        pos.id = cur.lastrowid
        return pos

    def close_position(
        self, position_id: int, exit_price: float, exit_reason: str,
        exit_date: dt.date | None = None,
    ) -> None:
        self._conn.execute(
            """UPDATE positions
               SET status='CLOSED', exit_price=?, exit_date=?, exit_reason=?
               WHERE id=? AND status='OPEN'""",
            (
                exit_price,
                (exit_date or dt.date.today()).isoformat(),
                exit_reason,
                position_id,
            ),
        )
        self._conn.commit()

    def open_positions(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_date"
        ).fetchall()
        return [self._to_position(r) for r in rows]

    def has_open_position(self, symbol: str, strategy: str | None = None) -> bool:
        query = "SELECT COUNT(*) FROM positions WHERE status='OPEN' AND symbol=?"
        params: list = [symbol]
        if strategy:
            query += " AND strategy=?"
            params.append(strategy)
        return self._conn.execute(query, params).fetchone()[0] > 0

    def all_positions(self) -> list[Position]:
        rows = self._conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
        return [self._to_position(r) for r in rows]

    def reconcile(self, broker_option_keys: set[str]) -> list[Position]:
        """Return locally-OPEN positions that the broker no longer reports.

        These were likely squared off manually (or auto-squared by the broker);
        the caller should investigate and close them locally with the actual
        exit price. Nothing is mutated here - reconciliation is a report."""
        return [p for p in self.open_positions() if p.option_key not in broker_option_keys]

    @staticmethod
    def _to_position(row: sqlite3.Row) -> Position:
        return Position(
            id=row["id"],
            symbol=row["symbol"],
            underlying_key=row["underlying_key"],
            option_key=row["option_key"],
            trading_symbol=row["trading_symbol"],
            option_type=row["option_type"],
            strike=row["strike"],
            expiry=dt.date.fromisoformat(row["expiry"]),
            lot_size=row["lot_size"],
            quantity=row["quantity"],
            entry_price=row["entry_price"],
            entry_date=dt.date.fromisoformat(row["entry_date"]),
            strategy=row["strategy"],
            status=row["status"],
            exit_price=row["exit_price"],
            exit_date=dt.date.fromisoformat(row["exit_date"]) if row["exit_date"] else None,
            exit_reason=row["exit_reason"],
            meta=json.loads(row["meta"] or "{}"),
        )

    def close(self) -> None:
        self._conn.close()
