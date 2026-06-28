from __future__ import annotations

import argparse
import threading
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from kraken_bot.app.config import BotConfig
from kraken_bot.app.container import Container
from kraken_bot.domain.enums import Decision, OrderType, TradeStatus
from kraken_bot.domain.models import PostOnlyExecution, Trade
from kraken_bot.exchange.kraken_adapter import KrakenApiError


class BotRunner:
    def __init__(self, container: Container) -> None:
        self.container = container
        self.config = container.config

    def run_cycle(self) -> Decision:
        now = datetime.now(timezone.utc)
        asset = self.config.bot.asset
        self.container.order_service.reconcile_asset_orders(asset)
        portfolio = self.container.portfolio_service.get_state(asset)
        regime_candles = self.container.market_data_service.get_candles(
            asset=asset,
            interval=self.config.market_regime.timeframe,
            limit=max(self.config.market_regime.lookback_candles, self.config.trend_strategy.ema_slow + 1),
        )
        trend_candles = self.container.market_data_service.get_candles(
            asset=asset,
            interval=self.config.trend_strategy.trend_timeframe,
            limit=self.config.trend_strategy.ema_slow + 5,
        )
        entry_candles = self.container.market_data_service.get_candles(
            asset=asset,
            interval=self.config.trend_strategy.entry_timeframe,
            limit=5,
        )
        regime_analysis = self.container.market_regime_service.analyze(regime_candles, self.config)
        market = self.container.market_data_service.get_market_snapshot(asset, trend_candles, now, regime_analysis)

        decision = self.container.strategy_service.decide(
            market=market,
            entry_history=entry_candles,
            portfolio=portfolio,
            config=self.config,
        )

        if decision.decision is Decision.BUY:
            self._handle_buy(asset, decision, now)
        elif decision.decision is Decision.SELL:
            self._handle_sell(asset, decision, now)

        self.container.persistence_service.record_config_snapshot(self.config, now)
        self.container.persistence_service.save_market_snapshot(market)
        self.container.persistence_service.save_strategy_decision(decision)
        return decision.decision

    def _handle_buy(self, asset: str, decision, now: datetime) -> None:
        strategy_price = decision.target_price or decision.price or Decimal("0")
        quantity = Decimal(self.config.trade.base_order_quantity)
        required_capital = (quantity * strategy_price).quantize(Decimal("0.00000001"))
        if not self.container.portfolio_service.can_open_trade(asset, required_capital):
            return
        execution = self.container.order_service.plan_post_only_limit_order(asset, OrderType.BUY, strategy_price)
        if not execution.can_place or execution.execution_price is None:
            self._log_post_only_skip(decision.strategy_name, execution)
            return

        trade = Trade(
            id=str(uuid4()),
            asset=asset,
            quantity=quantity,
            buy_order_id=None,
            status=TradeStatus.OPEN,
            strategy_name=decision.strategy_name,
            regime=decision.regime,
            created_at=now,
        )
        order = self.container.order_service.place_post_only_limit_order(
            asset=asset,
            side=OrderType.BUY,
            price=execution.execution_price,
            quantity=quantity,
            trade_id=trade.id,
        )

        self.container.persistence_service.create_trade(
            replace(trade, buy_order_id=order.id)
        )

    def _handle_sell(self, asset: str, decision, now: datetime) -> None:
        strategy_price = decision.target_price or decision.price or Decimal("0")
        portfolio = self.container.portfolio_service.get_state(asset)
        if portfolio.open_trade is None or portfolio.has_open_order:
            return
        available_base_balance = self.container.order_service.get_available_base_balance(asset)
        if available_base_balance < portfolio.open_trade.quantity:
            self.container.repositories.insert_log(
                level="ERROR",
                service="sell_guard",
                message="position quantity exceeds available Kraken base balance",
                context={
                    "asset": asset,
                    "position_quantity": str(portfolio.open_trade.quantity),
                    "available_base_balance": str(available_base_balance),
                    "trade_id": portfolio.open_trade.id,
                },
            )
            return
        execution = self.container.order_service.plan_post_only_limit_order(asset, OrderType.SELL, strategy_price)
        if not execution.can_place or execution.execution_price is None:
            self._log_post_only_skip(decision.strategy_name, execution)
            return
        self.container.order_service.place_post_only_limit_order(
            asset=asset,
            side=OrderType.SELL,
            price=execution.execution_price,
            quantity=portfolio.open_trade.quantity,
            trade_id=portfolio.open_trade.id,
        )

    def _log_post_only_skip(self, strategy_name: str | None, execution: PostOnlyExecution) -> None:
        self.container.repositories.insert_log(
            level="INFO",
            service="post_only_execution_guard",
            message="skipped strategy signal because no maker-safe post-only price satisfied the strategy",
            context={
                "asset": execution.asset,
                "side": execution.side.value,
                "strategy_name": strategy_name,
                "strategy_price": str(execution.strategy_price),
                "best_bid": str(execution.bid),
                "best_ask": str(execution.ask),
                "candidate_execution_price": str(execution.execution_price) if execution.execution_price is not None else None,
                "reason": execution.reason,
            },
        )

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        interval = self.config.bot.polling_interval_seconds
        while not stop_event.is_set():
            self.run_cycle()
            if stop_event.wait(interval):
                break


class BotLoopController:
    def __init__(self, runner: BotRunner) -> None:
        self.runner = runner
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started_at: datetime | None = None
        self._last_cycle_at: datetime | None = None
        self._last_error: str | None = None
        self._cycle_count = 0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event = threading.Event()
            self._started_at = datetime.now(timezone.utc)
            self._thread = threading.Thread(target=self._run, name="kraken-bot-loop", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def snapshot(self) -> dict[str, object]:
        thread = self._thread
        return {
            "running": bool(thread and thread.is_alive()),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_error": self._last_error,
            "cycle_count": self._cycle_count,
            "polling_interval_seconds": self.runner.config.bot.polling_interval_seconds,
        }

    def _run(self) -> None:
        interval = self.runner.config.bot.polling_interval_seconds
        while not self._stop_event.is_set():
            try:
                self.runner.run_cycle()
                self._last_cycle_at = datetime.now(timezone.utc)
                self._cycle_count += 1
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
            if self._stop_event.wait(interval):
                break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(Path("config.yaml")),
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously using bot.polling_interval_seconds",
    )
    args = parser.parse_args()
    config = BotConfig.load(args.config)
    container = Container(config)
    runner = BotRunner(container)
    if args.loop:
        runner.run_forever()
    else:
        runner.run_cycle()
