from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.models import MarketSnapshot, StrategyDecision, Trade
from kraken_bot.persistence.repositories import SqliteRepositories


class PersistenceService(ABC):
    @abstractmethod
    def save_market_snapshot(self, snapshot: MarketSnapshot) -> None: ...

    @abstractmethod
    def save_strategy_decision(self, decision: StrategyDecision) -> None: ...

    @abstractmethod
    def record_config_snapshot(self, config: BotConfig, time: datetime) -> None: ...

    @abstractmethod
    def create_trade(self, trade: Trade) -> None: ...


class DefaultPersistenceService(PersistenceService):
    def __init__(self, repositories: SqliteRepositories) -> None:
        self.repositories = repositories

    def save_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.repositories.insert_market_snapshot(snapshot)

    def save_strategy_decision(self, decision: StrategyDecision) -> None:
        self.repositories.insert_strategy_decision(decision)

    def record_config_snapshot(self, config: BotConfig, time: datetime) -> None:
        self.repositories.insert_config_snapshot(time=time, config_json=config.to_json(), config_hash=config.config_hash())

    def create_trade(self, trade: Trade) -> None:
        self.repositories.insert_trade(trade)
