from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from kraken_bot.domain.models import PortfolioState
from kraken_bot.persistence.repositories import SqliteRepositories


class PortfolioService(ABC):
    @abstractmethod
    def get_state(self, asset: str) -> PortfolioState: ...

    @abstractmethod
    def has_open_position(self, asset: str) -> bool: ...

    @abstractmethod
    def has_open_order(self, asset: str) -> bool: ...

    @abstractmethod
    def can_open_trade(self, asset: str, required_capital: Decimal) -> bool: ...


class DefaultPortfolioService(PortfolioService):
    def __init__(
        self,
        repositories: SqliteRepositories,
        available_quote_balance: Decimal = Decimal("1000"),
    ) -> None:
        self.repositories = repositories
        self.available_quote_balance = available_quote_balance

    def get_state(self, asset: str) -> PortfolioState:
        open_trade = self.repositories.get_open_trade(asset)
        has_open_order = self.repositories.has_open_order(asset)
        return PortfolioState(
            asset=asset,
            has_open_position=open_trade is not None,
            has_open_order=has_open_order,
            available_quote_balance=self.available_quote_balance,
            open_trade=open_trade,
        )

    def has_open_position(self, asset: str) -> bool:
        return self.get_state(asset).has_open_position

    def has_open_order(self, asset: str) -> bool:
        return self.get_state(asset).has_open_order

    def can_open_trade(self, asset: str, required_capital: Decimal) -> bool:
        state = self.get_state(asset)
        return (
            not state.has_open_position
            and not state.has_open_order
            and state.available_quote_balance >= required_capital
        )
