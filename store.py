from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from models import Direction, Profile, Signal, StrategyMode, Trade


class Store:
    def __init__(
        self,
        path: str,
        start_balance: float,
        default_amount: float,
        default_expiry: int,
        default_min_confidence: float,
    ) -> None:
        self.path = path
        self.start_balance = start_balance
        self.default_amount = default_amount
        self.default_expiry = default_expiry
        self.default_min_confidence = default_min_confidence
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    chat_id INTEGER PRIMARY KEY,
                    demo_balance REAL NOT NULL,
                    trade_amount REAL NOT NULL,
                    expiry_seconds INTEGER NOT NULL,
                    min_confidence REAL NOT NULL,
                    auto_demo INTEGER NOT NULL DEFAULT 0,
                    strategy_on INTEGER NOT NULL DEFAULT 0,
                    strategy_mode TEXT NOT NULL DEFAULT 'NORMALE',
                    stopped INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    amount REAL NOT NULL,
                    expiry_seconds INTEGER NOT NULL,
                    confidence REAL,
                    status TEXT NOT NULL,
                    pnl REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    strategy_variant TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    expiry_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_chat_created
                    ON trades(chat_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS strategy_events (
                    chat_id INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    candle_time TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    PRIMARY KEY (chat_id, asset, candle_time)
                );
                """
            )
            # Lightweight migrations for databases created by the first version.
            profile_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
            }
            if "strategy_on" not in profile_cols:
                conn.execute(
                    "ALTER TABLE profiles ADD COLUMN strategy_on INTEGER NOT NULL DEFAULT 0"
                )
            if "strategy_mode" not in profile_cols:
                conn.execute(
                    "ALTER TABLE profiles ADD COLUMN strategy_mode TEXT NOT NULL DEFAULT 'NORMALE'"
                )
            trade_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()
            }
            for column, definition in (
                ("entry_price", "REAL"),
                ("exit_price", "REAL"),
                ("expiry_at", "TEXT"),
                ("strategy_variant", "TEXT"),
            ):
                if column not in trade_cols:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {definition}")

    def get_profile(self, chat_id: int) -> Profile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles
                (chat_id, demo_balance, trade_amount, expiry_seconds, min_confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    self.start_balance,
                    self.default_amount,
                    self.default_expiry,
                    self.default_min_confidence,
                ),
            )
            row = conn.execute(
                "SELECT * FROM profiles WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        assert row is not None
        return Profile(
            chat_id=row["chat_id"],
            demo_balance=row["demo_balance"],
            trade_amount=row["trade_amount"],
            expiry_seconds=row["expiry_seconds"],
            min_confidence=row["min_confidence"],
            auto_demo=bool(row["auto_demo"]),
            strategy_on=bool(row["strategy_on"]),
            strategy_mode=StrategyMode(row["strategy_mode"]),
            stopped=bool(row["stopped"]),
        )

    def set_value(
        self, chat_id: int, field: str, value: float | int | bool | str
    ) -> Profile:
        allowed = {
            "trade_amount",
            "expiry_seconds",
            "min_confidence",
            "auto_demo",
            "strategy_on",
            "strategy_mode",
            "stopped",
        }
        if field not in allowed:
            raise ValueError("Campo profilo non valido")
        self.get_profile(chat_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE profiles SET {field} = ? WHERE chat_id = ?",  # field is allowlisted
                (int(value) if isinstance(value, bool) else value, chat_id),
            )
        return self.get_profile(chat_id)

    def daily_stats(self, chat_id: int) -> tuple[int, float]:
        today = datetime.now(UTC).date().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(pnl), 0) AS pnl
                FROM trades
                WHERE chat_id = ? AND substr(created_at, 1, 10) = ?
                """,
                (chat_id, today),
            ).fetchone()
        assert row is not None
        return int(row["n"]), float(row["pnl"])

    def create_demo_trade(
        self,
        chat_id: int,
        signal: Signal,
        entry_price: float | None = None,
        expiry_at: str | None = None,
        strategy_variant: str | None = None,
    ) -> Trade:
        profile = self.get_profile(chat_id)
        if profile.demo_balance < profile.trade_amount:
            raise ValueError("Saldo DEMO insufficiente")

        trade_id = uuid.uuid4().hex[:10].upper()
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE profiles SET demo_balance = demo_balance - ? WHERE chat_id = ?",
                (profile.trade_amount, chat_id),
            )
            conn.execute(
                """
                INSERT INTO trades
                (trade_id, chat_id, asset, direction, amount, expiry_seconds,
                 confidence, status, pnl, created_at, strategy_variant,
                 entry_price, expiry_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
                """,
                (
                    trade_id,
                    chat_id,
                    signal.asset,
                    signal.direction.value,
                    profile.trade_amount,
                    signal.expiry_seconds,
                    signal.confidence,
                    created_at,
                    strategy_variant,
                    entry_price,
                    expiry_at,
                ),
            )
        return self.get_trade(chat_id, trade_id)

    def get_trade(self, chat_id: int, trade_id: str) -> Trade:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE chat_id = ? AND trade_id = ?",
                (chat_id, trade_id.upper()),
            ).fetchone()
        if row is None:
            raise ValueError("Trade non trovato")
        return self._row_to_trade(row)

    def settle_demo_trade(
        self,
        chat_id: int,
        trade_id: str,
        result: str,
        payout: float,
        exit_price: float | None = None,
    ) -> Trade:
        result = result.upper()
        if result not in {"WIN", "LOSS", "TIE"}:
            raise ValueError("Risultato valido: WIN, LOSS o TIE")
        if payout < 0 or payout > 1.5:
            raise ValueError("Payout non valido")

        trade = self.get_trade(chat_id, trade_id)
        if trade.status != "PENDING":
            raise ValueError("Questo trade è già stato chiuso")

        if result == "WIN":
            pnl = trade.amount * payout
            credit = trade.amount + pnl
        elif result == "LOSS":
            pnl = -trade.amount
            credit = 0.0
        else:
            pnl = 0.0
            credit = trade.amount

        with self._connect() as conn:
            conn.execute(
                """UPDATE trades SET status = ?, pnl = ?, exit_price = ?
                   WHERE chat_id = ? AND trade_id = ?""",
                (result, pnl, exit_price, chat_id, trade.trade_id),
            )
            conn.execute(
                "UPDATE profiles SET demo_balance = demo_balance + ? WHERE chat_id = ?",
                (credit, chat_id),
            )
        return self.get_trade(chat_id, trade.trade_id)

    def strategy_chat_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chat_id FROM profiles WHERE strategy_on = 1 AND stopped = 0"
            ).fetchall()
        return [int(row["chat_id"]) for row in rows]

    def claim_strategy_event(
        self, chat_id: int, asset: str, candle_time: str, direction: Direction
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO strategy_events
                (chat_id, asset, candle_time, direction) VALUES (?, ?, ?, ?)
                """,
                (chat_id, asset, candle_time, direction.value),
            )
        return cursor.rowcount == 1

    def due_demo_trades(self, now_iso: str) -> list[Trade]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trades
                WHERE status = 'PENDING' AND entry_price IS NOT NULL
                  AND expiry_at IS NOT NULL AND expiry_at <= ?
                ORDER BY expiry_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def recent_trades(self, chat_id: int, limit: int = 8) -> list[Trade]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trades WHERE chat_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def strategy_comparison(self, chat_id: int) -> dict[str, dict[str, float | int]]:
        """Return all-time closed DEMO results split by RSI strategy variant."""
        result: dict[str, dict[str, float | int]] = {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT strategy_variant,
                       COUNT(*) AS closed,
                       SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN status = 'TIE' THEN 1 ELSE 0 END) AS ties,
                       COALESCE(SUM(pnl), 0) AS pnl
                FROM trades
                WHERE chat_id = ?
                  AND strategy_variant IN ('NORMALE', 'INVERSA')
                  AND status IN ('WIN', 'LOSS', 'TIE')
                GROUP BY strategy_variant
                """,
                (chat_id,),
            ).fetchall()
        for variant in (StrategyMode.NORMAL.value, StrategyMode.INVERSE.value):
            row = next(
                (item for item in rows if item["strategy_variant"] == variant), None
            )
            closed = int(row["closed"]) if row else 0
            wins = int(row["wins"]) if row else 0
            losses = int(row["losses"]) if row else 0
            ties = int(row["ties"]) if row else 0
            decided = wins + losses
            result[variant] = {
                "closed": closed,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": (wins / decided * 100.0) if decided else 0.0,
                "pnl": float(row["pnl"]) if row else 0.0,
            }
        return result

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> Trade:
        return Trade(
            trade_id=row["trade_id"],
            chat_id=row["chat_id"],
            asset=row["asset"],
            direction=Direction(row["direction"]),
            amount=row["amount"],
            expiry_seconds=row["expiry_seconds"],
            confidence=row["confidence"],
            status=row["status"],
            pnl=row["pnl"],
            created_at=row["created_at"],
            strategy_variant=row["strategy_variant"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            expiry_at=row["expiry_at"],
        )
