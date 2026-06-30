from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h"})


class BotSection(BaseModel):
    asset: str
    polling_interval_seconds: int = Field(gt=0)
    mode: Literal["live", "paper", "backtest", "demo"] = "paper"


class MarketRegimeSection(BaseModel):
    timeframe: str = "15m"
    lookback_candles: int = Field(default=30, gt=2)
    max_sideways_move_pct: float = Field(default=2.0, ge=0)
    ema_flatness_threshold_pct: float = Field(default=0.2, ge=0)
    min_band_width_pct: float = Field(default=0.5, ge=0)
    max_band_width_pct: float = Field(default=3.0, ge=0)

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        if value not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"unsupported timeframe {value}")
        return value


class TrendStrategySection(BaseModel):
    name: Literal["ema_pullback"] = "ema_pullback"
    trend_timeframe: str = "15m"
    entry_timeframe: str = "5m"
    require_close_above_previous_high: bool = True
    ema_fast: int = Field(gt=0)
    ema_slow: int = Field(gt=0)
    pullback_min_pct: float = Field(ge=0)
    pullback_max_pct: float = Field(ge=0)
    take_profit_pct: float = Field(ge=0)
    stop_loss_pct: float = Field(ge=0)
    max_holding_minutes: int = Field(gt=0)
    reduce_target_after_minutes: int = Field(ge=0)
    reduced_take_profit_pct: float = Field(ge=0)

    @field_validator("ema_slow")
    @classmethod
    def validate_windows(cls, value: int, info) -> int:
        if "ema_fast" in info.data and value <= info.data["ema_fast"]:
            raise ValueError("ema_slow must be greater than ema_fast")
        return value

    @field_validator("trend_timeframe", "entry_timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        if value not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"unsupported timeframe {value}")
        return value

    @model_validator(mode="after")
    def validate_pullback_range(self) -> "TrendStrategySection":
        if self.pullback_min_pct > self.pullback_max_pct:
            raise ValueError("pullback_min_pct must be less than or equal to pullback_max_pct")
        return self


class RangeStrategySection(BaseModel):
    name: Literal["range"] = "range"
    entry_buffer_pct: float = Field(default=0.3, ge=0)
    exit_buffer_pct: float = Field(default=0.3, ge=0)
    stop_loss_pct: float = Field(default=0.6, ge=0)
    max_holding_minutes: int = Field(default=180, gt=0)
    require_recovery_candle: bool = True


class TradeSection(BaseModel):
    base_order_quantity: str
    post_only: bool = True
    buy_fee_pct: float = Field(default=0.25, ge=0)
    sell_fee_pct: float = Field(default=0.25, ge=0)
    cooldown_after_sell_minutes: int = Field(default=0, ge=0)

    @property
    def round_trip_fee_pct(self) -> float:
        return self.buy_fee_pct + self.sell_fee_pct


class KrakenSection(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    api_key_env: str | None = None
    api_secret_env: str | None = None
    base_url: str = "https://api.kraken.com"


class DatabaseSection(BaseModel):
    path: str


class LoggingSection(BaseModel):
    level: str = "INFO"


class BotConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    bot: BotSection
    market_regime: MarketRegimeSection = MarketRegimeSection()
    trend_strategy: TrendStrategySection
    range_strategy: RangeStrategySection = RangeStrategySection()
    trade: TradeSection
    kraken: KrakenSection
    database: DatabaseSection
    logging: LoggingSection = LoggingSection()

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_strategy_block(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "trend_strategy" not in data and "strategy" in data:
                data["trend_strategy"] = data.pop("strategy")
        return data

    @model_validator(mode="after")
    def validate_kraken_credentials(self) -> "BotConfig":
        direct_pair = bool(self.kraken.api_key) == bool(self.kraken.api_secret)
        env_pair = bool(self.kraken.api_key_env) == bool(self.kraken.api_secret_env)
        if not direct_pair:
            raise ValueError("kraken.api_key and kraken.api_secret must be set together")
        if not env_pair:
            raise ValueError("kraken.api_key_env and kraken.api_secret_env must be set together")
        if self.bot.mode == "demo":
            return self
        if not (self.kraken.api_key and self.kraken.api_secret) and not (
            self.kraken.api_key_env and self.kraken.api_secret_env
        ):
            raise ValueError("configure Kraken credentials via api_key/api_secret or api_key_env/api_secret_env")
        return self

    @classmethod
    def load(cls, path: str | Path) -> "BotConfig":
        config_path = Path(path).resolve()
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            database = raw.get("database")
            if isinstance(database, dict):
                db_path = database.get("path")
                if isinstance(db_path, str) and db_path != ":memory:":
                    candidate = Path(db_path)
                    if not candidate.is_absolute():
                        database["path"] = str((config_path.parent / candidate).resolve())
        return cls.model_validate(raw)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True)

    def config_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def strategy(self) -> TrendStrategySection:
        return self.trend_strategy
