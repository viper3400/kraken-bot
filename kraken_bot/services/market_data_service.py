from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from statistics import mean
from uuid import uuid4

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import MarketRegime
from kraken_bot.domain.models import Candle, MarketRegimeAnalysis, MarketSnapshot
from kraken_bot.exchange.base import ExchangeAdapter


def calculate_ema(values: list[Decimal], period: int) -> Decimal:
    if len(values) < period:
        raise ValueError("not enough values for EMA")
    multiplier = Decimal("2") / Decimal(period + 1)
    ema = sum(values[:period]) / Decimal(period)
    for price in values[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


class MarketDataService(ABC):
    @abstractmethod
    def get_current_price(self, asset: str) -> Decimal: ...

    @abstractmethod
    def get_candles(self, asset: str, interval: str, limit: int) -> list[Candle]: ...

    @abstractmethod
    def get_market_snapshot(
        self,
        asset: str,
        candles: list[Candle],
        now: datetime,
        regime_analysis: MarketRegimeAnalysis | None = None,
    ) -> MarketSnapshot: ...


class DefaultMarketDataService(MarketDataService):
    def __init__(self, exchange: ExchangeAdapter, config: BotConfig) -> None:
        self.exchange = exchange
        self.config = config

    def get_current_price(self, asset: str) -> Decimal:
        return self.exchange.get_ticker(asset).price

    def get_candles(self, asset: str, interval: str, limit: int) -> list[Candle]:
        return self.exchange.get_ohlc(asset, interval, limit)

    def get_market_snapshot(
        self,
        asset: str,
        candles: list[Candle],
        now: datetime,
        regime_analysis: MarketRegimeAnalysis | None = None,
    ) -> MarketSnapshot:
        closes = [candle.close for candle in candles]
        ema_fast = calculate_ema(closes, self.config.strategy.ema_fast)
        ema_slow = calculate_ema(closes, self.config.strategy.ema_slow)
        price = closes[-1]
        recent_ranges = [candle.high - candle.low for candle in candles[-5:]]
        volatility = sum(recent_ranges) / Decimal(len(recent_ranges))
        volume = Decimal(str(mean([float(c.volume) for c in candles[-5:]])))
        trend_status = "BULLISH" if ema_fast > ema_slow else "BEARISH"
        return MarketSnapshot(
            id=str(uuid4()),
            time=now,
            asset=asset,
            price=price,
            ema20=ema_fast,
            ema50=ema_slow,
            volatility=volatility,
            volume=volume,
            trend_status=trend_status,
            regime=regime_analysis.regime if regime_analysis else MarketRegime.NO_TRADE,
            band_lower=regime_analysis.band_lower if regime_analysis else None,
            band_upper=regime_analysis.band_upper if regime_analysis else None,
            band_width_pct=regime_analysis.band_width_pct if regime_analysis else None,
            ema20_slope_pct=regime_analysis.ema20_slope_pct if regime_analysis else None,
            ema50_slope_pct=regime_analysis.ema50_slope_pct if regime_analysis else None,
            regime_reason=regime_analysis.reason if regime_analysis else None,
        )
