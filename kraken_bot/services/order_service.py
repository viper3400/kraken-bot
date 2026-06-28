from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from uuid import uuid4

from kraken_bot.domain.enums import OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import ExchangeOrder, Order, PostOnlyExecution
from kraken_bot.domain.value_objects import quantize_money
from kraken_bot.exchange.base import ExchangeAdapter
from kraken_bot.persistence.repositories import SqliteRepositories


class OrderService(ABC):
    @abstractmethod
    def place_post_only_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        trade_id: str | None,
    ) -> Order: ...

    @abstractmethod
    def get_order_status(self, exchange_order_id: str) -> OrderStatus: ...

    @abstractmethod
    def plan_post_only_limit_order(
        self,
        asset: str,
        side: OrderType,
        strategy_price: Decimal,
    ) -> PostOnlyExecution: ...

    @abstractmethod
    def cancel_order(self, exchange_order_id: str) -> None: ...

    @abstractmethod
    def replace_order(
        self,
        exchange_order_id: str,
        new_price: Decimal,
        new_quantity: Decimal,
    ) -> Order: ...

    @abstractmethod
    def reconcile_asset_orders(self, asset: str) -> None: ...

    @abstractmethod
    def get_available_base_balance(self, asset: str) -> Decimal: ...


class DefaultOrderService(OrderService):
    def __init__(
        self,
        exchange: ExchangeAdapter,
        repositories: SqliteRepositories,
        post_only: bool,
    ) -> None:
        self.exchange = exchange
        self.repositories = repositories
        self.post_only = post_only

    def place_post_only_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        trade_id: str | None,
    ) -> Order:
        now = datetime.now(timezone.utc)
        order_id = str(uuid4())
        result = self.exchange.place_limit_order(asset, side, price, quantity, self.post_only)
        order = Order(
            id=order_id,
            trade_id=trade_id,
            time=now,
            type=side,
            price=price,
            quantity=quantity,
            status=result.status,
            post_only=self.post_only,
            exchange_id=result.exchange_order_id,
            created_at=now,
        )
        self.repositories.insert_order(order)
        self.repositories.insert_order_event(
            order_id=order.id,
            time=now,
            status=result.status,
            raw_payload=result.raw_payload,
        )
        return order

    def get_order_status(self, exchange_order_id: str) -> OrderStatus:
        return self.exchange.get_order(exchange_order_id).status

    def plan_post_only_limit_order(
        self,
        asset: str,
        side: OrderType,
        strategy_price: Decimal,
    ) -> PostOnlyExecution:
        if not self.post_only:
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
        quote = self.exchange.get_quote(asset)
        tick = quote.price_increment
        if side is OrderType.BUY:
            market_ceiling = quote.ask - tick
            if market_ceiling <= 0:
                return PostOnlyExecution(
                    asset=asset,
                    side=side,
                    strategy_price=strategy_price,
                    execution_price=None,
                    bid=quote.bid,
                    ask=quote.ask,
                    can_place=False,
                    reason="best ask does not leave room for a maker buy",
                )
            execution_price = self._round_to_increment(min(strategy_price, market_ceiling), tick, ROUND_DOWN)
            if execution_price <= 0:
                reason = "computed maker buy price is non-positive"
            elif execution_price >= quote.ask:
                reason = "computed buy price would cross the ask"
            elif execution_price > strategy_price:
                reason = "maker buy price exceeds strategy entry"
            else:
                reason = None
        else:
            market_floor = quote.bid + tick
            execution_price = self._round_to_increment(max(strategy_price, market_floor), tick, ROUND_UP)
            if execution_price <= quote.bid:
                reason = "computed sell price would cross the bid"
            elif execution_price < strategy_price:
                reason = "maker sell price falls below strategy exit"
            else:
                reason = None
        return PostOnlyExecution(
            asset=asset,
            side=side,
            strategy_price=strategy_price,
            execution_price=execution_price,
            bid=quote.bid,
            ask=quote.ask,
            can_place=reason is None,
            reason=reason,
        )

    def cancel_order(self, exchange_order_id: str) -> None:
        self.exchange.cancel_order(exchange_order_id)

    def replace_order(
        self,
        exchange_order_id: str,
        new_price: Decimal,
        new_quantity: Decimal,
    ) -> Order:
        self.cancel_order(exchange_order_id)
        existing = self.repositories.get_order_by_exchange_id(exchange_order_id)
        if existing is None:
            raise ValueError(f"unknown order {exchange_order_id}")
        return self.place_post_only_limit_order(
            asset=self.repositories.get_trade_asset(existing.trade_id),
            side=existing.type,
            price=new_price,
            quantity=new_quantity,
            trade_id=existing.trade_id,
        )

    def reconcile_asset_orders(self, asset: str) -> None:
        open_like_statuses = (OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)
        for order in self.repositories.list_orders_for_asset_by_statuses(asset, open_like_statuses):
            if not order.exchange_id:
                continue
            exchange_order = self.exchange.get_order(order.exchange_id)
            if exchange_order.status == order.status:
                continue
            self.repositories.update_order_status(order.id, exchange_order.status)
            self.repositories.insert_order_event(
                order_id=order.id,
                time=datetime.now(timezone.utc),
                status=exchange_order.status,
                raw_payload=exchange_order.raw_payload,
            )
            self._reconcile_trade_after_order_status_change(order, exchange_order)
        self._repair_open_trades_with_terminal_entry_orders(asset)
        self._repair_open_trades_with_filled_entry_orders(asset)
        self._repair_open_trades_with_filled_exit_orders(asset)

    def _reconcile_trade_after_order_status_change(self, order: Order, exchange_order: ExchangeOrder) -> None:
        if order.trade_id is None:
            return
        if order.type is OrderType.SELL and exchange_order.status is OrderStatus.FILLED:
            self._close_trade_from_filled_sell(order, exchange_order)
            return
        if order.type is not OrderType.BUY:
            return
        if exchange_order.status is OrderStatus.FILLED:
            self.repositories.update_trade_buy_fill(
                order.trade_id,
                exchange_order.closed_at,
                exchange_order.average_price,
                exchange_order.fee,
            )
            return
        if exchange_order.filled_quantity != Decimal("0"):
            return
        if exchange_order.status not in {OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED}:
            return
        self.repositories.update_trade_status(order.trade_id, TradeStatus.CANCELLED)

    def _repair_open_trades_with_terminal_entry_orders(self, asset: str) -> None:
        for order in self.repositories.list_open_trade_entry_orders_with_terminal_statuses(asset):
            if order.trade_id is None or not order.exchange_id:
                continue
            exchange_order = self.exchange.get_order(order.exchange_id)
            if exchange_order.filled_quantity != Decimal("0"):
                continue
            if exchange_order.status not in {OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED}:
                continue
            self.repositories.update_trade_status(order.trade_id, TradeStatus.CANCELLED)

    def _repair_open_trades_with_filled_entry_orders(self, asset: str) -> None:
        for order in self.repositories.list_open_trade_entry_orders_missing_fill_details(asset):
            if order.trade_id is None or not order.exchange_id:
                continue
            exchange_order = self.exchange.get_order(order.exchange_id)
            if exchange_order.status is not OrderStatus.FILLED:
                continue
            self.repositories.update_trade_buy_fill(
                order.trade_id,
                exchange_order.closed_at,
                exchange_order.average_price,
                exchange_order.fee,
            )

    def _repair_open_trades_with_filled_exit_orders(self, asset: str) -> None:
        for order in self.repositories.list_open_trade_exit_orders_missing_close_details(asset):
            if order.trade_id is None or not order.exchange_id:
                continue
            exchange_order = self.exchange.get_order(order.exchange_id)
            if exchange_order.status is not OrderStatus.FILLED:
                continue
            self._close_trade_from_filled_sell(order, exchange_order)

    def _close_trade_from_filled_sell(self, order: Order, exchange_order: ExchangeOrder) -> None:
        if order.trade_id is None:
            return
        trade = self.repositories.get_trade(order.trade_id)
        if trade is None or trade.buy_price is None or trade.buy_time is None or exchange_order.average_price is None:
            return
        sell_time = exchange_order.closed_at or datetime.now(timezone.utc)
        gross_profit = quantize_money((exchange_order.average_price - trade.buy_price) * trade.quantity)
        total_fees = quantize_money(trade.buy_fee + exchange_order.fee)
        net_profit = quantize_money(gross_profit - total_fees)
        holding_duration_seconds = max(0, int((sell_time - trade.buy_time).total_seconds()))
        self.repositories.update_trade_sell_fill(
            trade_id=order.trade_id,
            sell_order_id=order.id,
            sell_time=sell_time,
            sell_price=exchange_order.average_price,
            sell_fee=exchange_order.fee,
            gross_profit=gross_profit,
            total_fees=total_fees,
            net_profit=net_profit,
            holding_duration_seconds=holding_duration_seconds,
        )

    def get_available_base_balance(self, asset: str) -> Decimal:
        return self.exchange.get_available_base_balance(asset)

    def _round_to_increment(self, value: Decimal, increment: Decimal, rounding: str) -> Decimal:
        if increment <= 0:
            return value
        units = (value / increment).to_integral_value(rounding=rounding)
        return units * increment
