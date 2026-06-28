from __future__ import annotations

from abc import ABC, abstractmethod

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, StrategyDecision


class Strategy(ABC):
    @abstractmethod
    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision: ...
