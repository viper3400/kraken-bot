from __future__ import annotations

import json
from uuid import uuid4

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import Decision, MarketRegime
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, StrategyDecision
from kraken_bot.strategies.base import Strategy


class RegimeStrategy(Strategy):
    def __init__(self, trend_strategy: Strategy, range_strategy: Strategy) -> None:
        self.trend_strategy = trend_strategy
        self.range_strategy = range_strategy

    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision:
        if portfolio.open_trade and portfolio.open_trade.strategy_name == getattr(self.range_strategy, "name", "range"):
            return self.range_strategy.decide(market, entry_history, portfolio, config)
        if portfolio.open_trade and portfolio.open_trade.strategy_name == getattr(self.trend_strategy, "name", "ema_pullback"):
            return self.trend_strategy.decide(market, entry_history, portfolio, config)

        if market.regime is MarketRegime.TREND:
            return self.trend_strategy.decide(market, entry_history, portfolio, config)
        if market.regime is MarketRegime.SIDEWAYS:
            return self.range_strategy.decide(market, entry_history, portfolio, config)

        return StrategyDecision(
            id=str(uuid4()),
            time=market.time,
            asset=market.asset,
            decision=Decision.HOLD,
            reason=market.regime_reason or "No trade regime selected",
            ema20=market.ema20,
            ema50=market.ema50,
            price=market.price,
            config_snapshot=config.to_json(),
            regime=MarketRegime.NO_TRADE,
            strategy_name=None,
            band_lower=market.band_lower,
            band_upper=market.band_upper,
            band_width_pct=market.band_width_pct,
            rule_states_json=json.dumps(
                {
                    "context": "regime",
                    "rules": [
                        {
                            "label": "Market regime is tradable",
                            "state": "FAIL",
                            "detail": market.regime_reason or "No matching regime",
                        }
                    ],
                }
            ),
        )
