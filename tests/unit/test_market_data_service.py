from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.models import Candle
from kraken_bot.services.market_data_service import calculate_ema, DefaultMarketDataService


class DummyExchange:
    def get_ticker(self, asset: str):
        raise NotImplementedError

    def get_quote(self, asset: str):
        raise NotImplementedError

    def get_ohlc(self, asset: str, interval: str, limit: int):
        raise NotImplementedError

    def get_order(self, exchange_order_id: str):
        raise NotImplementedError

    def cancel_order(self, exchange_order_id: str) -> None:
        raise NotImplementedError

    def place_limit_order(self, asset: str, side, price, quantity, post_only: bool):
        raise NotImplementedError

    def list_open_orders(self, asset: str | None = None):
        return []

    def get_available_base_balance(self, asset: str):
        raise NotImplementedError


def build_config() -> BotConfig:
    return BotConfig.model_validate(
        {
            "bot": {"asset": "XBT/EUR", "polling_interval_seconds": 30, "mode": "paper"},
            "market_regime": {"timeframe": "15m"},
            "strategy": {
                "name": "ema_pullback",
                "trend_timeframe": "15m",
                "entry_timeframe": "5m",
                "require_close_above_previous_high": True,
                "ema_fast": 20,
                "ema_slow": 50,
                "pullback_min_pct": 0.5,
                "pullback_max_pct": 1.5,
                "take_profit_pct": 0.8,
                "stop_loss_pct": 0.6,
                "max_holding_minutes": 120,
                "reduce_target_after_minutes": 60,
                "reduced_take_profit_pct": 0.3,
            },
            "trade": {"base_order_quantity": "50.00", "post_only": True, "cooldown_after_sell_minutes": 20},
            "kraken": {"api_key_env": "KRAKEN_API_KEY", "api_secret_env": "KRAKEN_API_SECRET"},
            "database": {"path": ":memory:"},
            "logging": {"level": "INFO"},
        }
    )


def build_candles(length: int = 55) -> list[Candle]:
    base_time = datetime(2026, 6, 27, tzinfo=timezone.utc)
    candles = []
    for idx in range(length):
        price = Decimal("100") + Decimal(idx) * Decimal("0.2")
        candles.append(
            Candle(
                time=base_time + timedelta(minutes=idx),
                open=price,
                high=price + Decimal("0.3"),
                low=price - Decimal("0.4"),
                close=price + Decimal("0.1"),
                volume=Decimal("10") + Decimal(idx),
            )
        )
    return candles


def test_calculate_ema_returns_decimal() -> None:
    values = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104")]
    ema = calculate_ema(values, period=3)
    assert ema == Decimal("103.0")


def test_market_snapshot_calculates_indicators() -> None:
    service = DefaultMarketDataService(DummyExchange(), build_config())
    candles = build_candles()
    snapshot = service.get_market_snapshot("XBT/EUR", candles, candles[-1].time)
    assert snapshot.asset == "XBT/EUR"
    assert snapshot.ema20 is not None
    assert snapshot.ema50 is not None
    assert snapshot.trend_status == "BULLISH"
