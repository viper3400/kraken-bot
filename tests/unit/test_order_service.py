from datetime import datetime, timezone
from decimal import Decimal

from kraken_bot.domain.enums import OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import ExchangeOrder, Order, Quote, Trade
from kraken_bot.services.order_service import DefaultOrderService


class StubExchange:
    def __init__(self, status: OrderStatus) -> None:
        self.status = status
        self.quote = Quote(
            asset="SOL/USD",
            bid=Decimal("71.00"),
            ask=Decimal("71.02"),
            price_increment=Decimal("0.01"),
            time=datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc),
        )

    def place_limit_order(self, asset, side, price, quantity, post_only):
        raise NotImplementedError

    def get_order(self, exchange_order_id: str) -> ExchangeOrder:
        return ExchangeOrder(
            exchange_order_id=exchange_order_id,
            status=self.status,
            filled_quantity=Decimal("0"),
            average_price=None,
            fee=Decimal("0"),
            raw_payload='{"status":"canceled"}',
        )

    def cancel_order(self, exchange_order_id: str) -> None:
        raise NotImplementedError

    def get_ticker(self, asset: str):
        raise NotImplementedError

    def get_quote(self, asset: str) -> Quote:
        return self.quote

    def get_ohlc(self, asset: str, interval: str, limit: int):
        raise NotImplementedError

    def list_open_orders(self, asset: str | None = None):
        raise NotImplementedError


class StubRepositories:
    def __init__(self, order: Order) -> None:
        self.order = order
        self.updated = []
        self.events = []
        self.trade_updates = []
        self.trade_buy_fills = []
        self.trade_sell_fills = []
        self.trade = None

    def list_orders_for_asset_by_statuses(self, asset, statuses):
        return [self.order]

    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        self.updated.append((order_id, status))

    def insert_order_event(self, order_id: str, time: datetime, status: OrderStatus, raw_payload: str | None) -> None:
        self.events.append((order_id, status, raw_payload))

    def update_trade_status(self, trade_id: str, status) -> None:
        self.trade_updates.append((trade_id, status))

    def update_trade_buy_fill(self, trade_id: str, buy_time: datetime | None, buy_price, buy_fee) -> None:
        self.trade_buy_fills.append((trade_id, buy_time, buy_price, buy_fee))

    def list_open_trade_entry_orders_with_terminal_statuses(self, asset: str):
        return []

    def list_open_trade_entry_orders_missing_fill_details(self, asset: str):
        return []

    def list_open_trade_exit_orders_missing_close_details(self, asset: str):
        return []

    def update_trade_sell_fill(
        self,
        trade_id: str,
        sell_order_id: str | None,
        sell_time: datetime | None,
        sell_price,
        sell_fee,
        gross_profit,
        total_fees,
        net_profit,
        holding_duration_seconds,
    ) -> None:
        self.trade_sell_fills.append(
            (
                trade_id,
                sell_order_id,
                sell_time,
                sell_price,
                sell_fee,
                gross_profit,
                total_fees,
                net_profit,
                holding_duration_seconds,
            )
        )

    def get_trade(self, trade_id: str):
        return self.trade


def test_reconcile_asset_orders_updates_changed_status() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.SUBMITTED,
        post_only=True,
        exchange_id="OCQUVE-AUHB7-3EFVK3",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    service = DefaultOrderService(StubExchange(OrderStatus.CANCELLED), repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == [("local-order-1", OrderStatus.CANCELLED)]
    assert repositories.events == [("local-order-1", OrderStatus.CANCELLED, '{"status":"canceled"}')]
    assert repositories.trade_updates == [("trade-1", TradeStatus.CANCELLED)]


def test_plan_post_only_buy_places_at_or_below_strategy_entry() -> None:
    repositories = StubRepositories(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
            type=OrderType.BUY,
            price=Decimal("71.08"),
            quantity=Decimal("0.06"),
            status=OrderStatus.SUBMITTED,
            post_only=True,
            exchange_id="exchange-1",
            created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        )
    )
    exchange = StubExchange(OrderStatus.SUBMITTED)
    service = DefaultOrderService(exchange, repositories, post_only=True)

    execution = service.plan_post_only_limit_order("SOL/USD", OrderType.BUY, Decimal("71.05"))

    assert execution.can_place is True
    assert execution.execution_price == Decimal("71.01")
    assert execution.reason is None


def test_plan_post_only_buy_skips_when_best_ask_leaves_no_maker_room() -> None:
    repositories = StubRepositories(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
            type=OrderType.BUY,
            price=Decimal("71.08"),
            quantity=Decimal("0.06"),
            status=OrderStatus.SUBMITTED,
            post_only=True,
            exchange_id="exchange-1",
            created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        )
    )
    exchange = StubExchange(OrderStatus.SUBMITTED)
    exchange.quote = Quote(
        asset="SOL/USD",
        bid=Decimal("0.04"),
        ask=Decimal("0.05"),
        price_increment=Decimal("0.05"),
        time=datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc),
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    execution = service.plan_post_only_limit_order("SOL/USD", OrderType.BUY, Decimal("71.01"))

    assert execution.can_place is False
    assert execution.execution_price is None
    assert execution.reason == "best ask does not leave room for a maker buy"


def test_plan_post_only_sell_places_at_or_above_strategy_exit() -> None:
    repositories = StubRepositories(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
            type=OrderType.SELL,
            price=Decimal("71.08"),
            quantity=Decimal("0.06"),
            status=OrderStatus.SUBMITTED,
            post_only=True,
            exchange_id="exchange-1",
            created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        )
    )
    exchange = StubExchange(OrderStatus.SUBMITTED)
    service = DefaultOrderService(exchange, repositories, post_only=True)

    execution = service.plan_post_only_limit_order("SOL/USD", OrderType.SELL, Decimal("71.03"))

    assert execution.can_place is True
    assert execution.execution_price == Decimal("71.03")
    assert execution.reason is None


def test_plan_post_only_sell_rounds_up_to_preserve_strategy_exit() -> None:
    repositories = StubRepositories(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
            type=OrderType.SELL,
            price=Decimal("71.08"),
            quantity=Decimal("0.06"),
            status=OrderStatus.SUBMITTED,
            post_only=True,
            exchange_id="exchange-1",
            created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        )
    )
    exchange = StubExchange(OrderStatus.SUBMITTED)
    exchange.quote = Quote(
        asset="SOL/USD",
        bid=Decimal("71.00"),
        ask=Decimal("71.02"),
        price_increment=Decimal("0.05"),
        time=datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc),
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    execution = service.plan_post_only_limit_order("SOL/USD", OrderType.SELL, Decimal("71.06"))

    assert execution.can_place is True
    assert execution.execution_price == Decimal("71.10")


def test_reconcile_asset_orders_skips_unchanged_status() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.SUBMITTED,
        post_only=True,
        exchange_id="OCQUVE-AUHB7-3EFVK3",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    service = DefaultOrderService(StubExchange(OrderStatus.SUBMITTED), repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == []
    assert repositories.events == []
    assert repositories.trade_updates == []
    assert repositories.trade_buy_fills == []


def test_reconcile_asset_orders_keeps_trade_open_when_buy_partially_filled() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.OPEN,
        post_only=True,
        exchange_id="OCQUVE-AUHB7-3EFVK3",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    exchange = StubExchange(OrderStatus.CANCELLED)
    exchange.get_order = lambda exchange_order_id: ExchangeOrder(
        exchange_order_id=exchange_order_id,
        status=OrderStatus.CANCELLED,
        filled_quantity=Decimal("0.01"),
        average_price=Decimal("71.08"),
        fee=Decimal("0"),
        raw_payload='{"status":"canceled","vol_exec":"0.01"}',
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == [("local-order-1", OrderStatus.CANCELLED)]
    assert repositories.trade_updates == []
    assert repositories.trade_buy_fills == []


def test_reconcile_asset_orders_repairs_stale_open_trade_from_terminal_buy_order() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.CANCELLED,
        post_only=True,
        exchange_id="OCQUVE-AUHB7-3EFVK3",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    repositories.list_orders_for_asset_by_statuses = lambda asset, statuses: []
    repositories.list_open_trade_entry_orders_with_terminal_statuses = lambda asset: [order]
    service = DefaultOrderService(StubExchange(OrderStatus.CANCELLED), repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == []
    assert repositories.events == []
    assert repositories.trade_updates == [("trade-1", TradeStatus.CANCELLED)]
    assert repositories.trade_buy_fills == []


def test_reconcile_asset_orders_promotes_filled_buy_into_trade() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.OPEN,
        post_only=True,
        exchange_id="OL2ZN5-XL7VP-77IF4R",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    exchange = StubExchange(OrderStatus.FILLED)
    exchange.get_order = lambda exchange_order_id: ExchangeOrder(
        exchange_order_id=exchange_order_id,
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.06"),
        average_price=Decimal("71.03"),
        fee=Decimal("0.01065"),
        closed_at=datetime(2026, 6, 27, 19, 49, tzinfo=timezone.utc),
        raw_payload='{"status":"closed","avg_price":"71.03"}',
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == [("local-order-1", OrderStatus.FILLED)]
    assert repositories.trade_buy_fills == [
        ("trade-1", datetime(2026, 6, 27, 19, 49, tzinfo=timezone.utc), Decimal("71.03"), Decimal("0.01065"))
    ]


def test_reconcile_asset_orders_repairs_stale_open_trade_from_filled_buy_order() -> None:
    order = Order(
        id="local-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
        type=OrderType.BUY,
        price=Decimal("71.08"),
        quantity=Decimal("0.06"),
        status=OrderStatus.FILLED,
        post_only=True,
        exchange_id="OL2ZN5-XL7VP-77IF4R",
        created_at=datetime(2026, 6, 27, 19, 35, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    repositories.list_orders_for_asset_by_statuses = lambda asset, statuses: []
    repositories.list_open_trade_entry_orders_with_terminal_statuses = lambda asset: []
    repositories.list_open_trade_entry_orders_missing_fill_details = lambda asset: [order]
    exchange = StubExchange(OrderStatus.FILLED)
    exchange.get_order = lambda exchange_order_id: ExchangeOrder(
        exchange_order_id=exchange_order_id,
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.06"),
        average_price=Decimal("71.03"),
        fee=Decimal("0.01065"),
        closed_at=datetime(2026, 6, 27, 19, 49, tzinfo=timezone.utc),
        raw_payload='{"status":"closed","avg_price":"71.03"}',
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.trade_buy_fills == [
        ("trade-1", datetime(2026, 6, 27, 19, 49, tzinfo=timezone.utc), Decimal("71.03"), Decimal("0.01065"))
    ]


def test_reconcile_asset_orders_closes_trade_from_filled_sell() -> None:
    order = Order(
        id="sell-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 28, 6, 46, tzinfo=timezone.utc),
        type=OrderType.SELL,
        price=Decimal("70.31"),
        quantity=Decimal("0.06"),
        status=OrderStatus.OPEN,
        post_only=True,
        exchange_id="O5QXLY-KXQGP-4DSURV",
        created_at=datetime(2026, 6, 28, 6, 46, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    repositories.trade = Trade(
        id="trade-1",
        asset="SOL/USD",
        quantity=Decimal("0.06"),
        buy_order_id="buy-order-1",
        buy_time=datetime(2026, 6, 27, 21, 48, 50, tzinfo=timezone.utc),
        buy_price=Decimal("71.03"),
        buy_fee=Decimal("0.01065"),
        status=TradeStatus.OPEN,
        created_at=datetime(2026, 6, 27, 21, 48, 46, tzinfo=timezone.utc),
    )
    exchange = StubExchange(OrderStatus.FILLED)
    exchange.get_order = lambda exchange_order_id: ExchangeOrder(
        exchange_order_id=exchange_order_id,
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.06"),
        average_price=Decimal("70.31"),
        fee=Decimal("0.01055"),
        closed_at=datetime(2026, 6, 28, 6, 47, 22, tzinfo=timezone.utc),
        raw_payload='{"status":"closed","price":"70.31"}',
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.updated == [("sell-order-1", OrderStatus.FILLED)]
    assert repositories.trade_sell_fills == [
        (
            "trade-1",
            "sell-order-1",
            datetime(2026, 6, 28, 6, 47, 22, tzinfo=timezone.utc),
            Decimal("70.31"),
                Decimal("0.01055"),
                Decimal("-0.04"),
                Decimal("0.02"),
                Decimal("-0.06"),
            32312,
        )
    ]


def test_reconcile_asset_orders_repairs_stale_open_trade_from_filled_sell_order() -> None:
    order = Order(
        id="sell-order-1",
        trade_id="trade-1",
        time=datetime(2026, 6, 28, 6, 46, tzinfo=timezone.utc),
        type=OrderType.SELL,
        price=Decimal("70.31"),
        quantity=Decimal("0.06"),
        status=OrderStatus.FILLED,
        post_only=True,
        exchange_id="O5QXLY-KXQGP-4DSURV",
        created_at=datetime(2026, 6, 28, 6, 46, tzinfo=timezone.utc),
    )
    repositories = StubRepositories(order)
    repositories.trade = Trade(
        id="trade-1",
        asset="SOL/USD",
        quantity=Decimal("0.06"),
        buy_order_id="buy-order-1",
        buy_time=datetime(2026, 6, 27, 21, 48, 50, tzinfo=timezone.utc),
        buy_price=Decimal("71.03"),
        buy_fee=Decimal("0.01065"),
        status=TradeStatus.OPEN,
        created_at=datetime(2026, 6, 27, 21, 48, 46, tzinfo=timezone.utc),
    )
    repositories.list_orders_for_asset_by_statuses = lambda asset, statuses: []
    repositories.list_open_trade_entry_orders_with_terminal_statuses = lambda asset: []
    repositories.list_open_trade_entry_orders_missing_fill_details = lambda asset: []
    repositories.list_open_trade_exit_orders_missing_close_details = lambda asset: [order]
    exchange = StubExchange(OrderStatus.FILLED)
    exchange.get_order = lambda exchange_order_id: ExchangeOrder(
        exchange_order_id=exchange_order_id,
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.06"),
        average_price=Decimal("70.31"),
        fee=Decimal("0.01055"),
        closed_at=datetime(2026, 6, 28, 6, 47, 22, tzinfo=timezone.utc),
        raw_payload='{"status":"closed","price":"70.31"}',
    )
    service = DefaultOrderService(exchange, repositories, post_only=True)

    service.reconcile_asset_orders("SOL/USD")

    assert repositories.trade_sell_fills == [
        (
            "trade-1",
            "sell-order-1",
            datetime(2026, 6, 28, 6, 47, 22, tzinfo=timezone.utc),
            Decimal("70.31"),
            Decimal("0.01055"),
            Decimal("-0.04"),
            Decimal("0.02"),
            Decimal("-0.06"),
            32312,
        )
    ]
