from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

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

    @staticmethod
    def sell_cooldown_state(
        market_time: datetime,
        portfolio: PortfolioState,
        cooldown_minutes: int,
    ) -> tuple[bool, str]:
        if cooldown_minutes <= 0:
            return False, "Cooldown disabled"

        closed_trade = portfolio.last_closed_trade
        if closed_trade is None or closed_trade.sell_time is None:
            return False, "No recent closed trade"

        elapsed_minutes = Decimal((market_time - closed_trade.sell_time).total_seconds()) / Decimal("60")
        active = elapsed_minutes < Decimal(str(cooldown_minutes))
        return active, f"{elapsed_minutes} min since sell vs cooldown {cooldown_minutes}"
