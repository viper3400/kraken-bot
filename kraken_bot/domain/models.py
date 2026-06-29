from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from kraken_bot.domain.enums import Decision, MarketRegime, OrderStatus, OrderType, TradeStatus


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class MarketSnapshot:
    id: str
    time: datetime
    asset: str
    price: Decimal
    ema20: Decimal | None
    ema50: Decimal | None
    volatility: Decimal | None
    volume: Decimal | None
    trend_status: str
    regime: MarketRegime = MarketRegime.NO_TRADE
    band_lower: Decimal | None = None
    band_upper: Decimal | None = None
    band_width_pct: Decimal | None = None
    ema20_slope_pct: Decimal | None = None
    ema50_slope_pct: Decimal | None = None
    regime_reason: str | None = None


@dataclass(frozen=True)
class MarketRegimeAnalysis:
    regime: MarketRegime
    reason: str
    band_lower: Decimal | None = None
    band_upper: Decimal | None = None
    band_width_pct: Decimal | None = None
    ema20_slope_pct: Decimal | None = None
    ema50_slope_pct: Decimal | None = None


@dataclass(frozen=True)
class StrategyDecision:
    id: str
    time: datetime
    asset: str
    decision: Decision
    reason: str
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    price: Decimal | None = None
    pullback: Decimal | None = None
    comment: str | None = None
    config_snapshot: str | None = None
    regime: MarketRegime = MarketRegime.NO_TRADE
    strategy_name: str | None = None
    target_price: Decimal | None = None
    band_lower: Decimal | None = None
    band_upper: Decimal | None = None
    band_width_pct: Decimal | None = None
    rule_states_json: str | None = None


@dataclass(frozen=True)
class Trade:
    id: str
    asset: str
    quantity: Decimal
    buy_order_id: str | None = None
    sell_order_id: str | None = None
    buy_time: datetime | None = None
    sell_time: datetime | None = None
    buy_price: Decimal | None = None
    sell_price: Decimal | None = None
    buy_fee: Decimal = Decimal("0")
    sell_fee: Decimal = Decimal("0")
    gross_profit: Decimal | None = None
    total_fees: Decimal | None = None
    net_profit: Decimal | None = None
    holding_duration_seconds: int | None = None
    status: TradeStatus = TradeStatus.OPEN
    strategy_name: str | None = None
    regime: MarketRegime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class Order:
    id: str
    trade_id: str | None
    time: datetime
    type: OrderType
    price: Decimal
    quantity: Decimal
    status: OrderStatus
    post_only: bool
    exchange_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class OrderEvent:
    id: str
    order_id: str
    time: datetime
    status: OrderStatus
    raw_payload: str | None = None


@dataclass(frozen=True)
class PortfolioState:
    asset: str
    has_open_position: bool
    has_open_order: bool
    available_quote_balance: Decimal
    open_trade: Trade | None = None
    last_closed_trade: Trade | None = None


@dataclass(frozen=True)
class Ticker:
    asset: str
    price: Decimal
    time: datetime


@dataclass(frozen=True)
class Quote:
    asset: str
    bid: Decimal
    ask: Decimal
    price_increment: Decimal
    time: datetime


@dataclass(frozen=True)
class ExchangeOrderResult:
    exchange_order_id: str
    status: OrderStatus
    raw_payload: str | None = None


@dataclass(frozen=True)
class ExchangeOrder:
    exchange_order_id: str
    status: OrderStatus
    filled_quantity: Decimal
    average_price: Decimal | None
    fee: Decimal
    closed_at: datetime | None = None
    raw_payload: str | None = None


@dataclass(frozen=True)
class ExchangeOpenOrder:
    exchange_order_id: str
    asset: str
    type: OrderType
    status: str
    price: Decimal
    quantity: Decimal
    filled_quantity: Decimal
    opened_at: datetime | None
    description: str | None = None
    raw_payload: str | None = None


@dataclass(frozen=True)
class PostOnlyExecution:
    asset: str
    side: OrderType
    strategy_price: Decimal
    execution_price: Decimal | None
    bid: Decimal
    ask: Decimal
    can_place: bool
    reason: str | None = None


@dataclass(frozen=True)
class LogEntry:
    id: str
    time: datetime
    level: str
    service: str
    message: str
    context_json: str | None = None
