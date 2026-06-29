from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import Decision, MarketRegime, TradeStatus
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, Trade
from kraken_bot.services.market_regime_service import MarketRegimeService
from kraken_bot.strategies.ema_pullback_strategy import EmaPullbackStrategy
from kraken_bot.strategies.range_strategy import RangeStrategy
from kraken_bot.strategies.regime_strategy import RegimeStrategy


def build_config() -> BotConfig:
    return BotConfig.model_validate(
        {
            "bot": {"asset": "SOL/USD", "polling_interval_seconds": 30, "mode": "paper"},
            "market_regime": {
                "timeframe": "15m",
                "lookback_candles": 30,
                "max_sideways_move_pct": 2.0,
                "ema_flatness_threshold_pct": 0.2,
                "min_band_width_pct": 0.5,
                "max_band_width_pct": 3.0,
            },
            "trend_strategy": {
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
            "range_strategy": {
                "name": "range",
                "entry_buffer_pct": 0.3,
                "exit_buffer_pct": 0.3,
                "stop_loss_pct": 0.6,
                "max_holding_minutes": 180,
                "require_recovery_candle": True,
            },
            "trade": {
                "base_order_quantity": "50.00",
                "post_only": True,
                "buy_fee_pct": 0.25,
                "sell_fee_pct": 0.25,
                "cooldown_after_sell_minutes": 20,
            },
            "kraken": {"api_key_env": "KRAKEN_API_KEY", "api_secret_env": "KRAKEN_API_SECRET"},
            "database": {"path": ":memory:"},
            "logging": {"level": "INFO"},
        }
    )


def build_sideways_candles(length: int = 60) -> list[Candle]:
    base = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    closes = [Decimal("149.2"), Decimal("148.9"), Decimal("149.4"), Decimal("149.0"), Decimal("149.3")] * 12
    candles: list[Candle] = []
    for index, close in enumerate(closes[:length]):
        candles.append(
            Candle(
                time=base + timedelta(minutes=index),
                open=close - Decimal("0.1"),
                high=close + Decimal("0.25"),
                low=close - Decimal("0.25"),
                close=close,
                volume=Decimal("10"),
            )
        )
    return candles


def build_trend_candles(length: int = 60) -> list[Candle]:
    base = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    candles: list[Candle] = []
    price = Decimal("100")
    for index in range(length):
        price += Decimal("0.3")
        candles.append(
            Candle(
                time=base + timedelta(minutes=index),
                open=price - Decimal("0.1"),
                high=price + Decimal("0.3"),
                low=price - Decimal("0.2"),
                close=price,
                volume=Decimal("10") + Decimal(index),
            )
        )
    return candles


def build_no_trade_candles(length: int = 60) -> list[Candle]:
    base = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    candles: list[Candle] = []
    price = Decimal("100")
    for index in range(length):
        direction = Decimal("1.5") if index % 2 == 0 else Decimal("-1.4")
        price += direction
        candles.append(
            Candle(
                time=base + timedelta(minutes=index),
                open=price - Decimal("0.2"),
                high=price + Decimal("0.9"),
                low=price - Decimal("0.9"),
                close=price,
                volume=Decimal("20"),
            )
        )
    return candles


def test_market_regime_detects_sideways() -> None:
    analysis = MarketRegimeService().analyze(build_sideways_candles(), build_config())
    assert analysis.regime is MarketRegime.SIDEWAYS
    assert analysis.band_lower is not None
    assert analysis.band_upper is not None


def test_market_regime_detects_trend() -> None:
    analysis = MarketRegimeService().analyze(build_trend_candles(), build_config())
    assert analysis.regime is MarketRegime.TREND


def test_market_regime_detects_no_trade() -> None:
    analysis = MarketRegimeService().analyze(build_no_trade_candles(), build_config())
    assert analysis.regime is MarketRegime.NO_TRADE


def test_range_strategy_buys_near_support() -> None:
    strategy = RangeStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        asset="SOL/USD",
        price=Decimal("148.35"),
        ema20=Decimal("149.1"),
        ema50=Decimal("149.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("42"),
        trend_status="FLAT",
        regime=MarketRegime.SIDEWAYS,
        band_lower=Decimal("148.00"),
        band_upper=Decimal("150.00"),
        band_width_pct=Decimal("1.35"),
        regime_reason="Recent range is tight and EMA slopes are flat",
    )
    decision = strategy.decide(
        market,
        build_sideways_candles(),
        PortfolioState("SOL/USD", False, False, Decimal("1000")),
        build_config(),
    )
    assert decision.decision is Decision.BUY
    assert decision.strategy_name == "range"
    assert decision.target_price is not None


def test_range_strategy_sells_near_upper_band() -> None:
    strategy = RangeStrategy()
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="SOL/USD",
        quantity=Decimal("1"),
        buy_price=Decimal("148.30"),
        buy_time=now - timedelta(minutes=20),
        status=TradeStatus.OPEN,
        strategy_name="range",
        regime=MarketRegime.SIDEWAYS,
        created_at=now - timedelta(minutes=20),
    )
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="SOL/USD",
        price=Decimal("149.70"),
        ema20=Decimal("149.1"),
        ema50=Decimal("149.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("42"),
        trend_status="FLAT",
        regime=MarketRegime.SIDEWAYS,
        band_lower=Decimal("148.00"),
        band_upper=Decimal("150.00"),
        band_width_pct=Decimal("1.35"),
        regime_reason="Recent range is tight and EMA slopes are flat",
    )
    decision = strategy.decide(
        market,
        build_sideways_candles(),
        PortfolioState("SOL/USD", True, False, Decimal("1000"), open_trade=trade),
        build_config(),
    )
    assert decision.decision is Decision.SELL


def test_range_strategy_does_not_take_profit_inside_fee_floor() -> None:
    strategy = RangeStrategy()
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="SOL/USD",
        quantity=Decimal("1"),
        buy_price=Decimal("148.30"),
        buy_time=now - timedelta(minutes=20),
        status=TradeStatus.OPEN,
        strategy_name="range",
        regime=MarketRegime.SIDEWAYS,
        created_at=now - timedelta(minutes=20),
    )
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="SOL/USD",
        price=Decimal("148.90"),
        ema20=Decimal("149.1"),
        ema50=Decimal("149.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("42"),
        trend_status="FLAT",
        regime=MarketRegime.SIDEWAYS,
        band_lower=Decimal("148.00"),
        band_upper=Decimal("149.00"),
        band_width_pct=Decimal("0.68"),
        regime_reason="Recent range is tight and EMA slopes are flat",
    )
    decision = strategy.decide(
        market,
        build_sideways_candles(),
        PortfolioState("SOL/USD", True, False, Decimal("1000"), open_trade=trade),
        build_config(),
    )
    assert decision.decision is Decision.HOLD
    assert decision.target_price is not None
    assert decision.target_price > Decimal("149.00")


def test_regime_strategy_routes_to_range_in_sideways_market() -> None:
    strategy = RegimeStrategy(EmaPullbackStrategy(), RangeStrategy())
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        asset="SOL/USD",
        price=Decimal("148.35"),
        ema20=Decimal("149.1"),
        ema50=Decimal("149.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("42"),
        trend_status="FLAT",
        regime=MarketRegime.SIDEWAYS,
        band_lower=Decimal("148.00"),
        band_upper=Decimal("150.00"),
        band_width_pct=Decimal("1.35"),
        regime_reason="Recent range is tight and EMA slopes are flat",
    )
    decision = strategy.decide(
        market,
        build_sideways_candles(),
        PortfolioState("SOL/USD", False, False, Decimal("1000")),
        build_config(),
    )
    assert decision.strategy_name == "range"


def test_range_strategy_holds_during_sell_cooldown() -> None:
    strategy = RangeStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 12, 15, tzinfo=timezone.utc),
        asset="SOL/USD",
        price=Decimal("148.35"),
        ema20=Decimal("149.1"),
        ema50=Decimal("149.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("42"),
        trend_status="FLAT",
        regime=MarketRegime.SIDEWAYS,
        band_lower=Decimal("148.00"),
        band_upper=Decimal("150.00"),
        band_width_pct=Decimal("1.35"),
        regime_reason="Recent range is tight and EMA slopes are flat",
    )
    closed_trade = Trade(
        id="trade-closed-1",
        asset="SOL/USD",
        quantity=Decimal("1"),
        buy_price=Decimal("148.10"),
        sell_price=Decimal("149.60"),
        buy_time=datetime(2026, 6, 27, 11, 30, tzinfo=timezone.utc),
        sell_time=datetime(2026, 6, 27, 12, 5, tzinfo=timezone.utc),
        status=TradeStatus.CLOSED,
        strategy_name="range",
        regime=MarketRegime.SIDEWAYS,
        created_at=datetime(2026, 6, 27, 11, 30, tzinfo=timezone.utc),
    )

    decision = strategy.decide(
        market,
        build_sideways_candles(),
        PortfolioState("SOL/USD", False, False, Decimal("1000"), last_closed_trade=closed_trade),
        build_config(),
    )

    assert decision.decision is Decision.HOLD
    assert "Sell cooldown inactive" in (decision.rule_states_json or "")
    assert "10 min since sell vs cooldown 20" in (decision.rule_states_json or "")
