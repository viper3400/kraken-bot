from pathlib import Path

from kraken_bot.app.config import BotConfig
from kraken_bot.app.demo_seed import DemoDataSeeder
from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.persistence.sqlite import SqlitePersistence


def build_config(tmp_path: Path, demo_enabled: bool = True) -> BotConfig:
    return BotConfig.model_validate(
        {
            "bot": {
                "asset": "XBT/EUR",
                "polling_interval_seconds": 30,
                "mode": "demo" if demo_enabled else "paper",
            },
            "market_regime": {"timeframe": "15m"},
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
            "trade": {"base_order_quantity": "0.06", "post_only": True, "cooldown_after_sell_minutes": 20},
            "kraken": (
                {}
                if demo_enabled
                else {"api_key_env": "KRAKEN_API_KEY", "api_secret_env": "KRAKEN_API_SECRET"}
            ),
            "database": {"path": str(tmp_path / "bot.sqlite")},
        }
    )


def test_demo_seed_populates_empty_database(tmp_path: Path) -> None:
    config = build_config(tmp_path, demo_enabled=True)
    repositories = SqliteRepositories(SqlitePersistence(tmp_path / "bot.sqlite"))

    DemoDataSeeder(repositories, config).seed_if_enabled()

    assert repositories.has_any_dashboard_data() is True
    assert repositories.get_latest_market_snapshot("XBT/EUR") is not None
    assert repositories.get_latest_strategy_decision("XBT/EUR") is not None
    assert repositories.get_open_trade("XBT/EUR") is not None
    assert len(repositories.list_recent_trades()) == 2
    assert len(repositories.list_recent_orders()) == 3
    assert len(repositories.list_recent_logs()) == 2


def test_demo_seed_is_skipped_when_database_already_has_data(tmp_path: Path) -> None:
    config = build_config(tmp_path, demo_enabled=True)
    repositories = SqliteRepositories(SqlitePersistence(tmp_path / "bot.sqlite"))

    DemoDataSeeder(repositories, config).seed_if_enabled()
    first_trade_ids = [trade.id for trade in repositories.list_trades()]

    DemoDataSeeder(repositories, config).seed_if_enabled()
    second_trade_ids = [trade.id for trade in repositories.list_trades()]

    assert second_trade_ids == first_trade_ids


def test_demo_seed_is_skipped_when_demo_mode_disabled(tmp_path: Path) -> None:
    config = build_config(tmp_path, demo_enabled=False)
    repositories = SqliteRepositories(SqlitePersistence(tmp_path / "bot.sqlite"))

    DemoDataSeeder(repositories, config).seed_if_enabled()

    assert repositories.has_any_dashboard_data() is False
