from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import Decision, TradeStatus
from kraken_bot.domain.models import Candle, MarketSnapshot, PortfolioState, Trade
from kraken_bot.strategies.ema_pullback_strategy import EmaPullbackStrategy


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
            "trade": {"base_order_quantity": "50.00", "post_only": True, "buy_fee_pct": 0.25, "sell_fee_pct": 0.25},
            "kraken": {"api_key_env": "KRAKEN_API_KEY", "api_secret_env": "KRAKEN_API_SECRET"},
            "database": {"path": ":memory:"},
            "logging": {"level": "INFO"},
        }
    )


def build_history() -> list[Candle]:
    base_time = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    previous = Candle(
        time=base_time,
        open=Decimal("100.6"),
        high=Decimal("100.7"),
        low=Decimal("99.2"),
        close=Decimal("100.1"),
        volume=Decimal("10"),
    )
    current = Candle(
        time=base_time + timedelta(minutes=1),
        open=Decimal("100.4"),
        high=Decimal("101.0"),
        low=Decimal("100.2"),
        close=Decimal("100.8"),
        volume=Decimal("12"),
    )
    return [previous, current]


def test_buy_decision_when_pullback_recovers() -> None:
    strategy = EmaPullbackStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 10, 1, tzinfo=timezone.utc),
        asset="XBT/EUR",
        price=Decimal("100.8"),
        ema20=Decimal("100.0"),
        ema50=Decimal("99.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    portfolio = PortfolioState("XBT/EUR", False, False, Decimal("1000"))
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.BUY
    assert '"trend": "15m"' in (decision.rule_states_json or "")
    assert '"entry": "5m"' in (decision.rule_states_json or "")


def test_hold_decision_when_open_order_exists() -> None:
    strategy = EmaPullbackStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 10, 1, tzinfo=timezone.utc),
        asset="XBT/EUR",
        price=Decimal("100.8"),
        ema20=Decimal("100.0"),
        ema50=Decimal("99.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    portfolio = PortfolioState("XBT/EUR", False, True, Decimal("1000"))
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.HOLD
    assert decision.reason.startswith("Open order already exists")


def test_sell_decision_for_take_profit() -> None:
    strategy = EmaPullbackStrategy()
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="XBT/EUR",
        quantity=Decimal("1"),
        buy_price=Decimal("100"),
        buy_time=now - timedelta(minutes=10),
        status=TradeStatus.OPEN,
        created_at=now - timedelta(minutes=10),
    )
    portfolio = PortfolioState("XBT/EUR", True, False, Decimal("1000"), open_trade=trade)
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="XBT/EUR",
        price=Decimal("100.9"),
        ema20=Decimal("100.2"),
        ema50=Decimal("99.7"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.SELL
    assert decision.reason == "Take profit reached"


def test_sell_decision_for_stop_loss() -> None:
    strategy = EmaPullbackStrategy()
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="XBT/EUR",
        quantity=Decimal("1"),
        buy_price=Decimal("100"),
        buy_time=now - timedelta(minutes=10),
        status=TradeStatus.OPEN,
        created_at=now - timedelta(minutes=10),
    )
    portfolio = PortfolioState("XBT/EUR", True, False, Decimal("1000"), open_trade=trade)
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="XBT/EUR",
        price=Decimal("99.3"),
        ema20=Decimal("100.2"),
        ema50=Decimal("99.7"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BEARISH",
    )
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.SELL
    assert decision.reason == "Stop loss reached"


def test_sell_decision_for_max_holding_time() -> None:
    strategy = EmaPullbackStrategy()
    now = datetime(2026, 6, 27, 12, 30, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="XBT/EUR",
        quantity=Decimal("1"),
        buy_price=Decimal("100"),
        buy_time=now - timedelta(minutes=121),
        status=TradeStatus.OPEN,
        created_at=now - timedelta(minutes=121),
    )
    portfolio = PortfolioState("XBT/EUR", True, False, Decimal("1000"), open_trade=trade)
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="XBT/EUR",
        price=Decimal("100.1"),
        ema20=Decimal("100.2"),
        ema50=Decimal("99.7"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.SELL
    assert decision.reason == "Maximum holding duration reached"


def test_trend_take_profit_respects_round_trip_fees() -> None:
    strategy = EmaPullbackStrategy()
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    trade = Trade(
        id="trade-1",
        asset="XBT/EUR",
        quantity=Decimal("1"),
        buy_price=Decimal("100"),
        buy_time=now - timedelta(minutes=10),
        status=TradeStatus.OPEN,
        created_at=now - timedelta(minutes=10),
    )
    portfolio = PortfolioState("XBT/EUR", True, False, Decimal("1000"), open_trade=trade)
    market = MarketSnapshot(
        id="1",
        time=now,
        asset="XBT/EUR",
        price=Decimal("100.40"),
        ema20=Decimal("100.2"),
        ema50=Decimal("99.7"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    decision = strategy.decide(market, build_history(), portfolio, build_config())
    assert decision.decision is Decision.HOLD


def test_hold_when_entry_confirmation_does_not_close_above_previous_high() -> None:
    strategy = EmaPullbackStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 10, 1, tzinfo=timezone.utc),
        asset="XBT/EUR",
        price=Decimal("100.8"),
        ema20=Decimal("100.0"),
        ema50=Decimal("99.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    history = [
        Candle(
            time=datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc),
            open=Decimal("100.6"),
            high=Decimal("100.9"),
            low=Decimal("99.2"),
            close=Decimal("100.7"),
            volume=Decimal("10"),
        ),
        Candle(
            time=datetime(2026, 6, 27, 10, 5, tzinfo=timezone.utc),
            open=Decimal("100.4"),
            high=Decimal("100.8"),
            low=Decimal("100.2"),
            close=Decimal("100.6"),
            volume=Decimal("12"),
        ),
    ]
    portfolio = PortfolioState("XBT/EUR", False, False, Decimal("1000"))
    decision = strategy.decide(market, history, portfolio, build_config())
    assert decision.decision is Decision.HOLD
    assert "prior high" in (decision.rule_states_json or "")


def test_hold_when_entry_history_too_short() -> None:
    strategy = EmaPullbackStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 10, 1, tzinfo=timezone.utc),
        asset="XBT/EUR",
        price=Decimal("100.8"),
        ema20=Decimal("100.0"),
        ema50=Decimal("99.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    history = [
        Candle(
            time=datetime(2026, 6, 27, 10, 5, tzinfo=timezone.utc),
            open=Decimal("100.4"),
            high=Decimal("101.0"),
            low=Decimal("100.2"),
            close=Decimal("100.8"),
            volume=Decimal("12"),
        )
    ]
    portfolio = PortfolioState("XBT/EUR", False, False, Decimal("1000"))
    decision = strategy.decide(market, history, portfolio, build_config())
    assert decision.decision is Decision.HOLD


def test_buy_when_confirmation_rebounds_above_pullback_range_but_prior_candle_pullback_was_valid() -> None:
    strategy = EmaPullbackStrategy()
    market = MarketSnapshot(
        id="1",
        time=datetime(2026, 6, 27, 10, 10, tzinfo=timezone.utc),
        asset="XBT/EUR",
        price=Decimal("101.6"),
        ema20=Decimal("100.0"),
        ema50=Decimal("99.0"),
        volatility=Decimal("0.5"),
        volume=Decimal("11"),
        trend_status="BULLISH",
    )
    history = [
        Candle(
            time=datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc),
            open=Decimal("101.0"),
            high=Decimal("100.6"),
            low=Decimal("99.0"),
            close=Decimal("99.8"),
            volume=Decimal("10"),
        ),
        Candle(
            time=datetime(2026, 6, 27, 10, 5, tzinfo=timezone.utc),
            open=Decimal("100.0"),
            high=Decimal("101.7"),
            low=Decimal("99.9"),
            close=Decimal("100.9"),
            volume=Decimal("12"),
        ),
    ]
    portfolio = PortfolioState("XBT/EUR", False, False, Decimal("1000"))

    decision = strategy.decide(market, history, portfolio, build_config())

    assert decision.decision is Decision.BUY
    assert decision.pullback == Decimal("1.00")
