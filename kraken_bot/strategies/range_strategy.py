from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal
from uuid import uuid4

from kraken_bot.app.config import BotConfig, RangeStrategySection
from kraken_bot.domain.enums import Decision, MarketRegime
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, StrategyDecision
from kraken_bot.strategies.base import Strategy


class RangeStrategy(Strategy):
    name = "range"

    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision:
        strategy_config = config.range_strategy
        fee_floor_pct = Decimal(str(config.trade.round_trip_fee_pct))
        if market.band_lower is None or market.band_upper is None:
            return self._decision(market, config, Decision.HOLD, "Range boundaries unavailable", [], market.price)

        if portfolio.has_open_position and portfolio.open_trade and portfolio.open_trade.buy_price:
            decision, reason, rules, target_price = self._decide_sell(market, portfolio, strategy_config, fee_floor_pct)
            return self._decision(market, config, decision, reason, rules, target_price)

        if portfolio.has_open_order:
            rules = [{"label": "No open order", "state": "FAIL", "detail": "A new range entry is blocked while another order is open"}]
            return self._decision(market, config, Decision.HOLD, "Open order already exists", rules, market.price)

        should_buy, reason, rules, target_price = self._should_buy(
            market,
            entry_history,
            portfolio,
            strategy_config,
            config.trade.cooldown_after_sell_minutes,
        )
        return self._decision(
            market,
            config,
            Decision.BUY if should_buy else Decision.HOLD,
            "Price is near support in a sideways market" if should_buy else reason,
            rules,
            target_price,
        )

    def _decision(
        self,
        market: MarketSnapshot,
        config: BotConfig,
        decision: Decision,
        reason: str,
        rules: list[dict[str, str]],
        target_price: Decimal,
    ) -> StrategyDecision:
        return StrategyDecision(
            id=str(uuid4()),
            time=market.time.astimezone(timezone.utc),
            asset=market.asset,
            decision=decision,
            reason=reason,
            ema20=market.ema20,
            ema50=market.ema50,
            price=market.price,
            config_snapshot=config.to_json(),
            regime=MarketRegime.SIDEWAYS,
            strategy_name=self.name,
            target_price=target_price,
            band_lower=market.band_lower,
            band_upper=market.band_upper,
            band_width_pct=market.band_width_pct,
            rule_states_json=json.dumps({"context": "range", "rules": rules}),
        )

    def _should_buy(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: RangeStrategySection,
        cooldown_after_sell_minutes: int,
    ) -> tuple[bool, str, list[dict[str, str]], Decimal]:
        assert market.band_lower is not None
        assert market.band_upper is not None
        entry_price = market.band_lower * (Decimal("1") + Decimal(str(config.entry_buffer_pct)) / Decimal("100"))
        upper_bound = market.band_lower * (Decimal("1") + Decimal(str(config.entry_buffer_pct)) / Decimal("100"))
        near_support = market.price <= upper_bound
        cooldown_active, cooldown_detail = self.sell_cooldown_state(
            market.time,
            portfolio,
            cooldown_after_sell_minutes,
        )
        recovery_ok = True
        if config.require_recovery_candle and len(entry_history) >= 2:
            previous = entry_history[-2]
            current = entry_history[-1]
            recovery_ok = current.close > current.open and current.close > previous.close
        rules = [
            {"label": "No open position", "state": "PASS" if not portfolio.has_open_position else "FAIL", "detail": "Single-position rule per asset"},
            {"label": "Sell cooldown inactive", "state": "FAIL" if cooldown_active else "PASS", "detail": cooldown_detail},
            {"label": "Near lower band", "state": "PASS" if near_support else "FAIL", "detail": f"price {market.price} vs entry zone <= {upper_bound}"},
            {"label": "Sideways regime active", "state": "PASS" if market.regime is MarketRegime.SIDEWAYS else "FAIL", "detail": market.regime.value},
            {"label": "Recovery candle", "state": "PASS" if recovery_ok else "FAIL", "detail": "Support bounce confirmation"},
        ]
        reason = "Sell cooldown active" if cooldown_active else "Price is not close enough to support"
        return (
            near_support and recovery_ok and not portfolio.has_open_position and not cooldown_active,
            reason,
            rules,
            entry_price,
        )

    def _decide_sell(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        config: RangeStrategySection,
        fee_floor_pct: Decimal,
    ) -> tuple[Decision, str, list[dict[str, str]], Decimal]:
        assert market.band_upper is not None
        trade = portfolio.open_trade
        assert trade is not None
        assert trade.buy_price is not None
        assert trade.buy_time is not None
        target_price = market.band_upper * (Decimal("1") - Decimal(str(config.exit_buffer_pct)) / Decimal("100"))
        fee_floor_price = trade.buy_price * (Decimal("1") + fee_floor_pct / Decimal("100"))
        target_price = max(target_price, fee_floor_price)
        current_profit_pct = ((market.price - trade.buy_price) / trade.buy_price) * Decimal("100")
        held_minutes = Decimal((market.time - trade.buy_time).total_seconds()) / Decimal("60")
        stop_loss = Decimal(str(config.stop_loss_pct))
        max_holding = Decimal(str(config.max_holding_minutes))
        at_target = market.price >= target_price
        stop_hit = current_profit_pct <= -stop_loss
        expired = held_minutes >= max_holding
        rules = [
            {"label": "Open position exists", "state": "PASS", "detail": f"Trade {trade.id} is open"},
            {"label": "Fees covered at target", "state": "PASS" if target_price >= fee_floor_price else "FAIL", "detail": f"target {target_price} vs fee floor {fee_floor_price}"},
            {"label": "Near upper band", "state": "PASS" if at_target else "FAIL", "detail": f"price {market.price} vs target {target_price}"},
            {"label": "Stop loss reached", "state": "PASS" if stop_hit else "FAIL", "detail": f"{current_profit_pct}% vs threshold -{stop_loss}%"},
            {"label": "Max holding reached", "state": "PASS" if expired else "FAIL", "detail": f"{held_minutes} min vs limit {max_holding}"},
        ]
        if at_target:
            return Decision.SELL, "Price reached the upper range exit zone", rules, target_price
        if stop_hit:
            return Decision.SELL, "Range trade stop loss reached", rules, market.price
        if expired:
            return Decision.SELL, "Range trade maximum holding time reached", rules, market.price
        return Decision.HOLD, "Range trade remains inside the band", rules, target_price
