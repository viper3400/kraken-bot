from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from kraken_bot.domain.enums import OrderType
from kraken_bot.domain.models import Candle, ExchangeOpenOrder, ExchangeOrder, ExchangeOrderResult, Quote, Ticker


class ExchangeAdapter(ABC):
    @abstractmethod
    def get_ticker(self, asset: str) -> Ticker: ...

    @abstractmethod
    def get_quote(self, asset: str) -> Quote: ...

    @abstractmethod
    def get_ohlc(self, asset: str, interval: str, limit: int) -> list[Candle]: ...

    @abstractmethod
    def place_limit_order(
        self,
        asset: str,
        side: OrderType,
        price: Decimal,
        quantity: Decimal,
        post_only: bool,
    ) -> ExchangeOrderResult: ...

    @abstractmethod
    def get_order(self, exchange_order_id: str) -> ExchangeOrder: ...

    @abstractmethod
    def cancel_order(self, exchange_order_id: str) -> None: ...

    @abstractmethod
    def list_open_orders(self, asset: str | None = None) -> list[ExchangeOpenOrder]: ...

    @abstractmethod
    def get_available_base_balance(self, asset: str) -> Decimal: ...
