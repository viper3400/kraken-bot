from __future__ import annotations

from abc import ABC, abstractmethod

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, StrategyDecision
from kraken_bot.strategies.base import Strategy


class StrategyService(ABC):
    @abstractmethod
    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision: ...


class DefaultStrategyService(StrategyService):
    def __init__(self, strategy: Strategy) -> None:
        self.strategy = strategy

    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision:
        return self.strategy.decide(market, entry_history, portfolio, config)
