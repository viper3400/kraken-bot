from __future__ import annotations

from pathlib import Path

from kraken_bot.app.config import BotConfig
from kraken_bot.app.demo_seed import DemoDataSeeder
from kraken_bot.exchange.kraken_adapter import KrakenAdapter
from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.persistence.sqlite import SqlitePersistence
from kraken_bot.reporting.csv_export import CsvExporter
from kraken_bot.reporting.pnl import PnLCalculator
from kraken_bot.services.market_data_service import DefaultMarketDataService
from kraken_bot.services.market_regime_service import MarketRegimeService
from kraken_bot.services.order_service import DefaultOrderService
from kraken_bot.services.persistence_service import DefaultPersistenceService
from kraken_bot.services.portfolio_service import DefaultPortfolioService
from kraken_bot.services.reporting_service import DefaultReportingService
from kraken_bot.services.strategy_service import DefaultStrategyService
from kraken_bot.strategies.ema_pullback_strategy import EmaPullbackStrategy
from kraken_bot.strategies.range_strategy import RangeStrategy
from kraken_bot.strategies.regime_strategy import RegimeStrategy


class Container:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.sqlite = SqlitePersistence(Path(config.database.path))
        self.repositories = SqliteRepositories(self.sqlite)
        DemoDataSeeder(self.repositories, config).seed_if_enabled()
        self.exchange = KrakenAdapter(
            base_url=config.kraken.base_url,
            api_key_env=config.kraken.api_key_env,
            api_secret_env=config.kraken.api_secret_env,
            api_key=config.kraken.api_key,
            api_secret=config.kraken.api_secret,
        )
        self.market_data_service = DefaultMarketDataService(self.exchange, self.config)
        self.market_regime_service = MarketRegimeService()
        self.persistence_service = DefaultPersistenceService(self.repositories)
        self.portfolio_service = DefaultPortfolioService(self.repositories)
        self.order_service = DefaultOrderService(
            exchange=self.exchange,
            repositories=self.repositories,
            post_only=config.trade.post_only,
        )
        self.strategy_service = DefaultStrategyService(
            RegimeStrategy(
                trend_strategy=EmaPullbackStrategy(),
                range_strategy=RangeStrategy(),
            )
        )
        self.reporting_service = DefaultReportingService(
            repositories=self.repositories,
            pnl_calculator=PnLCalculator(),
            csv_exporter=CsvExporter(),
        )
