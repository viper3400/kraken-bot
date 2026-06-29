from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math

from kraken_bot.app.config import BotConfig
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
    cooldown_status: "CooldownStatus"


@dataclass(frozen=True)
class CooldownStatus:
    configured_minutes: int
    active: bool
    minutes_remaining: int
    last_sell_time: datetime | None


class StatusService:
    def __init__(
        self,
        repositories: SqliteRepositories,
        reporting_service: ReportingService,
        exchange: ExchangeAdapter,
        config: BotConfig | None = None,
    ) -> None:
        self.repositories = repositories
        self.reporting_service = reporting_service
        self.exchange = exchange
        self.config = config

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
            cooldown_status=self._build_cooldown_status(asset),
        )

    def fetch_exchange_open_orders(self, asset: str) -> tuple[list[ExchangeOpenOrder], str | None]:
        try:
            return self.exchange.list_open_orders(asset), None
        except KrakenApiError as exc:
            return [], str(exc)

    def _build_cooldown_status(self, asset: str) -> CooldownStatus:
        configured_minutes = int(getattr(getattr(self.config, "trade", None), "cooldown_after_sell_minutes", 0) or 0)
        latest_closed_trade = self.repositories.get_latest_closed_trade(asset)
        last_sell_time = latest_closed_trade.sell_time if latest_closed_trade else None
        if configured_minutes <= 0 or last_sell_time is None:
            return CooldownStatus(
                configured_minutes=configured_minutes,
                active=False,
                minutes_remaining=0,
                last_sell_time=last_sell_time,
            )

        now = datetime.now(timezone.utc)
        remaining_seconds = (last_sell_time + timedelta(minutes=configured_minutes) - now).total_seconds()
        minutes_remaining = max(0, math.ceil(remaining_seconds / 60))
        return CooldownStatus(
            configured_minutes=configured_minutes,
            active=minutes_remaining > 0,
            minutes_remaining=minutes_remaining,
            last_sell_time=last_sell_time,
        )

    @staticmethod
    def format_decimal(value: Decimal | None, places: int | None = None) -> str:
        if value is None:
            return "-"
        if places is None:
            return format(value, "f")
        return format(value, f".{places}f")
