from datetime import datetime, timezone
from decimal import Decimal

import pytest

from kraken_bot.app.runner import BotRunner
from kraken_bot.domain.enums import Decision, MarketRegime, OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import Order, PostOnlyExecution, StrategyDecision, Trade
from kraken_bot.exchange.kraken_adapter import KrakenApiError


class RecordingPortfolioService:
    def __init__(self) -> None:
        self.required_capital: Decimal | None = None
        self.state = None

    def can_open_trade(self, asset: str, required_capital: Decimal) -> bool:
        self.required_capital = required_capital
        return True

    def get_state(self, asset: str):
        if self.state is None:
            raise NotImplementedError
        return self.state


class RecordingPersistenceService:
    def __init__(self) -> None:
        self.trades = []
        self.config_snapshots = []
        self.market_snapshots = []
        self.strategy_decisions = []

    def create_trade(self, trade) -> None:
        self.trades.append(trade)

    def record_config_snapshot(self, config, time) -> None:
        self.config_snapshots.append((config, time))

    def save_market_snapshot(self, snapshot) -> None:
        self.market_snapshots.append(snapshot)

    def save_strategy_decision(self, decision) -> None:
        self.strategy_decisions.append(decision)


class RecordingOrderService:
    def __init__(self) -> None:
        self.calls = []
        self.reconciled_assets = []
        self.available_base_balance = Decimal("1")
        self.execution = PostOnlyExecution(
            asset="SOL/USD",
            side=OrderType.BUY,
            strategy_price=Decimal("72.25"),
            execution_price=Decimal("72.20"),
            bid=Decimal("72.19"),
            ask=Decimal("72.21"),
            can_place=True,
            reason=None,
        )

    def place_post_only_limit_order(self, asset, side, price, quantity, trade_id):
        self.calls.append(
            {"asset": asset, "side": side, "price": price, "quantity": quantity, "trade_id": trade_id}
        )
        return Order(
            id="order-1",
            trade_id=trade_id,
            time=datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc),
            type=OrderType.BUY,
            price=price,
            quantity=quantity,
            status=OrderStatus.SUBMITTED,
            post_only=True,
            exchange_id="ex-1",
            created_at=datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc),
        )

    def plan_post_only_limit_order(self, asset, side, strategy_price):
        return PostOnlyExecution(
            asset=asset,
            side=side,
            strategy_price=strategy_price,
            execution_price=self.execution.execution_price,
            bid=self.execution.bid,
            ask=self.execution.ask,
            can_place=self.execution.can_place,
            reason=self.execution.reason,
        )

    def reconcile_asset_orders(self, asset: str) -> None:
        self.reconciled_assets.append(asset)

    def get_available_base_balance(self, asset: str) -> Decimal:
        return self.available_base_balance


class FailingOrderService:
    def plan_post_only_limit_order(self, asset, side, strategy_price):
        return PostOnlyExecution(
            asset=asset,
            side=side,
            strategy_price=strategy_price,
            execution_price=strategy_price,
            bid=Decimal("0"),
            ask=Decimal("0"),
            can_place=True,
            reason=None,
        )

    def place_post_only_limit_order(self, asset, side, price, quantity, trade_id):
        raise KrakenApiError("place order", "boom")

    def reconcile_asset_orders(self, asset: str) -> None:
        return None

    def get_available_base_balance(self, asset: str) -> Decimal:
        return Decimal("1")


class RecordingRepositories:
    def __init__(self) -> None:
        self.logs = []

    def insert_log(self, level: str, service: str, message: str, context=None) -> None:
        self.logs.append({"level": level, "service": service, "message": message, "context": context})


def build_container(order_service, portfolio_service, persistence_service, repositories):
    return type(
        "Container",
        (),
        {
            "config": type(
                "Config",
                (),
                {
                    "trade": type("Trade", (), {"base_order_quantity": "0.06"})(),
                    "bot": type("Bot", (), {"asset": "SOL/USD"})(),
                },
            )(),
            "order_service": order_service,
            "portfolio_service": portfolio_service,
            "persistence_service": persistence_service,
            "repositories": repositories,
        },
    )()


def build_run_cycle_container(repositories):
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    return type(
        "Container",
        (),
        {
            "config": type(
                "Config",
                (),
                {
                    "trade": type("Trade", (), {"base_order_quantity": "0.06"})(),
                    "bot": type("Bot", (), {"asset": "SOL/USD"})(),
                    "trend_strategy": type(
                        "Trend",
                        (),
                        {"ema_slow": 50, "trend_timeframe": "15m", "entry_timeframe": "5m"},
                    )(),
                    "market_regime": type("Regime", (), {"lookback_candles": 30, "timeframe": "1h"})(),
                },
            )(),
            "repositories": repositories,
            "persistence_service": persistence_service,
            "portfolio_service": type("Portfolio", (), {"get_state": lambda *args, **kwargs: None})(),
            "market_data_service": type(
                "MarketData",
                (),
                {"get_candles": lambda *args, **kwargs: (_ for _ in ()).throw(KrakenApiError("get OHLC", "timeout"))},
            )(),
            "market_regime_service": object(),
            "strategy_service": object(),
            "order_service": order_service,
        },
    )(), persistence_service, order_service


class RecordingMarketDataService:
    def __init__(self) -> None:
        self.calls = []

    def get_candles(self, asset: str, interval: str, limit: int):
        self.calls.append({"asset": asset, "interval": interval, "limit": limit})
        return ["candles", interval]

    def get_market_snapshot(self, asset: str, candles, now, regime_analysis=None):
        return {"asset": asset, "candles": candles, "regime_analysis": regime_analysis}


class RecordingMarketRegimeService:
    def __init__(self) -> None:
        self.calls = []

    def analyze(self, candles, config):
        self.calls.append({"candles": candles, "config": config})
        return "regime-analysis"


class RecordingStrategyService:
    def __init__(self) -> None:
        self.calls = []

    def decide(self, market, entry_history, portfolio, config):
        self.calls.append(
            {
                "market": market,
                "entry_history": entry_history,
                "portfolio": portfolio,
                "config": config,
            }
        )
        return StrategyDecision(
            id="dec-3",
            time=datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc),
            asset="SOL/USD",
            decision=Decision.HOLD,
            reason="No entry",
            regime=MarketRegime.TREND,
            strategy_name="ema_pullback",
        )


def build_buy_decision() -> StrategyDecision:
    return StrategyDecision(
        id="dec-1",
        time=datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc),
        asset="SOL/USD",
        decision=Decision.BUY,
        reason="Near support",
        price=Decimal("72.08"),
        target_price=Decimal("72.25"),
        regime=MarketRegime.SIDEWAYS,
        strategy_name="range",
    )


def build_sell_decision() -> StrategyDecision:
    return StrategyDecision(
        id="dec-2",
        time=datetime(2026, 6, 28, 6, 47, tzinfo=timezone.utc),
        asset="SOL/USD",
        decision=Decision.SELL,
        reason="Stop loss reached",
        price=Decimal("70.31"),
        target_price=Decimal("70.31"),
        regime=MarketRegime.SIDEWAYS,
        strategy_name="range",
    )


def test_handle_buy_uses_base_asset_quantity() -> None:
    portfolio_service = RecordingPortfolioService()
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    runner = BotRunner(build_container(order_service, portfolio_service, persistence_service, RecordingRepositories()))

    runner._handle_buy("SOL/USD", build_buy_decision(), datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc))

    assert portfolio_service.required_capital == Decimal("4.33500000")
    assert order_service.calls[0]["quantity"] == Decimal("0.06")
    assert order_service.calls[0]["price"] == Decimal("72.20")
    assert persistence_service.trades[0].quantity == Decimal("0.06")
    assert persistence_service.trades[0].buy_order_id is not None


def test_handle_buy_skips_trade_when_no_maker_safe_price_exists() -> None:
    portfolio_service = RecordingPortfolioService()
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    order_service.execution = PostOnlyExecution(
        asset="SOL/USD",
        side=OrderType.BUY,
        strategy_price=Decimal("72.25"),
        execution_price=None,
        bid=Decimal("72.25"),
        ask=Decimal("72.25"),
        can_place=False,
        reason="best ask does not leave room for a maker buy",
    )
    repositories = RecordingRepositories()
    runner = BotRunner(build_container(order_service, portfolio_service, persistence_service, repositories))

    runner._handle_buy("SOL/USD", build_buy_decision(), datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc))

    assert order_service.calls == []
    assert persistence_service.trades == []
    assert repositories.logs == [
        {
            "level": "INFO",
            "service": "post_only_execution_guard",
            "message": "skipped strategy signal because no maker-safe post-only price satisfied the strategy",
            "context": {
                "asset": "SOL/USD",
                "side": "BUY",
                "strategy_name": "range",
                "strategy_price": "72.25",
                "best_bid": "72.25",
                "best_ask": "72.25",
                "candidate_execution_price": None,
                "reason": "best ask does not leave room for a maker buy",
            },
        }
    ]


def test_handle_buy_does_not_persist_trade_when_order_submission_fails() -> None:
    portfolio_service = RecordingPortfolioService()
    persistence_service = RecordingPersistenceService()
    repositories = RecordingRepositories()
    runner = BotRunner(build_container(FailingOrderService(), portfolio_service, persistence_service, repositories))

    with pytest.raises(KrakenApiError):
        runner._handle_buy("SOL/USD", build_buy_decision(), datetime(2026, 6, 27, 17, 3, tzinfo=timezone.utc))

    assert persistence_service.trades == []
    assert repositories.logs == []


def test_run_cycle_does_not_persist_when_kraken_api_fails() -> None:
    repositories = RecordingRepositories()
    container, persistence_service, order_service = build_run_cycle_container(repositories)
    runner = BotRunner(container)

    with pytest.raises(KrakenApiError):
        runner.run_cycle()

    assert order_service.reconciled_assets == ["SOL/USD"]
    assert repositories.logs == []
    assert persistence_service.config_snapshots == []
    assert persistence_service.market_snapshots == []
    assert persistence_service.strategy_decisions == []
    assert persistence_service.trades == []


def test_run_cycle_loads_regime_trend_and_entry_candles_separately() -> None:
    repositories = RecordingRepositories()
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    market_data_service = RecordingMarketDataService()
    regime_service = RecordingMarketRegimeService()
    strategy_service = RecordingStrategyService()
    container = type(
        "Container",
        (),
        {
            "config": type(
                "Config",
                (),
                {
                    "trade": type("Trade", (), {"base_order_quantity": "0.06"})(),
                    "bot": type("Bot", (), {"asset": "SOL/USD"})(),
                    "trend_strategy": type(
                        "Trend",
                        (),
                        {"ema_slow": 50, "trend_timeframe": "15m", "entry_timeframe": "5m"},
                    )(),
                    "market_regime": type("Regime", (), {"lookback_candles": 30, "timeframe": "1h"})(),
                },
            )(),
            "repositories": repositories,
            "persistence_service": persistence_service,
            "portfolio_service": type("Portfolio", (), {"get_state": lambda *args, **kwargs: "portfolio"})(),
            "market_data_service": market_data_service,
            "market_regime_service": regime_service,
            "strategy_service": strategy_service,
            "order_service": order_service,
        },
    )()
    runner = BotRunner(container)

    decision = runner.run_cycle()

    assert decision is Decision.HOLD
    assert market_data_service.calls == [
        {"asset": "SOL/USD", "interval": "1h", "limit": 51},
        {"asset": "SOL/USD", "interval": "15m", "limit": 55},
        {"asset": "SOL/USD", "interval": "5m", "limit": 5},
    ]
    assert regime_service.calls == [{"candles": ["candles", "1h"], "config": container.config}]
    assert strategy_service.calls[0]["market"]["candles"] == ["candles", "15m"]
    assert strategy_service.calls[0]["entry_history"] == ["candles", "5m"]


def test_handle_sell_skips_order_when_available_balance_cannot_cover_position() -> None:
    portfolio_service = RecordingPortfolioService()
    portfolio_service.state = type(
        "PortfolioState",
        (),
        {
            "open_trade": Trade(
                id="trade-1",
                asset="SOL/USD",
                quantity=Decimal("0.06"),
                buy_price=Decimal("71.03"),
                buy_time=datetime(2026, 6, 27, 21, 48, tzinfo=timezone.utc),
                status=TradeStatus.OPEN,
                created_at=datetime(2026, 6, 27, 21, 48, tzinfo=timezone.utc),
            ),
            "has_open_order": False,
        },
    )()
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    order_service.available_base_balance = Decimal("0.0000000068")
    repositories = RecordingRepositories()
    runner = BotRunner(build_container(order_service, portfolio_service, persistence_service, repositories))

    runner._handle_sell("SOL/USD", build_sell_decision(), datetime(2026, 6, 28, 6, 47, tzinfo=timezone.utc))

    assert order_service.calls == []
    assert repositories.logs == [
        {
            "level": "ERROR",
            "service": "sell_guard",
            "message": "position quantity exceeds available Kraken base balance",
            "context": {
                "asset": "SOL/USD",
                "position_quantity": "0.06",
                "available_base_balance": "6.8E-9",
                "trade_id": "trade-1",
            },
        }
    ]


def test_handle_sell_skips_order_when_execution_guard_rejects_post_only_price() -> None:
    portfolio_service = RecordingPortfolioService()
    portfolio_service.state = type(
        "PortfolioState",
        (),
        {
            "open_trade": Trade(
                id="trade-1",
                asset="SOL/USD",
                quantity=Decimal("0.06"),
                buy_price=Decimal("71.03"),
                buy_time=datetime(2026, 6, 27, 21, 48, tzinfo=timezone.utc),
                status=TradeStatus.OPEN,
                created_at=datetime(2026, 6, 27, 21, 48, tzinfo=timezone.utc),
            ),
            "has_open_order": False,
        },
    )()
    persistence_service = RecordingPersistenceService()
    order_service = RecordingOrderService()
    order_service.execution = PostOnlyExecution(
        asset="SOL/USD",
        side=OrderType.SELL,
        strategy_price=Decimal("70.31"),
        execution_price=None,
        bid=Decimal("70.31"),
        ask=Decimal("70.31"),
        can_place=False,
        reason="computed sell price would cross the bid",
    )
    repositories = RecordingRepositories()
    runner = BotRunner(build_container(order_service, portfolio_service, persistence_service, repositories))

    runner._handle_sell("SOL/USD", build_sell_decision(), datetime(2026, 6, 28, 6, 47, tzinfo=timezone.utc))

    assert order_service.calls == []
    assert repositories.logs == [
        {
            "level": "INFO",
            "service": "post_only_execution_guard",
            "message": "skipped strategy signal because no maker-safe post-only price satisfied the strategy",
            "context": {
                "asset": "SOL/USD",
                "side": "SELL",
                "strategy_name": "range",
                "strategy_price": "70.31",
                "best_bid": "70.31",
                "best_ask": "70.31",
                "candidate_execution_price": None,
                "reason": "computed sell price would cross the bid",
            },
        }
    ]
