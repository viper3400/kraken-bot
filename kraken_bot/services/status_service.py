from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from kraken_bot.domain.models import ExchangeOpenOrder, LogEntry, MarketSnapshot, Order, StrategyDecision, Trade
from kraken_bot.exchange.base import ExchangeAdapter
from kraken_bot.exchange.kraken_adapter import KrakenApiError
from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.reporting.pnl import ReportMetrics
from kraken_bot.services.reporting_service import ReportingService


@dataclass(frozen=True)
class BotStatus:
    asset: str
    generated_at: datetime
    latest_market_snapshot: MarketSnapshot | None
    latest_strategy_decision: StrategyDecision | None
    open_trade: Trade | None
    has_open_order: bool
    recent_trades: list[Trade]
    recent_orders: list[Order]
    exchange_open_orders: list[ExchangeOpenOrder]
    exchange_open_orders_error: str | None
    recent_logs: list[LogEntry]
    report_metrics: ReportMetrics
    trade_counts: dict[str, int]


class StatusService:
    def __init__(
        self,
        repositories: SqliteRepositories,
        reporting_service: ReportingService,
        exchange: ExchangeAdapter,
    ) -> None:
        self.repositories = repositories
        self.reporting_service = reporting_service
        self.exchange = exchange

    def get_status(
        self,
        asset: str,
        exchange_open_orders: list[ExchangeOpenOrder] | None = None,
        exchange_open_orders_error: str | None = None,
    ) -> BotStatus:
        if exchange_open_orders is None and exchange_open_orders_error is None:
            exchange_open_orders, exchange_open_orders_error = self.fetch_exchange_open_orders(asset)
        return BotStatus(
            asset=asset,
            generated_at=datetime.now(timezone.utc),
            latest_market_snapshot=self.repositories.get_latest_market_snapshot(asset),
            latest_strategy_decision=self.repositories.get_latest_strategy_decision(asset),
            open_trade=self.repositories.get_open_trade(asset),
            has_open_order=self.repositories.has_open_order(asset),
            recent_trades=self.repositories.list_recent_trades(limit=10),
            recent_orders=self.repositories.list_recent_orders(limit=10),
            exchange_open_orders=exchange_open_orders or [],
            exchange_open_orders_error=exchange_open_orders_error,
            recent_logs=self.repositories.list_recent_logs(limit=20),
            report_metrics=self.reporting_service.build_report(),
            trade_counts=self.repositories.count_trades_by_status(),
        )

    def fetch_exchange_open_orders(self, asset: str) -> tuple[list[ExchangeOpenOrder], str | None]:
        try:
            return self.exchange.list_open_orders(asset), None
        except KrakenApiError as exc:
            return [], str(exc)

    @staticmethod
    def format_decimal(value: Decimal | None, places: int | None = None) -> str:
        if value is None:
            return "-"
        if places is None:
            return format(value, "f")
        return format(value, f".{places}f")
