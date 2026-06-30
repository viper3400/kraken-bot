from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import Decision, MarketRegime, OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import MarketSnapshot, Order, StrategyDecision, Trade
from kraken_bot.persistence.repositories import SqliteRepositories


class DemoDataSeeder:
    def __init__(self, repositories: SqliteRepositories, config: BotConfig) -> None:
        self.repositories = repositories
        self.config = config

    def seed_if_enabled(self) -> None:
        if self.config.bot.mode != "demo" or self.repositories.has_any_dashboard_data():
            return
        self._seed()

    def _seed(self) -> None:
        asset = self.config.bot.asset
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot_time = now - timedelta(minutes=6)
        closed_buy_time = now - timedelta(hours=5, minutes=10)
        closed_sell_time = now - timedelta(hours=3, minutes=40)
        open_buy_time = now - timedelta(minutes=95)

        self.repositories.insert_market_snapshot(
            MarketSnapshot(
                id="demo-snapshot-1",
                time=snapshot_time,
                asset=asset,
                price=Decimal("64210.45"),
                ema20=Decimal("64182.10"),
                ema50=Decimal("64095.75"),
                volatility=Decimal("0.84"),
                volume=Decimal("128.4"),
                trend_status="BULLISH",
                regime=MarketRegime.TREND,
                band_lower=Decimal("63890.00"),
                band_upper=Decimal("64540.00"),
                band_width_pct=Decimal("1.02"),
                ema20_slope_pct=Decimal("0.16"),
                ema50_slope_pct=Decimal("0.08"),
                regime_reason="EMA slopes are positive and price is holding above the fast trend average.",
            )
        )
        self.repositories.insert_strategy_decision(
            StrategyDecision(
                id="demo-decision-1",
                time=snapshot_time,
                asset=asset,
                decision=Decision.BUY,
                reason="Trend resumed after a shallow pullback into EMA support.",
                ema20=Decimal("64182.10"),
                ema50=Decimal("64095.75"),
                price=Decimal("64210.45"),
                pullback=Decimal("0.74"),
                config_snapshot=self.config.to_json(),
                regime=MarketRegime.TREND,
                strategy_name="ema_pullback",
                target_price=Decimal("64200.00"),
                band_lower=Decimal("63890.00"),
                band_upper=Decimal("64540.00"),
                band_width_pct=Decimal("1.02"),
                rule_states_json=json.dumps(
                    {
                        "context": "trend",
                        "timeframes": {"regime": "15m", "trend": "15m", "entry": "5m"},
                        "rules": [
                            {
                                "label": "EMA trend bullish",
                                "state": "PASS",
                                "detail": "timeframe 15m: price 64210.45 / ema20 64182.10 / ema50 64095.75",
                            },
                            {
                                "label": "Pullback in range",
                                "state": "PASS",
                                "detail": "0.74% in [0.5, 1.5]",
                            },
                            {
                                "label": "Recovery candle",
                                "state": "PASS",
                                "detail": "timeframe 5m: current candle closed green and reclaimed the prior high",
                            },
                        ],
                    }
                ),
            )
        )
        self.repositories.insert_trade(
            Trade(
                id="demo-trade-closed-1",
                asset=asset,
                quantity=Decimal("0.02000000"),
                buy_order_id="demo-order-buy-closed-1",
                sell_order_id="demo-order-sell-closed-1",
                buy_time=closed_buy_time,
                sell_time=closed_sell_time,
                buy_price=Decimal("63150.00"),
                sell_price=Decimal("63680.00"),
                buy_fee=Decimal("3.16"),
                sell_fee=Decimal("3.18"),
                gross_profit=Decimal("10.60"),
                total_fees=Decimal("6.34"),
                net_profit=Decimal("4.26"),
                holding_duration_seconds=int((closed_sell_time - closed_buy_time).total_seconds()),
                status=TradeStatus.CLOSED,
                strategy_name="ema_pullback",
                regime=MarketRegime.TREND,
                created_at=closed_buy_time,
            )
        )
        self.repositories.insert_trade(
            Trade(
                id="demo-trade-open-1",
                asset=asset,
                quantity=Decimal("0.01500000"),
                buy_order_id="demo-order-buy-open-1",
                buy_time=open_buy_time,
                buy_price=Decimal("64020.00"),
                buy_fee=Decimal("2.40"),
                status=TradeStatus.OPEN,
                strategy_name="ema_pullback",
                regime=MarketRegime.TREND,
                created_at=open_buy_time,
            )
        )
        self.repositories.insert_order(
            Order(
                id="demo-order-buy-closed-1",
                trade_id="demo-trade-closed-1",
                time=closed_buy_time,
                type=OrderType.BUY,
                price=Decimal("63150.00"),
                quantity=Decimal("0.02000000"),
                status=OrderStatus.FILLED,
                post_only=True,
                exchange_id="demo-ex-buy-1",
                created_at=closed_buy_time,
            )
        )
        self.repositories.insert_order(
            Order(
                id="demo-order-sell-closed-1",
                trade_id="demo-trade-closed-1",
                time=closed_sell_time,
                type=OrderType.SELL,
                price=Decimal("63680.00"),
                quantity=Decimal("0.02000000"),
                status=OrderStatus.FILLED,
                post_only=True,
                exchange_id="demo-ex-sell-1",
                created_at=closed_sell_time,
            )
        )
        self.repositories.insert_order(
            Order(
                id="demo-order-buy-open-1",
                trade_id="demo-trade-open-1",
                time=open_buy_time,
                type=OrderType.BUY,
                price=Decimal("64020.00"),
                quantity=Decimal("0.01500000"),
                status=OrderStatus.FILLED,
                post_only=True,
                exchange_id="demo-ex-buy-2",
                created_at=open_buy_time,
            )
        )
        self.repositories.insert_log(
            level="INFO",
            service="demo_mode",
            message="seeded demo dashboard data into an empty SQLite database",
            context={"asset": asset},
        )
        self.repositories.insert_log(
            level="INFO",
            service="strategy",
            message="demo position remains open while the uptrend stays intact",
            context={"trade_id": "demo-trade-open-1", "regime": "TREND"},
        )
