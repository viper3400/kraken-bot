from __future__ import annotations

from decimal import Decimal

from kraken_bot.app.config import BotConfig
from kraken_bot.domain.enums import MarketRegime
from kraken_bot.domain.models import Candle, MarketRegimeAnalysis
from kraken_bot.services.market_data_service import calculate_ema


def _slope_pct(values: list[Decimal], period: int) -> Decimal:
    if len(values) < period + 1:
        return Decimal("0")
    previous = calculate_ema(values[:-1], period)
    current = calculate_ema(values, period)
    if previous == 0:
        return Decimal("0")
    return ((current - previous) / previous) * Decimal("100")


class MarketRegimeService:
    def analyze(self, candles: list[Candle], config: BotConfig) -> MarketRegimeAnalysis:
        lookback = min(config.market_regime.lookback_candles, len(candles))
        window = candles[-lookback:]
        closes = [c.close for c in candles]
        low = min(c.low for c in window)
        high = max(c.high for c in window)
        if low == 0:
            band_width_pct = Decimal("0")
        else:
            band_width_pct = ((high - low) / low) * Decimal("100")
        ema20_slope_pct = _slope_pct(closes, config.trend_strategy.ema_fast)
        ema50_slope_pct = _slope_pct(closes, config.trend_strategy.ema_slow)

        sideways = (
            band_width_pct <= Decimal(str(config.market_regime.max_sideways_move_pct))
            and band_width_pct >= Decimal(str(config.market_regime.min_band_width_pct))
            and band_width_pct <= Decimal(str(config.market_regime.max_band_width_pct))
            and abs(ema20_slope_pct) <= Decimal(str(config.market_regime.ema_flatness_threshold_pct))
            and abs(ema50_slope_pct) <= Decimal(str(config.market_regime.ema_flatness_threshold_pct))
        )
        if sideways:
            return MarketRegimeAnalysis(
                regime=MarketRegime.SIDEWAYS,
                reason="Recent range is tight and EMA slopes are flat",
                band_lower=low,
                band_upper=high,
                band_width_pct=band_width_pct,
                ema20_slope_pct=ema20_slope_pct,
                ema50_slope_pct=ema50_slope_pct,
            )

        ema_fast = calculate_ema(closes, config.trend_strategy.ema_fast)
        ema_slow = calculate_ema(closes, config.trend_strategy.ema_slow)
        if ema_fast > ema_slow and ema20_slope_pct > 0 and ema50_slope_pct >= 0:
            return MarketRegimeAnalysis(
                regime=MarketRegime.TREND,
                reason="EMA alignment and slope support a trend regime",
                band_lower=low,
                band_upper=high,
                band_width_pct=band_width_pct,
                ema20_slope_pct=ema20_slope_pct,
                ema50_slope_pct=ema50_slope_pct,
            )

        return MarketRegimeAnalysis(
            regime=MarketRegime.NO_TRADE,
            reason="Neither sideways nor trend conditions are sufficiently clear",
            band_lower=low,
            band_upper=high,
            band_width_pct=band_width_pct,
            ema20_slope_pct=ema20_slope_pct,
            ema50_slope_pct=ema50_slope_pct,
        )
