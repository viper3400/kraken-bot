# Strategy Guide

This document explains how the bot decides whether to trade, which strategy it uses, and how the relevant values in [config.yaml](./config.yaml) change that behavior.

## Decision Flow

Each cycle follows this order:

1. Load recent candles for the configured regime, trend, and entry timeframes.
2. Detect the current market regime from the regime timeframe.
3. Build trend indicators from the trend timeframe.
4. Choose the matching strategy.
5. Return `BUY`, `SELL`, or `HOLD`.
6. If the decision is `BUY` or `SELL`, the runner places a post-only limit order at the strategy's target price.

The bot does not always look for a buy directly. It first decides whether the market is:

- `TREND`
- `SIDEWAYS`
- `NO_TRADE`

## Market Regime Detection

The regime detector lives in [kraken_bot/services/market_regime_service.py](./kraken_bot/services/market_regime_service.py).

### `SIDEWAYS`

The market is treated as sideways when:

- the recent price range is small enough
- the recent price range is not too small
- EMA20 slope is nearly flat
- EMA50 slope is nearly flat

In simple terms:

- price is moving inside a band
- the band is not exploding upward or downward
- the moving averages are not clearly trending

### `TREND`

If the market is not sideways, the detector checks for a trend:

- EMA20 is above EMA50
- EMA20 slope is positive
- EMA50 slope is non-negative

In simple terms:

- the fast average is above the slow average
- the averages are still pointing upward

### `NO_TRADE`

If the market is neither clearly sideways nor clearly trending, the bot does nothing.

This is intentional. `NO_TRADE` means:

- regime is unclear
- the bot should stay out

## Regime Config

These parameters are under `market_regime` in [config.yaml](./config.yaml).

### `timeframe`

Candles used only for market regime detection.

- default: `15m`
- can differ from the trend and entry timeframes
- affects sideways-band detection and EMA slope checks for regime classification

### `lookback_candles`

How many recent candles are used to measure the current trading environment.

- larger value: slower, more stable regime detection
- smaller value: faster, more reactive regime detection

### `max_sideways_move_pct`

Maximum allowed total range width for the market to still count as sideways.

- larger value: more markets qualify as sideways
- smaller value: only very tight ranges qualify

### `ema_flatness_threshold_pct`

How flat EMA20 and EMA50 must be to count as sideways.

- larger value: allows more slope while still calling it sideways
- smaller value: requires flatter averages

### `min_band_width_pct`

Minimum range width required before the bot considers a sideways band meaningful.

- larger value: ignores very narrow, noisy micro-ranges
- smaller value: allows tighter bands

### `max_band_width_pct`

Maximum range width allowed for sideways trading.

- larger value: wider ranges still count as sideways
- smaller value: only compact ranges count

## Trend Strategy: EMA Pullback

The trend strategy lives in [kraken_bot/strategies/ema_pullback_strategy.py](./kraken_bot/strategies/ema_pullback_strategy.py).

It is only used when the regime is `TREND`.

The trend strategy now works with two candle streams:

- `trend_timeframe`: used for EMA trend filter and pullback calculation
- `entry_timeframe`: used for the entry confirmation candle

### Trend Buy Logic

The bot considers a trend buy when all of these are true:

- there is no open position
- there is no open order
- EMA20 is above EMA50 on the trend timeframe
- price is above EMA20 on the trend timeframe
- the previous completed entry candle created a pullback inside the configured range
- the latest completed entry candle is green
- that entry candle closes above the previous entry candle high

In simple words:

- the market is trending upward
- the previous entry candle dipped enough to count as a valid pullback
- the dip is neither too small nor too deep
- the next entry candle confirms that price is bouncing again

### What “pullback” means

The pullback is not measured from the current confirmation price anymore.

Instead, the bot uses the low of the previous completed entry candle and compares that low to the trend EMA20.

This separates the setup from the confirmation:

- setup: a prior completed entry candle dips far enough away from EMA20
- confirmation: the next completed entry candle turns green and closes above the previous candle high

This is intentional. A valid pullback should not be invalidated just because the confirmation candle already bounced somewhat before the bot enters.

### Trend Sell Logic

If a trend trade is already open, the bot can sell when:

- take profit is reached
- stop loss is reached
- maximum holding time is reached

After a configurable amount of time, the bot reduces its take-profit target.

## Trend Config

These parameters are under `trend_strategy`.

### `ema_fast`

Fast EMA period, currently used as EMA20.

- smaller value: reacts faster to price changes
- larger value: smoother but slower

### `ema_slow`

Slow EMA period, currently used as EMA50.

- larger value: slower trend confirmation
- must be greater than `ema_fast`

### `trend_timeframe`

Candles used for EMA alignment and pullback calculation.

- default: `15m`
- supported values in this codebase: `1m`, `5m`, `15m`, `1h`

### `entry_timeframe`

Candles used for the entry confirmation pattern.

- default: `5m`
- supported values in this codebase: `1m`, `5m`, `15m`, `1h`
- the current refinement checks one completed green confirmation candle above the prior candle high

### `pullback_min_pct`

Minimum pullback size required to consider buying.

This threshold is applied to the low of the previous completed entry candle relative to EMA20, not to the current confirmation price.

- larger value: waits for deeper dips
- smaller value: allows shallower pullbacks

### `pullback_max_pct`

Maximum pullback size still considered acceptable.

This threshold is also applied to the low of the previous completed entry candle relative to EMA20.

- larger value: tolerates deeper pullbacks
- smaller value: avoids larger dips

### `take_profit_pct`

Initial profit target for trend trades.

- larger value: waits longer for profit
- smaller value: exits sooner

### `stop_loss_pct`

Maximum allowed loss before exiting a trend trade.

- larger value: gives trades more room
- smaller value: cuts losing trades faster

### `max_holding_minutes`

Maximum time a trend trade may stay open.

- larger value: allows longer holds
- smaller value: forces faster exits

### `reduce_target_after_minutes`

After this many minutes, the bot lowers its profit target.

- smaller value: becomes more eager to exit sooner
- larger value: keeps the original target longer

### `reduced_take_profit_pct`

The lower profit target used after `reduce_target_after_minutes`.

- smaller value: accepts smaller late profits
- larger value: still demands more upside

## Sideways Strategy: Range

The range strategy lives in [kraken_bot/strategies/range_strategy.py](./kraken_bot/strategies/range_strategy.py).

It is only used when the regime is `SIDEWAYS`.

The strategy uses the detected trading band:

- lower band = support area
- upper band = resistance area

### Range Buy Logic

The bot considers a range buy when:

- there is no open position
- there is no open order
- the regime is still `SIDEWAYS`
- price is near the lower band
- optional recovery candle confirmation passes

In simple words:

- market is moving inside a box
- price is near the bottom of the box
- price starts to bounce

### Range Sell Logic

If a range trade is already open, the bot can sell when:

- price reaches the upper-band exit zone
- stop loss is reached
- maximum holding time is reached

In simple words:

- sell near the top of the range
- exit early if the range breaks down
- do not hold sideways trades forever

## Range Config

These parameters are under `range_strategy`.

### `entry_buffer_pct`

How far above the lower band price may still be considered “near support”.

It also affects the limit-buy target price.

- larger value: more permissive entries, less precise support buying
- smaller value: stricter entries closer to the lower band

### `exit_buffer_pct`

How far below the upper band the bot aims to exit.

- larger value: sells earlier before resistance
- smaller value: waits closer to the top of the range

### `stop_loss_pct`

Maximum allowed loss on a range trade.

- larger value: gives the trade more room
- smaller value: exits breakdowns sooner

### `max_holding_minutes`

Maximum time a range trade may stay open.

- larger value: lets the range trade develop longer
- smaller value: exits stale range trades sooner

### `require_recovery_candle`

Whether the bot requires a simple bounce confirmation before entering near the lower band.

- `true`: safer, more selective entries
- `false`: more aggressive entries directly near support

## Trade Config

These parameters are under `trade`.

### `quote_amount`

How much quote currency to allocate per buy.

Examples:

- on `SOL/USD`, this is the USD amount
- on `XBT/EUR`, this is the EUR amount

The runner calculates:

`quantity = quote_amount / target_price`

### `post_only`

Whether orders must be submitted as post-only limit orders.

- `true`: do not cross the spread as a taker
- `false`: allow ordinary limit behavior

### `buy_fee_pct`

Expected buy-side fee in percent.

### `sell_fee_pct`

Expected sell-side fee in percent.

The bot uses both together as a round-trip fee floor:

`round_trip_fee_pct = buy_fee_pct + sell_fee_pct`

That fee floor is enforced for take-profit exits in both strategies.

Practical effect:

- a trend take profit will not trigger below the round-trip fee floor
- a range take-profit target will be pushed upward if the band exit would otherwise fall inside the fee zone

With:

- `buy_fee_pct: 0.25`
- `sell_fee_pct: 0.25`

the bot treats `0.50%` as the minimum gross profit needed before a profit-taking exit makes sense.

## Important Practical Notes

### Strategy choice happens before order placement

The strategy decides:

- whether to buy or sell
- which target price to use

The runner then places the order.

### Strategy parameters do not change Kraken behavior directly

The strategy config changes decision logic and target prices. It does not change exchange credentials, account balances, or order matching rules.

### Current execution model

The strategy layer is real. Exchange execution is still simplified.

That means:

- regime detection is implemented
- trend and range strategy decisions are implemented
- dashboard explanations are based on persisted rule snapshots
- private Kraken order execution is still not a full production integration yet
