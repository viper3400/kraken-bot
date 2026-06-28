from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from kraken_bot.domain.enums import Decision, MarketRegime, OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import LogEntry, MarketSnapshot, Order, Trade, StrategyDecision
from kraken_bot.persistence.sqlite import SqlitePersistence


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


class SqliteRepositories:
    def __init__(self, sqlite: SqlitePersistence) -> None:
        self.sqlite = sqlite

    def insert_trade(self, trade: Trade) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO trades (
                    id, asset, quantity, buy_order_id, sell_order_id, buy_time, sell_time,
                    buy_price, sell_price, buy_fee, sell_fee, gross_profit, total_fees,
                    net_profit, holding_duration_seconds, status, strategy_name, regime, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.id,
                    trade.asset,
                    str(trade.quantity),
                    trade.buy_order_id,
                    trade.sell_order_id,
                    _iso(trade.buy_time),
                    _iso(trade.sell_time),
                    str(trade.buy_price) if trade.buy_price is not None else None,
                    str(trade.sell_price) if trade.sell_price is not None else None,
                    str(trade.buy_fee),
                    str(trade.sell_fee),
                    str(trade.gross_profit) if trade.gross_profit is not None else None,
                    str(trade.total_fees) if trade.total_fees is not None else None,
                    str(trade.net_profit) if trade.net_profit is not None else None,
                    trade.holding_duration_seconds,
                    trade.status.value,
                    trade.strategy_name,
                    trade.regime.value if trade.regime is not None else None,
                    _iso(trade.created_at),
                ),
            )

    def insert_order(self, order: Order) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    id, trade_id, time, type, price, quantity, status, post_only, exchange_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    order.trade_id,
                    _iso(order.time),
                    order.type.value,
                    str(order.price),
                    str(order.quantity),
                    order.status.value,
                    1 if order.post_only else 0,
                    order.exchange_id,
                    _iso(order.created_at),
                ),
            )

    def insert_order_event(
        self,
        order_id: str,
        time: datetime,
        status: OrderStatus,
        raw_payload: str | None,
    ) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_events (id, order_id, time, status, raw_payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid4()), order_id, _iso(time), status.value, raw_payload),
            )

    def insert_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO market_snapshots (
                    id, time, asset, price, ema20, ema50, volatility, volume, trend_status, regime,
                    band_lower, band_upper, band_width_pct, ema20_slope_pct, ema50_slope_pct, regime_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    _iso(snapshot.time),
                    snapshot.asset,
                    str(snapshot.price),
                    str(snapshot.ema20) if snapshot.ema20 is not None else None,
                    str(snapshot.ema50) if snapshot.ema50 is not None else None,
                    str(snapshot.volatility) if snapshot.volatility is not None else None,
                    str(snapshot.volume) if snapshot.volume is not None else None,
                    snapshot.trend_status,
                    snapshot.regime.value,
                    str(snapshot.band_lower) if snapshot.band_lower is not None else None,
                    str(snapshot.band_upper) if snapshot.band_upper is not None else None,
                    str(snapshot.band_width_pct) if snapshot.band_width_pct is not None else None,
                    str(snapshot.ema20_slope_pct) if snapshot.ema20_slope_pct is not None else None,
                    str(snapshot.ema50_slope_pct) if snapshot.ema50_slope_pct is not None else None,
                    snapshot.regime_reason,
                    _iso(snapshot.time),
                ),
            )

    def insert_strategy_decision(self, decision: StrategyDecision) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_decisions (
                    id, time, asset, decision, reason, ema20, ema50, price, pullback, comment, config_snapshot,
                    regime, strategy_name, target_price, band_lower, band_upper, band_width_pct, rule_states_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.id,
                    _iso(decision.time),
                    decision.asset,
                    decision.decision.value,
                    decision.reason,
                    str(decision.ema20) if decision.ema20 is not None else None,
                    str(decision.ema50) if decision.ema50 is not None else None,
                    str(decision.price) if decision.price is not None else None,
                    str(decision.pullback) if decision.pullback is not None else None,
                    decision.comment,
                    decision.config_snapshot,
                    decision.regime.value,
                    decision.strategy_name,
                    str(decision.target_price) if decision.target_price is not None else None,
                    str(decision.band_lower) if decision.band_lower is not None else None,
                    str(decision.band_upper) if decision.band_upper is not None else None,
                    str(decision.band_width_pct) if decision.band_width_pct is not None else None,
                    decision.rule_states_json,
                    _iso(decision.time),
                ),
            )

    def insert_config_snapshot(self, time: datetime, config_json: str, config_hash: str) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO bot_config_history (id, time, config_json, config_hash)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid4()), _iso(time), config_json, config_hash),
            )

    def insert_log(
        self,
        level: str,
        service: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                INSERT INTO logs (id, time, level, service, message, context_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    _iso(datetime.now(timezone.utc)),
                    level,
                    service,
                    message,
                    json.dumps(context, sort_keys=True) if context else None,
                ),
            )

    def get_open_trade(self, asset: str) -> Trade | None:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trades WHERE asset = ? AND status = ? ORDER BY created_at DESC LIMIT 1",
                (asset, TradeStatus.OPEN.value),
            ).fetchone()
        return self._row_to_trade(row) if row else None

    def has_open_order(self, asset: str) -> bool:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM orders o
                JOIN trades t ON t.id = o.trade_id
                WHERE t.asset = ?
                  AND o.status IN (?, ?, ?)
                LIMIT 1
                """,
                (asset, OrderStatus.CREATED.value, OrderStatus.SUBMITTED.value, OrderStatus.OPEN.value),
            ).fetchone()
        return row is not None

    def get_order_by_exchange_id(self, exchange_order_id: str) -> Order | None:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE exchange_id = ? LIMIT 1",
                (exchange_order_id,),
            ).fetchone()
        return self._row_to_order(row) if row else None

    def list_orders_for_asset_by_statuses(self, asset: str, statuses: tuple[OrderStatus, ...]) -> list[Order]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        params = [asset, *(status.value for status in statuses)]
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.*
                FROM orders o
                JOIN trades t ON t.id = o.trade_id
                WHERE t.asset = ?
                  AND o.status IN ({placeholders})
                ORDER BY o.created_at ASC
                """,
                params,
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def list_open_trade_entry_orders_with_terminal_statuses(self, asset: str) -> list[Order]:
        terminal_statuses = (OrderStatus.CANCELLED.value, OrderStatus.EXPIRED.value, OrderStatus.REJECTED.value)
        placeholders = ", ".join("?" for _ in terminal_statuses)
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.*
                FROM orders o
                JOIN trades t ON t.id = o.trade_id
                WHERE t.asset = ?
                  AND t.status = ?
                  AND o.type = ?
                  AND o.status IN ({placeholders})
                ORDER BY o.created_at ASC
                """,
                (asset, TradeStatus.OPEN.value, OrderType.BUY.value, *terminal_statuses),
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def list_open_trade_entry_orders_missing_fill_details(self, asset: str) -> list[Order]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.*
                FROM orders o
                JOIN trades t ON t.id = o.trade_id
                WHERE t.asset = ?
                  AND t.status = ?
                  AND o.type = ?
                  AND o.status = ?
                  AND (t.buy_price IS NULL OR t.buy_time IS NULL)
                ORDER BY o.created_at ASC
                """,
                (asset, TradeStatus.OPEN.value, OrderType.BUY.value, OrderStatus.FILLED.value),
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def list_open_trade_exit_orders_missing_close_details(self, asset: str) -> list[Order]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.*
                FROM orders o
                JOIN trades t ON t.id = o.trade_id
                WHERE t.asset = ?
                  AND t.status = ?
                  AND o.type = ?
                  AND o.status = ?
                  AND (t.sell_price IS NULL OR t.sell_time IS NULL OR t.net_profit IS NULL)
                ORDER BY o.created_at ASC
                """,
                (asset, TradeStatus.OPEN.value, OrderType.SELL.value, OrderStatus.FILLED.value),
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (status.value, order_id),
            )

    def update_trade_status(self, trade_id: str, status: TradeStatus) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                "UPDATE trades SET status = ? WHERE id = ?",
                (status.value, trade_id),
            )

    def update_trade_buy_fill(
        self,
        trade_id: str,
        buy_time: datetime | None,
        buy_price: Decimal | None,
        buy_fee: Decimal | None,
    ) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                UPDATE trades
                SET buy_time = COALESCE(?, buy_time),
                    buy_price = COALESCE(?, buy_price),
                    buy_fee = COALESCE(?, buy_fee)
                WHERE id = ?
                """,
                (
                    _iso(buy_time),
                    str(buy_price) if buy_price is not None else None,
                    str(buy_fee) if buy_fee is not None else None,
                    trade_id,
                ),
            )

    def update_trade_sell_fill(
        self,
        trade_id: str,
        sell_order_id: str | None,
        sell_time: datetime | None,
        sell_price: Decimal | None,
        sell_fee: Decimal | None,
        gross_profit: Decimal | None,
        total_fees: Decimal | None,
        net_profit: Decimal | None,
        holding_duration_seconds: int | None,
    ) -> None:
        with self.sqlite.connect() as connection:
            connection.execute(
                """
                UPDATE trades
                SET sell_order_id = COALESCE(?, sell_order_id),
                    sell_time = COALESCE(?, sell_time),
                    sell_price = COALESCE(?, sell_price),
                    sell_fee = COALESCE(?, sell_fee),
                    gross_profit = COALESCE(?, gross_profit),
                    total_fees = COALESCE(?, total_fees),
                    net_profit = COALESCE(?, net_profit),
                    holding_duration_seconds = COALESCE(?, holding_duration_seconds),
                    status = ?
                WHERE id = ?
                """,
                (
                    sell_order_id,
                    _iso(sell_time),
                    str(sell_price) if sell_price is not None else None,
                    str(sell_fee) if sell_fee is not None else None,
                    str(gross_profit) if gross_profit is not None else None,
                    str(total_fees) if total_fees is not None else None,
                    str(net_profit) if net_profit is not None else None,
                    holding_duration_seconds,
                    TradeStatus.CLOSED.value,
                    trade_id,
                ),
            )

    def get_trade(self, trade_id: str) -> Trade | None:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trades WHERE id = ? LIMIT 1",
                (trade_id,),
            ).fetchone()
        return self._row_to_trade(row) if row else None

    def get_trade_asset(self, trade_id: str | None) -> str:
        if trade_id is None:
            raise ValueError("trade_id is required")
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT asset FROM trades WHERE id = ? LIMIT 1",
                (trade_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown trade {trade_id}")
        return str(row["asset"])

    def list_trades(self) -> list[Trade]:
        with self.sqlite.connect() as connection:
            rows = connection.execute("SELECT * FROM trades ORDER BY created_at ASC").fetchall()
        return [self._row_to_trade(row) for row in rows]

    def list_recent_trades(self, limit: int = 10) -> list[Trade]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def list_recent_orders(self, limit: int = 10) -> list[Order]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def list_recent_logs(self, limit: int = 20) -> list[LogEntry]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM logs ORDER BY time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_log(row) for row in rows]

    def get_latest_market_snapshot(self, asset: str) -> MarketSnapshot | None:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT * FROM market_snapshots WHERE asset = ? ORDER BY time DESC LIMIT 1",
                (asset,),
            ).fetchone()
        return self._row_to_market_snapshot(row) if row else None

    def get_latest_strategy_decision(self, asset: str) -> StrategyDecision | None:
        with self.sqlite.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_decisions WHERE asset = ? ORDER BY time DESC LIMIT 1",
                (asset,),
            ).fetchone()
        return self._row_to_strategy_decision(row) if row else None

    def count_trades_by_status(self) -> dict[str, int]:
        with self.sqlite.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM trades GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _row_to_trade(self, row) -> Trade:
        return Trade(
            id=row["id"],
            asset=row["asset"],
            quantity=Decimal(row["quantity"]),
            buy_order_id=row["buy_order_id"],
            sell_order_id=row["sell_order_id"],
            buy_time=datetime.fromisoformat(row["buy_time"]) if row["buy_time"] else None,
            sell_time=datetime.fromisoformat(row["sell_time"]) if row["sell_time"] else None,
            buy_price=_decimal(row["buy_price"]),
            sell_price=_decimal(row["sell_price"]),
            buy_fee=Decimal(row["buy_fee"]),
            sell_fee=Decimal(row["sell_fee"]),
            gross_profit=_decimal(row["gross_profit"]),
            total_fees=_decimal(row["total_fees"]),
            net_profit=_decimal(row["net_profit"]),
            holding_duration_seconds=row["holding_duration_seconds"],
            status=TradeStatus(row["status"]),
            strategy_name=row["strategy_name"] if "strategy_name" in row.keys() else None,
            regime=MarketRegime(row["regime"]) if "regime" in row.keys() and row["regime"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_order(self, row) -> Order:
        return Order(
            id=row["id"],
            trade_id=row["trade_id"],
            time=datetime.fromisoformat(row["time"]),
            type=OrderType(row["type"]),
            price=Decimal(row["price"]),
            quantity=Decimal(row["quantity"]),
            status=OrderStatus(row["status"]),
            post_only=bool(row["post_only"]),
            exchange_id=row["exchange_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_market_snapshot(self, row) -> MarketSnapshot:
        return MarketSnapshot(
            id=row["id"],
            time=datetime.fromisoformat(row["time"]),
            asset=row["asset"],
            price=Decimal(row["price"]),
            ema20=_decimal(row["ema20"]),
            ema50=_decimal(row["ema50"]),
            volatility=_decimal(row["volatility"]),
            volume=_decimal(row["volume"]),
            trend_status=row["trend_status"],
            regime=MarketRegime(row["regime"]) if "regime" in row.keys() and row["regime"] else MarketRegime.NO_TRADE,
            band_lower=_decimal(row["band_lower"]) if "band_lower" in row.keys() else None,
            band_upper=_decimal(row["band_upper"]) if "band_upper" in row.keys() else None,
            band_width_pct=_decimal(row["band_width_pct"]) if "band_width_pct" in row.keys() else None,
            ema20_slope_pct=_decimal(row["ema20_slope_pct"]) if "ema20_slope_pct" in row.keys() else None,
            ema50_slope_pct=_decimal(row["ema50_slope_pct"]) if "ema50_slope_pct" in row.keys() else None,
            regime_reason=row["regime_reason"] if "regime_reason" in row.keys() else None,
        )

    def _row_to_strategy_decision(self, row) -> StrategyDecision:
        return StrategyDecision(
            id=row["id"],
            time=datetime.fromisoformat(row["time"]),
            asset=row["asset"],
            decision=Decision(row["decision"]),
            reason=row["reason"],
            ema20=_decimal(row["ema20"]),
            ema50=_decimal(row["ema50"]),
            price=_decimal(row["price"]),
            pullback=_decimal(row["pullback"]),
            comment=row["comment"],
            config_snapshot=row["config_snapshot"],
            regime=MarketRegime(row["regime"]) if "regime" in row.keys() and row["regime"] else MarketRegime.NO_TRADE,
            strategy_name=row["strategy_name"] if "strategy_name" in row.keys() else None,
            target_price=_decimal(row["target_price"]) if "target_price" in row.keys() else None,
            band_lower=_decimal(row["band_lower"]) if "band_lower" in row.keys() else None,
            band_upper=_decimal(row["band_upper"]) if "band_upper" in row.keys() else None,
            band_width_pct=_decimal(row["band_width_pct"]) if "band_width_pct" in row.keys() else None,
            rule_states_json=row["rule_states_json"] if "rule_states_json" in row.keys() else None,
        )

    def _row_to_log(self, row) -> LogEntry:
        return LogEntry(
            id=row["id"],
            time=datetime.fromisoformat(row["time"]),
            level=str(row["level"]),
            service=str(row["service"]),
            message=str(row["message"]),
            context_json=row["context_json"],
        )
