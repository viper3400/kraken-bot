import pytest
from pydantic import ValidationError

from kraken_bot.app.config import BotConfig


def build_valid_config() -> dict:
    return {
        "bot": {"asset": "SOL/USD", "polling_interval_seconds": 30, "mode": "paper"},
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
        "trade": {"base_order_quantity": "0.06", "post_only": True},
        "kraken": {"api_key_env": "KRAKEN_API_KEY", "api_secret_env": "KRAKEN_API_SECRET"},
        "database": {"path": ":memory:"},
    }


def test_quote_amount_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        invalid = build_valid_config()
        invalid["trade"] = {"quote_amount": "0.06", "post_only": True}
        BotConfig.model_validate(invalid)

    assert "base_order_quantity" in str(exc_info.value)


def test_invalid_timeframe_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        invalid = build_valid_config()
        invalid["strategy"]["entry_timeframe"] = "30m"
        BotConfig.model_validate(invalid)

    assert "unsupported timeframe 30m" in str(exc_info.value)


def test_pullback_min_above_max_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        invalid = build_valid_config()
        invalid["strategy"]["pullback_min_pct"] = 2.0
        invalid["strategy"]["pullback_max_pct"] = 1.0
        BotConfig.model_validate(invalid)

    assert "pullback_min_pct must be less than or equal to pullback_max_pct" in str(exc_info.value)
