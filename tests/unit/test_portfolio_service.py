from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from kraken_bot.domain.enums import OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import Order, Trade
from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.persistence.sqlite import SqlitePersistence
from kraken_bot.services.portfolio_service import DefaultPortfolioService


def build_repositories(tmp_path: Path) -> SqliteRepositories:
    return SqliteRepositories(SqlitePersistence(tmp_path / "bot.sqlite"))


def test_cannot_open_second_position_for_same_asset(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    repositories.insert_trade(
        Trade(
            id="trade-1",
            asset="XBT/EUR",
            quantity=Decimal("0.5"),
            status=TradeStatus.OPEN,
            created_at=datetime.now(timezone.utc),
        )
    )
    service = DefaultPortfolioService(repositories)
    assert service.can_open_trade("XBT/EUR", Decimal("50")) is False


def test_cannot_buy_when_open_order_exists(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    now = datetime.now(timezone.utc)
    repositories.insert_trade(
        Trade(
            id="trade-1",
            asset="XBT/EUR",
            quantity=Decimal("0.5"),
            status=TradeStatus.OPEN,
            created_at=now,
        )
    )
    repositories.insert_order(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=now,
            type=OrderType.BUY,
            price=Decimal("100"),
            quantity=Decimal("0.5"),
            status=OrderStatus.OPEN,
            post_only=True,
            exchange_id="ex-1",
            created_at=now,
        )
    )
    service = DefaultPortfolioService(repositories)
    assert service.has_open_order("XBT/EUR") is True


def test_can_open_trade_with_capital_and_no_open_state(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    service = DefaultPortfolioService(repositories, available_quote_balance=Decimal("100"))
    assert service.can_open_trade("XBT/EUR", Decimal("50")) is True


def test_get_state_includes_latest_closed_trade(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    now = datetime.now(timezone.utc)
    repositories.insert_trade(
        Trade(
            id="trade-closed-1",
            asset="XBT/EUR",
            quantity=Decimal("0.5"),
            buy_time=now,
            sell_time=now,
            status=TradeStatus.CLOSED,
            created_at=now,
        )
    )

    service = DefaultPortfolioService(repositories)
    state = service.get_state("XBT/EUR")

    assert state.last_closed_trade is not None
    assert state.last_closed_trade.id == "trade-closed-1"
