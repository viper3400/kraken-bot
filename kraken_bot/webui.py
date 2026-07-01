from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import cache
import html
import json
from http import HTTPStatus
import mimetypes
from pathlib import Path
import re
import tomllib
from wsgiref.simple_server import make_server

from jinja2 import Environment, FileSystemLoader, select_autoescape

from kraken_bot.app.config import BotConfig
from kraken_bot.app.container import Container
from kraken_bot.app.runner import BotLoopController, BotRunner
from kraken_bot.exchange.kraken_adapter import KrakenApiError
from kraken_bot.services.market_data_service import calculate_ema
from kraken_bot.services.status_service import BotStatus, StatusService

_RULE_DETAIL_NUMBER_PATTERN = re.compile(r"(?<![\w.])[-+]?(?:\d+\.\d{3,}|\.\d{3,}|\d+(?:\.\d+)?[eE][-+]?\d+)")
_PACKAGE_ROOT = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_ROOT / "templates"
_STATIC_DIR = _PACKAGE_ROOT / "static"


@cache
def _app_version() -> str:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return "unknown"
    project = payload.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return "unknown"


@cache
def _template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _format_local_datetime(value: object) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
    else:
        return str(value)

    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_local_datetime_short(value: object) -> str:
    formatted = _format_local_datetime(value)
    return formatted[:-3] if len(formatted) >= 16 else formatted


def _format_duration_seconds(value: object) -> str:
    if value in (None, ""):
        return "-"
    try:
        total_seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _format_money_total(price: Decimal | None, quantity: Decimal, fee: Decimal | None = None, *, subtract_fee: bool = False) -> str:
    if price is None:
        return "-"
    total = price * quantity
    if fee is not None:
        total = total - fee if subtract_fee else total + fee
    return StatusService.format_decimal(total, places=4)


def _local_timezone_label() -> str:
    tzinfo = datetime.now().astimezone().tzinfo
    if tzinfo is None:
        return "local time"
    key = getattr(tzinfo, "key", None)
    if key:
        return str(key)
    return tzinfo.tzname(None) or str(tzinfo)


def _metric_id_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value or "unknown")


def _format_rule_detail(detail: str) -> str:
    def replace_decimal(match: re.Match[str]) -> str:
        raw_value = match.group(0)
        try:
            value = Decimal(raw_value)
            return format(value.quantize(Decimal("0.01")), "f")
        except InvalidOperation:
            return raw_value

    return _RULE_DETAIL_NUMBER_PATTERN.sub(replace_decimal, detail)


def _strategy_snapshot(status: BotStatus) -> dict[str, object]:
    decision = status.latest_strategy_decision
    if decision and decision.rule_states_json:
        try:
            payload = json.loads(decision.rule_states_json)
            return {
                "context": payload.get("context", "decision"),
                "timeframes": payload.get("timeframes", {}),
                "rules": [
                    (rule.get("label", "Rule"), rule.get("state", "UNKNOWN"), rule.get("detail", ""))
                    for rule in payload.get("rules", [])
                ],
            }
        except json.JSONDecodeError:
            pass

    return {
        "context": "decision",
        "timeframes": {},
        "rules": [("Rule details", "INFO", "No persisted rule breakdown available for this decision")],
    }


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _build_market_chart(container: Container, latest_snapshot) -> dict[str, object]:
    trend_config = getattr(container.config, "trend_strategy", getattr(container.config, "strategy", None))
    timeframe = getattr(trend_config, "trend_timeframe", "5m")
    ema_fast = getattr(trend_config, "ema_fast", 20)
    ema_slow = getattr(trend_config, "ema_slow", 50)
    candle_limit = max(48, int(ema_fast), int(ema_slow) + 20)
    asset = container.config.bot.asset

    try:
        candles = container.exchange.get_ohlc(asset, timeframe, candle_limit)
    except (KrakenApiError, ValueError, AttributeError) as exc:
        return {"asset": asset, "timeframe": timeframe, "candles": [], "error": str(exc)}

    closes: list[Decimal] = []
    points: list[dict[str, object]] = []
    for candle in candles:
        closes.append(candle.close)
        ema_fast_value = calculate_ema(closes, ema_fast) if len(closes) >= ema_fast else None
        ema_slow_value = calculate_ema(closes, ema_slow) if len(closes) >= ema_slow else None
        points.append(
            {
                "time": candle.time.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "ema_fast": ema_fast_value,
                "ema_slow": ema_slow_value,
            }
        )

    return {
        "asset": asset,
        "timeframe": timeframe,
        "ema_fast_period": ema_fast,
        "ema_slow_period": ema_slow,
        "band_lower": latest_snapshot.band_lower if latest_snapshot else None,
        "band_upper": latest_snapshot.band_upper if latest_snapshot else None,
        "band_width_pct": latest_snapshot.band_width_pct if latest_snapshot else None,
        "points": points,
        "error": None,
    }


def _render_market_chart(chart_payload: dict[str, object] | None) -> str:
    if not chart_payload:
        return "<div class='empty'>No chart data available</div>"
    if chart_payload.get("error"):
        return f"<div class='empty'>Chart unavailable: {html.escape(str(chart_payload['error']))}</div>"

    raw_points = chart_payload.get("points", [])
    if not isinstance(raw_points, list) or not raw_points:
        return "<div class='empty'>No chart data available</div>"

    points = []
    for raw in raw_points:
        if not isinstance(raw, dict):
            continue
        open_value = _decimal_or_none(raw.get("open"))
        high_value = _decimal_or_none(raw.get("high"))
        low_value = _decimal_or_none(raw.get("low"))
        close_value = _decimal_or_none(raw.get("close"))
        if None in (open_value, high_value, low_value, close_value):
            continue
        points.append(
            {
                "time": str(raw.get("time", "")),
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "ema_fast": _decimal_or_none(raw.get("ema_fast")),
                "ema_slow": _decimal_or_none(raw.get("ema_slow")),
            }
        )
    if not points:
        return "<div class='empty'>No chart data available</div>"

    width = 960
    height = 320
    left = 18
    right = 18
    top = 16
    bottom = 34
    inner_width = width - left - right
    inner_height = height - top - bottom
    band_lower = _decimal_or_none(chart_payload.get("band_lower"))
    band_upper = _decimal_or_none(chart_payload.get("band_upper"))

    values = [point["high"] for point in points] + [point["low"] for point in points]
    if band_lower is not None:
        values.append(band_lower)
    if band_upper is not None:
        values.append(band_upper)
    high_bound = max(values)
    low_bound = min(values)
    if high_bound == low_bound:
        high_bound += Decimal("1")
        low_bound -= Decimal("1")
    padding = (high_bound - low_bound) * Decimal("0.08")
    high_bound += padding
    low_bound -= padding
    value_range = high_bound - low_bound

    def x_pos(index: int) -> float:
        if len(points) == 1:
            return left + inner_width / 2
        return left + (inner_width * index / (len(points) - 1))

    def y_pos(value: Decimal) -> float:
        normalized = float((value - low_bound) / value_range)
        return top + inner_height - (normalized * inner_height)

    def path_for(series_key: str) -> str:
        segments = []
        for index, point in enumerate(points):
            value = point.get(series_key)
            if value is None:
                continue
            command = "M" if not segments else "L"
            segments.append(f"{command}{x_pos(index):.2f},{y_pos(value):.2f}")
        return " ".join(segments)

    price_ticks: list[tuple[Decimal, float]] = []
    for step in range(5):
        ratio = Decimal(step) / Decimal("4")
        value = high_bound - (value_range * ratio)
        price_ticks.append((value, y_pos(value)))

    candles_markup = []
    body_width = max(4.0, min(16.0, inner_width / max(len(points) * 1.8, 2)))
    for index, point in enumerate(points):
        x = x_pos(index)
        open_y = y_pos(point["open"])
        close_y = y_pos(point["close"])
        high_y = y_pos(point["high"])
        low_y = y_pos(point["low"])
        body_top = min(open_y, close_y)
        body_height = max(abs(open_y - close_y), 1.5)
        candle_class = "candle-up" if point["close"] >= point["open"] else "candle-down"
        candles_markup.append(
            f"<line class='candle-wick {candle_class}' x1='{x:.2f}' y1='{high_y:.2f}' x2='{x:.2f}' y2='{low_y:.2f}' />"
            f"<rect class='candle-body {candle_class}' x='{x - body_width / 2:.2f}' y='{body_top:.2f}' "
            f"width='{body_width:.2f}' height='{body_height:.2f}' rx='1.5' />"
        )

    band_markup = ""
    if band_lower is not None and band_upper is not None:
        band_top = y_pos(max(band_lower, band_upper))
        band_bottom = y_pos(min(band_lower, band_upper))
        band_markup = (
            f"<rect class='band-zone' x='{left}' y='{band_top:.2f}' width='{inner_width:.2f}' "
            f"height='{max(1.0, band_bottom - band_top):.2f}' rx='8' />"
        )

    close_path = path_for("close")
    ema_fast_path = path_for("ema_fast")
    ema_slow_path = path_for("ema_slow")
    price_grid_markup = "".join(
        f"<line class='price-grid' x1='{left:.2f}' y1='{tick_y:.2f}' x2='{width - right:.2f}' y2='{tick_y:.2f}' />"
        for _, tick_y in price_ticks
    )
    price_label_markup = "".join(
        f"<text class='price-label' x='{width - right - 4:.2f}' y='{tick_y - 4:.2f}' text-anchor='end'>"
        f"{html.escape(StatusService.format_decimal(tick_value, places=2))}</text>"
        for tick_value, tick_y in price_ticks
    )
    first_label = _format_local_datetime_short(points[0]["time"])
    mid_label = _format_local_datetime_short(points[len(points) // 2]["time"])
    last_label = _format_local_datetime_short(points[-1]["time"])
    meta = [
        f"<span class='mini-tag'>Trend TF: {html.escape(str(chart_payload.get('timeframe', '-')))}</span>",
        f"<span class='mini-tag'>Candles: {len(points)}</span>",
    ]
    if chart_payload.get("band_width_pct") is not None:
        meta.append(
            f"<span class='mini-tag'>Band Width: {html.escape(StatusService.format_decimal(_decimal_or_none(chart_payload.get('band_width_pct')), places=2))}%</span>"
        )

    return (
        "<div class='chart-shell'>"
        "<div class='chart-head'>"
        "<div><div class='eyebrow'>Live Trend View</div><h3 id='market-chart-title' class='text-lg font-semibold'>Price, candles, EMAs, and band</h3></div>"
        f"<div class='flex flex-wrap gap-2'>{''.join(meta)}</div>"
        "</div>"
        "<div id='market-chart-frame' class='chart-frame'>"
        f"<svg id='market-chart-svg' viewBox='0 0 {width} {height}' role='img' aria-label='Market chart'>"
        f"{price_grid_markup}"
        f"{band_markup}"
        f"<path class='line-close' d='{close_path}' />"
        f"<path class='line-ema-fast' d='{ema_fast_path}' />"
        f"<path class='line-ema-slow' d='{ema_slow_path}' />"
        f"{''.join(candles_markup)}"
        f"{price_label_markup}"
        f"<text class='axis-label' x='{left}' y='{height - 10}'>{html.escape(first_label)}</text>"
        f"<text class='axis-label' x='{width / 2:.2f}' y='{height - 10}' text-anchor='middle'>{html.escape(mid_label)}</text>"
        f"<text class='axis-label' x='{width - right}' y='{height - 10}' text-anchor='end'>{html.escape(last_label)}</text>"
        "</svg>"
        "</div>"
        "<div class='chart-legend'>"
        "<span class='legend-item'><span class='legend-swatch swatch-candle'></span>Candles</span>"
        "<span class='legend-item'><span class='legend-swatch swatch-close'></span>Close</span>"
        "<span class='legend-item'><span class='legend-swatch swatch-ema-fast'></span>EMA Fast</span>"
        "<span class='legend-item'><span class='legend-swatch swatch-ema-slow'></span>EMA Slow</span>"
        "<span class='legend-item'><span class='legend-swatch swatch-band'></span>Band</span>"
        "</div>"
        "</div>"
    )


def _build_metric_data(label: str, value: str, value_id: str | None = None) -> dict[str, str | None]:
    return {"label": label, "value": value, "id": value_id}


def _performance_metric_data(metrics, prefix: str) -> list[dict[str, str | None]]:
    return [
        _build_metric_data("Net PnL", format(metrics.net_profit, "f"), f"metric-{prefix}net-pnl"),
        _build_metric_data("Gross PnL", format(metrics.gross_profit, "f"), f"metric-{prefix}gross-pnl"),
        _build_metric_data("Fees", format(metrics.fees, "f"), f"metric-{prefix}fees"),
        _build_metric_data("Win Rate %", format(metrics.win_rate, "f"), f"metric-{prefix}win-rate"),
        _build_metric_data("Trades", str(metrics.total_trades), f"metric-{prefix}total-trades"),
        _build_metric_data("Open Trades", str(metrics.open_trades), f"metric-{prefix}open-trades"),
        _build_metric_data("Closed Trades", str(metrics.closed_trades), f"metric-{prefix}closed-trades"),
        _build_metric_data("Avg Hold", str(metrics.average_holding_duration), f"metric-{prefix}average-hold"),
    ]


def _strategy_performance_data(strategy_reports: dict[str, object], prefix: str) -> list[dict[str, object]]:
    return [
        {
            "name": strategy_name,
            "metrics": _performance_metric_data(metrics, f"{prefix}{_metric_id_slug(strategy_name)}-"),
        }
        for strategy_name, metrics in strategy_reports.items()
    ]


def _recent_trade_rows(trades: list) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade in trades:
        rows.append(
            {
                "label": f"{trade.id} · {trade.status.value}",
                "execution": f"Qty {format(trade.quantity, 'f')} · Buy {StatusService.format_decimal(trade.buy_price)} · Sell {StatusService.format_decimal(trade.sell_price)}",
                "outcome": f"Net {StatusService.format_decimal(trade.net_profit)}",
                "timing": _format_local_datetime(trade.created_at),
                "detail_tags": [
                    f"Buy Total {_format_money_total(trade.buy_price, trade.quantity, trade.buy_fee)}",
                    f"Sell Total {_format_money_total(trade.sell_price, trade.quantity, trade.sell_fee, subtract_fee=True)}",
                    f"Fees {StatusService.format_decimal(trade.total_fees if trade.total_fees is not None else trade.buy_fee + trade.sell_fee, places=4)}",
                    f"Held {_format_duration_seconds(trade.holding_duration_seconds)}",
                    f"Regime {trade.regime.value if trade.regime else '-'}",
                    f"Strategy {trade.strategy_name or '-'}",
                    f"Buy Order {trade.buy_order_id or '-'}",
                    f"Sell Order {trade.sell_order_id or '-'}",
                ],
            }
        )
    return rows


def _recent_order_rows(orders: list) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for order in orders:
        rows.append(
            {
                "label": f"{order.id} · {order.type.value}",
                "execution": f"Qty {format(order.quantity, 'f')} @ {format(order.price, 'f')}",
                "state": order.status.value,
                "timing": _format_local_datetime(order.time),
                "detail_tags": [
                    f"Trade {order.trade_id or '-'}",
                    f"Notional {StatusService.format_decimal(order.price * order.quantity)}",
                    f"Exchange {order.exchange_id or '-'}",
                    f"Post Only {'yes' if order.post_only else 'no'}",
                ],
            }
        )
    return rows


def _rule_rows(strategy_snapshot: dict[str, object]) -> list[dict[str, str]]:
    state_class_map = {
        "PASS": "rule-pass",
        "FAIL": "rule-fail",
        "INFO": "rule-info",
        "UNKNOWN": "rule-unknown",
    }
    return [
        {
            "label": label,
            "state": state,
            "detail": _format_rule_detail(detail),
            "state_class": state_class_map.get(state, "rule-unknown"),
        }
        for label, state, detail in strategy_snapshot["rules"]
    ]


def _open_trade_row(open_trade) -> dict[str, str] | None:
    if not open_trade:
        return None
    return {
        "id": open_trade.id,
        "quantity": format(open_trade.quantity, "f"),
        "buy_price": StatusService.format_decimal(open_trade.buy_price),
        "buy_time": _format_local_datetime(open_trade.buy_time) if open_trade.buy_time else "-",
        "status": f"{open_trade.status.value} / {open_trade.strategy_name or '-'}",
    }


def render_dashboard(
    status: BotStatus,
    mode: str,
    runtime: dict[str, object] | None = None,
    market_chart: dict[str, object] | None = None,
) -> str:
    latest_snapshot = status.latest_market_snapshot
    latest_decision = status.latest_strategy_decision
    cooldown_status = status.cooldown_status
    runtime = runtime or {}
    refresh_seconds = max(int(runtime.get("polling_interval_seconds") or 30), 1)
    strategy_snapshot = _strategy_snapshot(status)
    rules_title = "SELL Rules" if strategy_snapshot["context"] == "sell" else "BUY Rules"

    cooldown_label = "Disabled"
    cooldown_left = "-"
    if cooldown_status.configured_minutes > 0:
        cooldown_label = "Active" if cooldown_status.active else "Ready"
        cooldown_left = f"{cooldown_status.minutes_remaining} min" if cooldown_status.active else "0 min"

    context = {
        "app_version": _app_version(),
        "generated_at": _format_local_datetime(status.generated_at),
        "timezone_label": _local_timezone_label(),
        "refresh_seconds": refresh_seconds,
        "market_chart_markup": _render_market_chart(market_chart),
        "market_metrics": [
            _build_metric_data("Mode", mode, "metric-mode"),
            _build_metric_data("Asset", status.asset, "metric-asset"),
            _build_metric_data("Bot Loop", "Running" if runtime.get("running") else "External / Off", "metric-bot-loop"),
            _build_metric_data("Regime", latest_snapshot.regime.value if latest_snapshot else "-", "metric-regime"),
            _build_metric_data("Strategy", latest_decision.strategy_name if latest_decision and latest_decision.strategy_name else "-", "metric-strategy"),
            _build_metric_data("Snapshot Time", _format_local_datetime(latest_snapshot.time) if latest_snapshot else "-", "metric-snapshot-time"),
            _build_metric_data("Price", StatusService.format_decimal(latest_snapshot.price if latest_snapshot else None), "metric-price"),
            _build_metric_data("EMA Fast", StatusService.format_decimal(latest_snapshot.ema20 if latest_snapshot else None, places=2), "metric-ema-fast"),
            _build_metric_data("EMA Slow", StatusService.format_decimal(latest_snapshot.ema50 if latest_snapshot else None, places=2), "metric-ema-slow"),
            _build_metric_data("Band Low", StatusService.format_decimal(latest_snapshot.band_lower if latest_snapshot else None), "metric-band-low"),
            _build_metric_data("Band High", StatusService.format_decimal(latest_snapshot.band_upper if latest_snapshot else None), "metric-band-high"),
            _build_metric_data("Band Width %", StatusService.format_decimal(latest_snapshot.band_width_pct if latest_snapshot else None, places=2), "metric-band-width"),
            _build_metric_data("Decision", latest_decision.decision.value if latest_decision else "-", "metric-decision"),
            _build_metric_data("Cooldown", cooldown_label, "metric-cooldown"),
            _build_metric_data("Cooldown Left", cooldown_left, "metric-cooldown-left"),
            _build_metric_data("Last Sell", _format_local_datetime(cooldown_status.last_sell_time), "metric-last-sell"),
        ],
        "trade_counts": ", ".join(f"{key}: {value}" for key, value in sorted(status.trade_counts.items())) or "No trades yet",
        "regime_reason": latest_snapshot.regime_reason if latest_snapshot and latest_snapshot.regime_reason else "No regime explanation persisted yet",
        "decision_reason": latest_decision.reason if latest_decision else "No strategy decision persisted yet",
        "rules_title": rules_title,
        "strategy_rules": _rule_rows(strategy_snapshot),
        "runtime_metrics": [
            _build_metric_data("Cycles", str(runtime.get("cycle_count", 0)), "runtime-cycles"),
            _build_metric_data("Polling Interval", str(runtime.get("polling_interval_seconds", "-")), "runtime-polling-interval"),
            _build_metric_data("Loop Started", _format_local_datetime(runtime.get("started_at")), "runtime-started-at"),
            _build_metric_data("Last Cycle", _format_local_datetime(runtime.get("last_cycle_at")), "runtime-last-cycle"),
            _build_metric_data("Last Error", str(runtime.get("last_error") or "-"), "runtime-last-error"),
        ],
        "performance_panels": [
            {
                "title": "Overall",
                "note": "All recorded trades",
                "root_id": "performance-grid",
                "metrics": _performance_metric_data(status.report_metrics, ""),
                "strategy_root_id": "performance-by-strategy-root",
                "strategy_sections": _strategy_performance_data(status.strategy_report_metrics, "strategy-"),
                "empty_label": "No strategy-specific performance yet",
            },
            {
                "title": "Today",
                "note": "Current local day",
                "root_id": "performance-today-grid",
                "metrics": _performance_metric_data(status.today_report_metrics, "today-"),
                "strategy_root_id": "performance-today-by-strategy-root",
                "strategy_sections": _strategy_performance_data(status.today_strategy_report_metrics, "today-strategy-"),
                "empty_label": "No strategy-specific performance for today",
            },
        ],
        "open_trade": _open_trade_row(status.open_trade),
        "recent_orders": _recent_order_rows(status.recent_orders),
        "exchange_open_orders_summary": (
            f"Live Kraken open orders for {status.asset}."
            if status.exchange_open_orders_error is None
            else f"Kraken fetch error: {status.exchange_open_orders_error}"
        ),
        "exchange_open_order_headers": ["Exchange ID", "Type", "Price", "Qty", "Filled", "Status", "Opened"],
        "exchange_open_orders": [
            [
                order.exchange_order_id,
                order.type.value,
                format(order.price, "f"),
                format(order.quantity, "f"),
                format(order.filled_quantity, "f"),
                order.status,
                _format_local_datetime(order.opened_at),
            ]
            for order in status.exchange_open_orders
        ],
        "recent_trades": _recent_trade_rows(status.recent_trades),
        "recent_log_headers": ["Time", "Level", "Service", "Message", "Context"],
        "recent_logs": [
            [
                _format_local_datetime(log.time),
                log.level,
                log.service,
                log.message,
                log.context_json or "-",
            ]
            for log in status.recent_logs
        ],
    }

    return _template_environment().get_template("dashboard.html").render(**context)


def build_app(container: Container, loop_controller: BotLoopController | None = None):
    status_service = StatusService(container.repositories, container.reporting_service, container.exchange, container.config)
    exchange_cache: dict[str, object] = {
        "expires_at": None,
        "exchange_open_orders": [],
        "exchange_open_orders_error": None,
        "market_chart": None,
    }

    def refresh_exchange_cache(asset: str):
        now_ts = datetime.now().timestamp()
        expires_at = exchange_cache.get("expires_at")
        if isinstance(expires_at, (int, float)) and now_ts < expires_at:
            return

        exchange_open_orders, exchange_open_orders_error = status_service.fetch_exchange_open_orders(asset)
        latest_snapshot = container.repositories.get_latest_market_snapshot(asset)
        market_chart = _build_market_chart(container, latest_snapshot)
        ttl_seconds = max(int(container.config.bot.polling_interval_seconds), 1)

        exchange_cache["exchange_open_orders"] = exchange_open_orders
        exchange_cache["exchange_open_orders_error"] = exchange_open_orders_error
        exchange_cache["market_chart"] = market_chart
        exchange_cache["expires_at"] = now_ts + ttl_seconds

    def cached_exchange_payload(asset: str) -> tuple[list[object], str | None, dict[str, object] | None]:
        refresh_exchange_cache(asset)
        return (
            exchange_cache.get("exchange_open_orders", []),
            exchange_cache.get("exchange_open_orders_error"),
            exchange_cache.get("market_chart"),
        )

    def serve_static(path: str, start_response):
        relative_path = path.removeprefix("/static/")
        target = (_STATIC_DIR / relative_path).resolve()
        try:
            target.relative_to(_STATIC_DIR)
        except ValueError:
            body = b"Not found"
            start_response(
                f"{HTTPStatus.NOT_FOUND.value} {HTTPStatus.NOT_FOUND.phrase}",
                [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]
        if not target.is_file():
            body = b"Not found"
            start_response(
                f"{HTTPStatus.NOT_FOUND.value} {HTTPStatus.NOT_FOUND.phrase}",
                [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", content_type), ("Content-Length", str(len(body)))],
        )
        return [body]

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")

        if path.startswith("/static/"):
            return serve_static(path, start_response)

        asset = container.config.bot.asset
        exchange_open_orders, exchange_open_orders_error, market_chart = cached_exchange_payload(asset)
        status = status_service.get_status(
            asset,
            exchange_open_orders=exchange_open_orders,
            exchange_open_orders_error=exchange_open_orders_error,
        )
        runtime = loop_controller.snapshot() if loop_controller else {
            "running": False,
            "started_at": None,
            "last_cycle_at": None,
            "last_error": None,
            "cycle_count": 0,
            "polling_interval_seconds": container.config.bot.polling_interval_seconds,
        }

        if path == "/api/status":
            body = json.dumps(
                _status_to_dict(status, container.config.bot.mode, runtime, market_chart),
                default=str,
            ).encode("utf-8")
            start_response(
                f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
                [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]

        if path != "/":
            body = b"Not found"
            start_response(
                f"{HTTPStatus.NOT_FOUND.value} {HTTPStatus.NOT_FOUND.phrase}",
                [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]

        body = render_dashboard(status, container.config.bot.mode, runtime, market_chart).encode("utf-8")
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]

    return app


def _status_to_dict(
    status: BotStatus,
    mode: str,
    runtime: dict[str, object],
    market_chart: dict[str, object] | None,
) -> dict[str, object]:
    def normalize(value):
        if is_dataclass(value):
            return {key: normalize(item) for key, item in asdict(value).items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    return {
        "asset": status.asset,
        "app_version": _app_version(),
        "mode": mode,
        "generated_at": status.generated_at.isoformat(),
        "latest_market_snapshot": normalize(status.latest_market_snapshot),
        "latest_strategy_decision": normalize(status.latest_strategy_decision),
        "open_trade": normalize(status.open_trade),
        "has_open_order": status.has_open_order,
        "recent_trades": normalize(status.recent_trades),
        "recent_orders": normalize(status.recent_orders),
        "exchange_open_orders": normalize(status.exchange_open_orders),
        "exchange_open_orders_error": status.exchange_open_orders_error,
        "recent_logs": normalize(status.recent_logs),
        "trade_counts": normalize(status.trade_counts),
        "report_metrics": normalize(status.report_metrics),
        "today_report_metrics": normalize(status.today_report_metrics),
        "strategy_report_metrics": normalize(status.strategy_report_metrics),
        "today_strategy_report_metrics": normalize(status.today_strategy_report_metrics),
        "cooldown_status": normalize(status.cooldown_status),
        "strategy_rules": normalize(_strategy_snapshot(status)),
        "market_chart": normalize(market_chart),
        "runtime": normalize(runtime),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path("config.yaml")), help="Path to YAML configuration file")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the web UI server")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind the web UI server")
    parser.add_argument(
        "--with-bot-loop",
        action="store_true",
        help="Start a background bot loop alongside the web UI",
    )
    args = parser.parse_args()

    config = BotConfig.load(args.config)
    container = Container(config)
    loop_controller = None
    if args.with_bot_loop:
        loop_controller = BotLoopController(BotRunner(container))
        loop_controller.start()
    app = build_app(container, loop_controller)
    with make_server(args.host, args.port, app) as server:
        print(f"Kraken Bot UI serving at http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        finally:
            if loop_controller:
                loop_controller.stop()


if __name__ == "__main__":
    main()
