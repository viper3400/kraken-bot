from __future__ import annotations

import sqlite3
from pathlib import Path


class SqlitePersistence:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)
            self._ensure_columns(connection, "trades", {"strategy_name": "TEXT", "regime": "TEXT"})
            self._ensure_columns(
                connection,
                "market_snapshots",
                {
                    "regime": "TEXT",
                    "band_lower": "TEXT",
                    "band_upper": "TEXT",
                    "band_width_pct": "TEXT",
                    "ema20_slope_pct": "TEXT",
                    "ema50_slope_pct": "TEXT",
                    "regime_reason": "TEXT",
                },
            )
            self._ensure_columns(
                connection,
                "strategy_decisions",
                {
                    "regime": "TEXT",
                    "strategy_name": "TEXT",
                    "target_price": "TEXT",
                    "band_lower": "TEXT",
                    "band_upper": "TEXT",
                    "band_width_pct": "TEXT",
                    "rule_states_json": "TEXT",
                },
            )

    def _ensure_columns(self, connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
