import json
import re
import tomllib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from kraken_bot.domain.enums import Decision, MarketRegime, OrderStatus, OrderType, TradeStatus
from kraken_bot.domain.models import Candle, ExchangeOpenOrder, MarketSnapshot, Order, StrategyDecision, Trade
from kraken_bot.persistence.repositories import SqliteRepositories
from kraken_bot.persistence.sqlite import SqlitePersistence
from kraken_bot.reporting.csv_export import CsvExporter
from kraken_bot.reporting.pnl import PnLCalculator
from kraken_bot.services.reporting_service import DefaultReportingService
from kraken_bot.services.status_service import StatusService
from kraken_bot.webui import _format_rule_detail, build_app, render_dashboard


def app_version() -> str:
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


class DummyExchange:
    def __init__(self) -> None:
        self.list_open_orders_calls = 0
        self.get_ohlc_calls = 0

    def list_open_orders(self, asset: str | None = None) -> list[ExchangeOpenOrder]:
        self.list_open_orders_calls += 1
        return [
            ExchangeOpenOrder(
                exchange_order_id="kraken-open-1",
                asset=asset or "XBT/EUR",
                type=OrderType.BUY,
                status="OPEN",
                price=Decimal("99.50"),
                quantity=Decimal("0.06"),
                filled_quantity=Decimal("0"),
                opened_at=datetime(2026, 6, 27, 11, 55, tzinfo=timezone.utc),
            )
        ]

    def get_quote(self, asset: str):
        raise NotImplementedError

    def get_ohlc(self, asset: str, interval: str, limit: int) -> list[Candle]:
        self.get_ohlc_calls += 1
        base = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)
        candles = []
        price = Decimal("99.50")
        for index in range(limit):
            price += Decimal("0.08")
            candles.append(
                Candle(
                    time=base + timedelta(minutes=15 * index),
                    open=price - Decimal("0.10"),
                    high=price + Decimal("0.22"),
                    low=price - Decimal("0.18"),
                    close=price,
                    volume=Decimal("10"),
                )
            )
        return candles


class DummyContainer:
    def __init__(self, repositories: SqliteRepositories) -> None:
        self.repositories = repositories
        self.reporting_service = DefaultReportingService(repositories, PnLCalculator(), CsvExporter())
        self.exchange = DummyExchange()
        self.config = type(
            "Config",
            (),
            {
                "bot": type(
                    "Bot",
                    (),
                    {"asset": "XBT/EUR", "mode": "paper", "polling_interval_seconds": 30},
                )(),
                "trade": type(
                    "Trade",
                    (),
                    {"cooldown_after_sell_minutes": 20},
                )(),
                "trend_strategy": type(
                    "TrendStrategy",
                    (),
                    {"trend_timeframe": "15m", "ema_fast": 20, "ema_slow": 50},
                )(),
            },
        )()


def build_repositories(tmp_path: Path) -> SqliteRepositories:
    repositories = SqliteRepositories(SqlitePersistence(tmp_path / "bot.sqlite"))
    now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    recent_sell_time = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    repositories.insert_market_snapshot(
        MarketSnapshot(
            id="snap-1",
            time=now,
            asset="XBT/EUR",
            price=Decimal("100.80"),
            ema20=Decimal("100.123456"),
            ema50=Decimal("99.987654"),
            volatility=Decimal("0.60"),
            volume=Decimal("42"),
            trend_status="BULLISH",
            band_lower=Decimal("98.111111"),
            band_upper=Decimal("101.999999"),
            band_width_pct=Decimal("1.357891"),
        )
    )
    repositories.insert_strategy_decision(
        StrategyDecision(
            id="dec-1",
            time=now,
            asset="XBT/EUR",
            decision=Decision.BUY,
            reason="Recovered from pullback",
            ema20=Decimal("100.00"),
            ema50=Decimal("99.00"),
            price=Decimal("100.80"),
            pullback=Decimal("0.80"),
            config_snapshot="{}",
            rule_states_json=json.dumps(
                {
                    "context": "trend",
                    "timeframes": {"regime": "15m", "trend": "15m", "entry": "5m"},
                    "rules": [
                        {
                            "label": "EMA trend bullish",
                            "state": "PASS",
                            "detail": "timeframe 15m: price 71.734567 / ema20 70.77571074593162710453145120 / ema50 70.80229906164694015395412320",
                        },
                        {
                            "label": "Pullback in range",
                            "state": "PASS",
                            "detail": "1.348328747264792302723827103% in [0.5, 1.5]",
                        },
                        {"label": "Recovery candle", "state": "FAIL", "detail": "timeframe 5m: current candle is green and closes above the prior high"},
                    ],
                }
            ),
        )
    )
    repositories.insert_trade(
        Trade(
            id="trade-1",
            asset="XBT/EUR",
            quantity=Decimal("1"),
            buy_order_id="order-1",
            sell_order_id="order-1-sell",
            buy_time=recent_sell_time - timedelta(minutes=10),
            sell_time=recent_sell_time,
            buy_price=Decimal("100.00"),
            sell_price=Decimal("100.80"),
            buy_fee=Decimal("0.16"),
            sell_fee=Decimal("0.16"),
            gross_profit=Decimal("0.80"),
            total_fees=Decimal("0.32"),
            net_profit=Decimal("0.48"),
            holding_duration_seconds=600,
            status=TradeStatus.CLOSED,
            strategy_name="trend_pullback",
            regime=MarketRegime.TREND,
            created_at=now,
        )
    )
    repositories.insert_order(
        Order(
            id="order-1",
            trade_id="trade-1",
            time=now,
            type=OrderType.BUY,
            price=Decimal("100.00"),
            quantity=Decimal("1"),
            status=OrderStatus.FILLED,
            post_only=True,
            exchange_id="ex-1",
            created_at=now,
        )
    )
    return repositories


def test_render_dashboard_contains_status_content(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = container.reporting_service
    app = build_app(container)
    assert status is not None

    collected = {}

    def start_response(status_line, headers):
        collected["status"] = status_line
        collected["headers"] = headers

    body = b"".join(app({"PATH_INFO": "/"}, start_response)).decode("utf-8")
    assert collected["status"] == "200 OK"
    assert "Kraken Bot Status" in body
    assert "Bot Loop" in body
    assert "Regime Reason:" in body
    assert "Decision Reason:" in body
    assert "Recovered from pullback" in body
    assert "100.80000000" in body or "100.80" in body
    assert "Live Market Chart" in body
    assert "Candles" in body
    assert "Band Width: 1.36%" in body
    assert "price-label" in body
    assert "price-grid" in body
    assert "id=\"metric-snapshot-time\"" in body or "id='metric-snapshot-time'" in body
    assert "id=\"metric-price\"" in body or "id='metric-price'" in body
    assert "id=\"metric-cooldown\"" in body or "id='metric-cooldown'" in body
    assert "id=\"metric-net-pnl\"" in body or "id='metric-net-pnl'" in body
    assert "id=\"rules-table-body\"" in body or "id='rules-table-body'" in body
    assert "id=\"strategy-rules-title\"" in body or "id='strategy-rules-title'" in body
    assert "id=\"open-trade-root\"" in body or "id='open-trade-root'" in body
    assert "id=\"recent-orders-root\"" in body or "id='recent-orders-root'" in body
    assert "id=\"exchange-open-orders-root\"" in body or "id='exchange-open-orders-root'" in body
    assert "id=\"recent-trades-root\"" in body or "id='recent-trades-root'" in body
    assert "id=\"recent-logs-root\"" in body or "id='recent-logs-root'" in body
    assert "refreshStatusFields(payload)" in body
    assert "renderRecentTrades(payload.recent_trades || [])" in body
    assert "price 71.73 / ema20 70.78 / ema50 70.80" in body
    assert "1.35% in [0.5, 1.5]" in body
    assert "70.77571074593162710453145120" not in body
    assert "Cooldown" in body
    assert "Active" in body


def test_api_status_returns_json(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    app = build_app(container)
    collected = {}

    def start_response(status_line, headers):
        collected["status"] = status_line
        collected["headers"] = headers

    body = b"".join(app({"PATH_INFO": "/api/status"}, start_response)).decode("utf-8")
    payload = json.loads(body)
    assert collected["status"] == "200 OK"
    assert payload["asset"] == "XBT/EUR"
    assert payload["app_version"] == app_version()
    assert payload["latest_strategy_decision"]["decision"] == "BUY"
    assert payload["report_metrics"]["net_profit"] == "0.48"
    assert payload["cooldown_status"]["configured_minutes"] == 20
    assert payload["cooldown_status"]["active"] is True
    assert 1 <= payload["cooldown_status"]["minutes_remaining"] <= 20
    assert payload["cooldown_status"]["last_sell_time"] is not None
    assert payload["runtime"]["polling_interval_seconds"] == 30
    assert payload["market_chart"]["timeframe"] == "15m"
    assert len(payload["market_chart"]["points"]) == 48
    assert container.exchange.list_open_orders_calls == 1
    assert container.exchange.get_ohlc_calls == 1


def test_render_dashboard_function_produces_html(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")
    dashboard = render_dashboard(status, "paper", {"running": True, "cycle_count": 3})
    assert "<html" in dashboard
    assert "Recent Trades" in dashboard
    assert "Running" in dashboard
    assert "Kraken Open Orders" in dashboard
    assert "kraken-open-1" in dashboard
    assert "Live Market Chart" in dashboard
    assert "price-label" in dashboard
    assert "Cooldown Left" in dashboard
    assert "Active" in dashboard
    assert f"App Version: <span id=\"dashboard-app-version\">{app_version()}</span>" in dashboard
    assert "<th>Asset</th>" not in dashboard
    assert "<th>Trade</th>" in dashboard
    assert "<th>Order</th>" in dashboard
    assert "Buy Total 100.16" in dashboard
    assert "Sell Total 100.64" in dashboard
    assert "Regime TREND" in dashboard
    assert "Strategy trend_pullback" in dashboard
    assert "Buy Order order-1" in dashboard
    assert "Sell Order order-1-sell" in dashboard
    assert "Notional 100.00" in dashboard


def test_render_dashboard_formats_runtime_timestamps_in_local_time(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")
    local_tzinfo = datetime.now().astimezone().tzinfo
    expected_timezone_label = getattr(local_tzinfo, "key", None) or local_tzinfo.tzname(None) or str(local_tzinfo)
    expected_snapshot_time = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    expected_snapshot_metric = f"Snapshot Time</div><div class='value'>{expected_snapshot_time}</div>"
    expected_started_at = datetime.fromisoformat("2026-06-27T14:55:25.210592+00:00").astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    expected_last_cycle_at = datetime.fromisoformat("2026-06-27T14:58:56.434151+00:00").astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    expected_trade_created_at = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    expected_order_time = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    dashboard = render_dashboard(
        status,
        "paper",
        {
            "running": True,
            "cycle_count": 3,
            "started_at": "2026-06-27T14:55:25.210592+00:00",
            "last_cycle_at": "2026-06-27T14:58:56.434151+00:00",
        },
    )

    assert "2026-06-27 14:55:25+00:00" not in dashboard
    assert "2026-06-27 14:58:56+00:00" not in dashboard
    assert expected_started_at in dashboard
    assert expected_last_cycle_at in dashboard
    assert "Snapshot Time</div>" in dashboard
    assert expected_snapshot_time in dashboard
    assert expected_trade_created_at in dashboard
    assert expected_order_time in dashboard
    assert "+02:00" not in dashboard
    assert "2026-06-27T12:00:00+00:00" not in dashboard
    assert re.search(r"Refreshed at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} · Timezone:", dashboard)
    assert f"Timezone: {expected_timezone_label}" in dashboard


def test_render_dashboard_trims_market_indicator_precision(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")

    dashboard = render_dashboard(status, "paper", {"running": True, "cycle_count": 3})

    assert "EMA Fast</div>" in dashboard
    assert ">100.12</div>" in dashboard
    assert "EMA Slow</div>" in dashboard
    assert ">99.99</div>" in dashboard
    assert "Band Width %</div>" in dashboard
    assert ">1.36</div>" in dashboard
    assert "100.123456" not in dashboard
    assert "99.987654" not in dashboard
    assert "1.357891" not in dashboard


def test_format_rule_detail_trims_embedded_precision_variants() -> None:
    detail = "price .123456 / drift -0.000123 / ema50 70.80229906164694015395412320 / tiny 1E-7"

    formatted = _format_rule_detail(detail)

    assert formatted == "price 0.12 / drift -0.00 / ema50 70.80 / tiny 0.00"


def test_format_rule_detail_preserves_unquantizable_scientific_notation() -> None:
    detail = "extreme move 1e999999 with fallback"

    formatted = _format_rule_detail(detail)

    assert formatted == detail


def test_api_status_includes_exchange_open_orders(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")

    assert len(status.exchange_open_orders) == 1
    assert status.exchange_open_orders[0].exchange_order_id == "kraken-open-1"
    assert status.exchange_open_orders_error is None


def test_api_status_reuses_cached_exchange_data_within_poll_window(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    app = build_app(container)

    def start_response(_status_line, _headers):
        return None

    first = b"".join(app({"PATH_INFO": "/api/status"}, start_response)).decode("utf-8")
    second = b"".join(app({"PATH_INFO": "/api/status"}, start_response)).decode("utf-8")

    assert json.loads(first)["market_chart"]["timeframe"] == "15m"
    assert json.loads(second)["market_chart"]["timeframe"] == "15m"
    assert container.exchange.list_open_orders_calls == 1
    assert container.exchange.get_ohlc_calls == 1


def test_dashboard_recent_tables_are_filtered_to_configured_asset(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    other_time = datetime(2026, 6, 27, 12, 5, tzinfo=timezone.utc)
    repositories.insert_trade(
        Trade(
            id="trade-2",
            asset="ETH/EUR",
            quantity=Decimal("2"),
            buy_time=other_time - timedelta(minutes=15),
            sell_time=other_time,
            buy_price=Decimal("200.00"),
            sell_price=Decimal("201.00"),
            buy_fee=Decimal("0.20"),
            sell_fee=Decimal("0.20"),
            gross_profit=Decimal("2.00"),
            total_fees=Decimal("0.40"),
            net_profit=Decimal("1.60"),
            holding_duration_seconds=900,
            status=TradeStatus.CLOSED,
            created_at=other_time,
        )
    )
    repositories.insert_order(
        Order(
            id="order-2",
            trade_id="trade-2",
            time=other_time,
            type=OrderType.SELL,
            price=Decimal("201.00"),
            quantity=Decimal("2"),
            status=OrderStatus.FILLED,
            post_only=True,
            exchange_id="ex-2",
            created_at=other_time,
        )
    )
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")
    dashboard = render_dashboard(status, "paper", {"running": True, "cycle_count": 3})

    assert [trade.id for trade in status.recent_trades] == ["trade-1"]
    assert [order.id for order in status.recent_orders] == ["order-1"]
    assert "trade-2" not in dashboard
    assert "order-2" not in dashboard
    assert "<th>Asset</th>" not in dashboard


def test_dashboard_client_chart_labels_use_local_time_formatter(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    status = StatusService(repositories, container.reporting_service, container.exchange, container.config).get_status("XBT/EUR")
    dashboard = render_dashboard(status, "paper", {"running": True, "cycle_count": 3})

    assert "function formatLocalDateTimeShort(value)" in dashboard
    assert 'formatLocalDateTimeShort(normalized[0].time)' in dashboard
    assert '.replace("T", " ").slice(0, 16)' not in dashboard


def test_initial_chart_render_formats_labels_in_local_time(tmp_path: Path) -> None:
    repositories = build_repositories(tmp_path)
    container = DummyContainer(repositories)
    app = build_app(container)
    collected = {}

    def start_response(status_line, headers):
        collected["status"] = status_line
        collected["headers"] = headers

    body = b"".join(app({"PATH_INFO": "/"}, start_response)).decode("utf-8")
    expected_chart_first_label = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    assert collected["status"] == "200 OK"
    assert expected_chart_first_label in body
    assert "2026-06-27T08:00:00+00:00" not in body
