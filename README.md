# Kraken Bot

Modular Python trading bot for Kraken spot trading.

This repository currently contains the V1 foundation:

- YAML-based configuration
- clean service boundaries
- SQLite persistence
- EMA pullback strategy
- portfolio and order guards for a single open position per asset
- PnL and CSV reporting helpers
- unit tests for core strategy and calculation logic

## Status

The project is implemented as a local Python package in [kraken_bot](./kraken_bot).

Current scope:

- public Kraken market data access
- strategy evaluation
- decision persistence
- trade and order persistence
- runner/container wiring
- unit test coverage for core rules

Current limitation:

- private Kraken order status and cancellation are still scaffolded

## Requirements

- Python 3.12+
- virtualenv recommended

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
.venv/bin/pip install -r requirements.txt
```

## Configuration

Default configuration lives in [config.yaml](./config.yaml).

Detailed strategy and parameter behavior is documented in [STRATEGY.md](./STRATEGY.md).

Important sections:

- `bot`: asset, polling interval, mode
- `market_regime`: regime detection thresholds
- `trend_strategy`: EMA pullback, separate trend/entry timeframes, and sell thresholds for trend mode
- `range_strategy`: sideways-band entry/exit and stop settings
- `trade`: base-asset order quantity, post-only flag, and fee assumptions
- `kraken`: API credentials or environment variable names for API credentials
- `database`: SQLite file path

Credentials can be provided directly in YAML or by referencing environment variable names:

```bash
export KRAKEN_API_KEY=...
export KRAKEN_API_SECRET=...
```

Example:

```yaml
kraken:
  api_key_env: KRAKEN_API_KEY
  api_secret_env: KRAKEN_API_SECRET
```

### Available Modes

The `bot.mode` setting currently accepts these values:

- `live`: intended for real Kraken execution against private API endpoints
- `paper`: intended for simulated trading without sending real exchange orders
- `backtest`: intended for replaying historical data

Current implementation status:

- `live` and `paper` both use the same runner flow today
- public market data fetching is implemented
- private Kraken `AddOrder` and `OpenOrders` calls are signed
- private Kraken order status and cancellation are still scaffolded
- `paper` is not yet a full simulation engine
- `backtest` is declared in config, but not implemented yet

So for the current codebase, `mode` is partly architectural and not yet a complete execution abstraction.

### Strategy Regimes

The bot now evaluates the market in two steps:

1. detect a market regime
2. run the matching strategy or stay out

Available regimes:

- `TREND`: routes into the EMA pullback strategy
- `SIDEWAYS`: routes into the range strategy
- `NO_TRADE`: no strategy is allowed to open a new trade

The sideways mode detects a trading band from recent candles and aims to:

- buy near the lower band
- sell near the upper band
- exit on stop loss if the range breaks down

## Run

```bash
.venv/bin/python -m kraken_bot.main --config config.yaml
```

Run continuously with the configured polling interval:

```bash
.venv/bin/python -m kraken_bot.main --config config.yaml --loop
```

The runner executes one bot cycle:

1. load config
2. load portfolio state
3. fetch regime candles
4. fetch trend candles
5. fetch entry candles
6. compute regime and trend indicators
7. persist market snapshot
8. evaluate strategy
9. persist strategy decision
10. place a BUY or SELL order when rules allow it

## Web UI

A slim read-only local status page is available:

```bash
.venv/bin/python -m kraken_bot.webui --config config.yaml --host 127.0.0.1 --port 8080
```

Then open `http://127.0.0.1:8080`.

For a temporary combined setup, you can host the UI and an in-process bot loop together:

```bash
.venv/bin/python -m kraken_bot.webui --config config.yaml --host 127.0.0.1 --port 8080 --with-bot-loop
```

That starts a background runner thread inside the UI process. It is intentionally loose coupling for development convenience, not the long-term architecture.

Available endpoints:

- `/`: HTML dashboard
- `/api/status`: JSON status payload

The UI reads from SQLite and also queries Kraken for live open orders. It shows:

- latest market snapshot
- latest strategy decision
- open trade
- live Kraken open orders
- recent orders and trades
- recent error logs
- aggregate PnL metrics

## Project Layout

```text
kraken_bot/
  app/
  domain/
  exchange/
  persistence/
  reporting/
  services/
  strategies/
tests/
doc/
config.yaml
requirements.txt
```

## Testing

Run the unit tests with:

```bash
.venv/bin/pytest
```

## Docker

The repository includes a `Dockerfile` and `docker-compose.yml` for running the bot with the config and SQLite database kept outside the image.

Create host directories for runtime files:

```bash
mkdir -p config data
cp config.yaml config/config.yaml
```

For Docker, set the database path in `config/config.yaml` to a path under `/data`, for example:

```yaml
database:
  path: "/data/bot.sqlite"
```

Then start the bot:

```bash
docker compose up --build
```

The compose file:

- runs the web UI on `0.0.0.0:8080`
- starts the background bot loop with `--with-bot-loop`
- exposes the dashboard at `http://127.0.0.1:8080`
- mounts `./config` to `/config` read-only
- mounts `./data` to `/data` read-write

## Notes On Design

- all money values use `decimal.Decimal`
- the Kraken adapter is isolated from strategy and PnL logic
- persistence is SQLite-based and append-oriented
- the strategy is testable without Kraken or SQLite

## Next Gaps

- implement signed Kraken private API order flow
- add integration tests for the full trade lifecycle
- complete restart/recovery synchronization from exchange plus SQLite
- persist trade close/PnL updates during filled sell execution
