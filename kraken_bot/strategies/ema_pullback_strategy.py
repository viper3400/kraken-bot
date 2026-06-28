from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal
from uuid import uuid4

from kraken_bot.app.config import BotConfig, TrendStrategySection
from kraken_bot.domain.enums import Decision, MarketRegime
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, StrategyDecision
from kraken_bot.strategies.base import Strategy


class EmaPullbackStrategy(Strategy):
    name = "ema_pullback"

    def decide(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: BotConfig,
    ) -> StrategyDecision:
        strategy_config = config.trend_strategy
        timeframe_summary = (
            f"regime={config.market_regime.timeframe}, "
            f"trend={strategy_config.trend_timeframe}, "
            f"entry={strategy_config.entry_timeframe}"
        )
        pullback = self._setup_pullback_pct(market, entry_history)
        decision = Decision.HOLD
        reason = "No rule matched"
        rules: list[dict[str, str]] = []
        fee_floor_pct = Decimal(str(config.trade.round_trip_fee_pct))

        if portfolio.has_open_position and portfolio.open_trade and portfolio.open_trade.buy_price:
            decision, reason, rules = self._decide_sell(market, portfolio, strategy_config, fee_floor_pct)
        elif portfolio.has_open_order:
            reason = f"Open order already exists ({timeframe_summary})"
            rules = [
                {"label": "Open order exists", "state": "FAIL", "detail": "A new buy is blocked while another order is open"}
            ]
        else:
            should_buy, rules = self._should_buy(market, entry_history, portfolio, strategy_config, pullback)
            if should_buy:
                decision = Decision.BUY
                reason = f"EMA trend bullish, pullback recovered, no open position ({timeframe_summary})"
            else:
                reason = f"No buy rule matched ({timeframe_summary})"

        target_price = market.price
        if decision is Decision.BUY:
            target_price = market.price
        elif decision is Decision.SELL:
            target_price = market.price

        return StrategyDecision(
            id=str(uuid4()),
            time=market.time.astimezone(timezone.utc),
            asset=market.asset,
            decision=decision,
            reason=reason,
            ema20=market.ema20,
            ema50=market.ema50,
            price=market.price,
            pullback=pullback,
            config_snapshot=config.to_json(),
            regime=MarketRegime.TREND,
            strategy_name=self.name,
            target_price=target_price,
            band_lower=market.band_lower,
            band_upper=market.band_upper,
            band_width_pct=market.band_width_pct,
            rule_states_json=json.dumps(
                {
                    "context": "trend",
                    "timeframes": {
                        "regime": config.market_regime.timeframe,
                        "trend": strategy_config.trend_timeframe,
                        "entry": strategy_config.entry_timeframe,
                    },
                    "rules": rules,
                }
            ),
        )

    def _should_buy(
        self,
        market: MarketSnapshot,
        entry_history: list[Candle],
        portfolio: PortfolioState,
        config: TrendStrategySection,
        pullback: Decimal,
    ) -> tuple[bool, list[dict[str, str]]]:
        rules: list[dict[str, str]] = []
        if portfolio.has_open_position:
            return False, [{"label": "No open position", "state": "FAIL", "detail": "The asset already has an open trade"}]
        if market.ema20 is None or market.ema50 is None:
            return False, [{"label": "EMA values available", "state": "FAIL", "detail": "EMA values are missing"}]
        min_pullback = Decimal(str(config.pullback_min_pct))
        max_pullback = Decimal(str(config.pullback_max_pct))
        trend_ok = market.ema20 > market.ema50 and market.price > market.ema20
        pullback_ok = min_pullback <= pullback <= max_pullback
        entry_history_ok = len(entry_history) >= 2
        recovery_ok = entry_history_ok and self._is_recovery_candle(
            entry_history[-2],
            entry_history[-1],
            require_close_above_previous_high=config.require_close_above_previous_high,
        )
        rules.extend(
            [
                {"label": "No open position", "state": "PASS", "detail": "Single-position rule is satisfied"},
                {
                    "label": "EMA trend bullish",
                    "state": "PASS" if trend_ok else "FAIL",
                    "detail": f"timeframe {config.trend_timeframe}: price {market.price} / ema20 {market.ema20} / ema50 {market.ema50}",
                },
                {
                    "label": "Pullback in range",
                    "state": "PASS" if pullback_ok else "FAIL",
                    "detail": f"timeframe {config.entry_timeframe}: prior candle low pullback {pullback}% in [{min_pullback}, {max_pullback}]",
                },
                {
                    "label": "Entry history available",
                    "state": "PASS" if entry_history_ok else "FAIL",
                    "detail": f"timeframe {config.entry_timeframe}: need at least 2 completed candles",
                },
                {
                    "label": "Recovery candle",
                    "state": "PASS" if recovery_ok else "FAIL",
                    "detail": (
                        f"timeframe {config.entry_timeframe}: current candle is green and closes above the prior high"
                        if config.require_close_above_previous_high
                        else f"timeframe {config.entry_timeframe}: current candle is green and closes above the prior close"
                    ),
                },
            ]
        )
        return trend_ok and pullback_ok and entry_history_ok and recovery_ok, rules

    def _decide_sell(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        config: TrendStrategySection,
        fee_floor_pct: Decimal,
    ) -> tuple[Decision, str, list[dict[str, str]]]:
        trade = portfolio.open_trade
        assert trade is not None
        assert trade.buy_price is not None
        assert trade.buy_time is not None

        current_profit_pct = ((market.price - trade.buy_price) / trade.buy_price) * Decimal("100")
        held_minutes = Decimal((market.time - trade.buy_time).total_seconds()) / Decimal("60")
        target_pct = max(Decimal(str(config.take_profit_pct)), fee_floor_pct)
        reduced_target_active = held_minutes >= Decimal(str(config.reduce_target_after_minutes))
        if reduced_target_active:
            target_pct = max(Decimal(str(config.reduced_take_profit_pct)), fee_floor_pct)

        rules = [
            {"label": "Open position exists", "state": "PASS", "detail": f"Trade {trade.id} is open"},
            {"label": "Fees covered", "state": "PASS" if current_profit_pct >= fee_floor_pct else "FAIL", "detail": f"{current_profit_pct}% vs round-trip fees {fee_floor_pct}%"},
            {"label": "Take profit reached", "state": "PASS" if current_profit_pct >= target_pct else "FAIL", "detail": f"{current_profit_pct}% vs target {target_pct}%"},
            {"label": "Stop loss reached", "state": "PASS" if current_profit_pct <= -Decimal(str(config.stop_loss_pct)) else "FAIL", "detail": f"{current_profit_pct}% vs threshold -{config.stop_loss_pct}%"},
            {"label": "Max holding reached", "state": "PASS" if held_minutes >= Decimal(str(config.max_holding_minutes)) else "FAIL", "detail": f"{held_minutes} min vs limit {config.max_holding_minutes}"},
            {"label": "Reduced target active", "state": "PASS" if reduced_target_active else "INFO", "detail": f"Switch after {config.reduce_target_after_minutes} min"},
        ]

        if current_profit_pct >= target_pct:
            return Decision.SELL, "Take profit reached", rules
        if current_profit_pct <= -Decimal(str(config.stop_loss_pct)):
            return Decision.SELL, "Stop loss reached", rules
        if held_minutes >= Decimal(str(config.max_holding_minutes)):
            return Decision.SELL, "Maximum holding duration reached", rules
        return Decision.HOLD, "Open trade still within sell thresholds", rules

    def _setup_pullback_pct(self, market: MarketSnapshot, entry_history: list[Candle]) -> Decimal:
        if len(entry_history) >= 2:
            return self._pullback_pct_from_price(market.ema20, entry_history[-2].low)
        return self._pullback_pct_from_price(market.ema20, market.price)

    def _pullback_pct_from_price(self, ema_fast: Decimal | None, price: Decimal) -> Decimal:
        if ema_fast is None or ema_fast == 0:
            return Decimal("0")
        return ((price - ema_fast) / ema_fast * Decimal("100")).copy_abs()

    def _is_recovery_candle(
        self,
        previous: Candle,
        current: Candle,
        require_close_above_previous_high: bool,
    ) -> bool:
        previous_red = previous.close <= previous.open
        current_green = current.close > current.open
        if require_close_above_previous_high:
            confirmation_ok = current.close > previous.high
        else:
            confirmation_ok = current.close > previous.close
        return current_green and confirmation_ok and previous_red
