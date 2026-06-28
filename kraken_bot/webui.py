from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
import html
import json
from http import HTTPStatus
from pathlib import Path
import re
from wsgiref.simple_server import make_server

from kraken_bot.app.config import BotConfig
from kraken_bot.app.container import Container
from kraken_bot.app.runner import BotLoopController, BotRunner
from kraken_bot.exchange.kraken_adapter import KrakenApiError
from kraken_bot.services.market_data_service import calculate_ema
from kraken_bot.services.status_service import BotStatus, StatusService


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


def _local_timezone_label() -> str:
    tzinfo = datetime.now().astimezone().tzinfo
    if tzinfo is None:
        return "local time"
    key = getattr(tzinfo, "key", None)
    if key:
        return str(key)
    return tzinfo.tzname(None) or str(tzinfo)


def _render_metric(label: str, value: str, value_id: str | None = None) -> str:
    id_attr = f" id='{html.escape(value_id)}'" if value_id else ""
    return (
        "<div class='card metric'>"
        f"<div class='label'>{html.escape(label)}</div>"
        f"<div{id_attr} class='value'>{html.escape(value)}</div>"
        "</div>"
    )


def _render_table(headers: list[str], rows: list[list[str]], table_class: str = "") -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows) if body_rows else "<tr><td colspan='99'>No data</td></tr>"
    class_attr = f" class='{html.escape(table_class)}'" if table_class else ""
    return f"<div class='table-wrap'><table{class_attr}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _format_rule_detail(detail: str) -> str:
    def replace_decimal(match: re.Match[str]) -> str:
        value = Decimal(match.group(0))
        return format(value.quantize(Decimal("0.01")), "f")

    return re.sub(r"-?\d+\.\d{3,}", replace_decimal, detail)


def _render_rule_row(label: str, state: str, detail: str) -> str:
    state_class = {
        "PASS": "rule-pass",
        "FAIL": "rule-fail",
        "INFO": "rule-info",
        "UNKNOWN": "rule-unknown",
    }.get(state, "rule-unknown")
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td><span class='rule-pill {state_class}'>{html.escape(state)}</span></td>"
        f"<td>{html.escape(_format_rule_detail(detail))}</td>"
        "</tr>"
    )


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
    asset = container.config.bot.asset

    try:
        candles = container.exchange.get_ohlc(asset, timeframe, 48)
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
    first_label = _format_local_datetime(points[0]["time"])
    mid_label = _format_local_datetime(points[len(points) // 2]["time"])
    last_label = _format_local_datetime(points[-1]["time"])
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
        "<div><div class='eyebrow'>Live Trend View</div><h3 id='market-chart-title'>Price, candles, EMAs, and band</h3></div>"
        f"<div class='mini-tags'>{''.join(meta)}</div>"
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


def render_dashboard(
    status: BotStatus,
    mode: str,
    runtime: dict[str, object] | None = None,
    market_chart: dict[str, object] | None = None,
) -> str:
    latest_snapshot = status.latest_market_snapshot
    latest_decision = status.latest_strategy_decision
    open_trade = status.open_trade
    metrics = status.report_metrics
    runtime = runtime or {}
    strategy_snapshot = _strategy_snapshot(status)
    rules_title = "SELL Rules" if strategy_snapshot["context"] == "sell" else "BUY Rules"

    market_cards = [
        _render_metric("Mode", mode, "metric-mode"),
        _render_metric("Asset", status.asset, "metric-asset"),
        _render_metric("Bot Loop", "Running" if runtime.get("running") else "External / Off", "metric-bot-loop"),
        _render_metric("Regime", latest_snapshot.regime.value if latest_snapshot else "-", "metric-regime"),
        _render_metric("Strategy", latest_decision.strategy_name if latest_decision and latest_decision.strategy_name else "-", "metric-strategy"),
        _render_metric("Snapshot Time", _format_local_datetime(latest_snapshot.time) if latest_snapshot else "-", "metric-snapshot-time"),
        _render_metric("Price", StatusService.format_decimal(latest_snapshot.price if latest_snapshot else None), "metric-price"),
        _render_metric("EMA Fast", StatusService.format_decimal(latest_snapshot.ema20 if latest_snapshot else None, places=2), "metric-ema-fast"),
        _render_metric("EMA Slow", StatusService.format_decimal(latest_snapshot.ema50 if latest_snapshot else None, places=2), "metric-ema-slow"),
        _render_metric("Band Low", StatusService.format_decimal(latest_snapshot.band_lower if latest_snapshot else None), "metric-band-low"),
        _render_metric("Band High", StatusService.format_decimal(latest_snapshot.band_upper if latest_snapshot else None), "metric-band-high"),
        _render_metric("Band Width %", StatusService.format_decimal(latest_snapshot.band_width_pct if latest_snapshot else None, places=2), "metric-band-width"),
        _render_metric("Decision", latest_decision.decision.value if latest_decision else "-", "metric-decision"),
    ]
    runtime_cards = [
        _render_metric("Cycles", str(runtime.get("cycle_count", 0)), "runtime-cycles"),
        _render_metric("Polling Interval", str(runtime.get("polling_interval_seconds", "-")), "runtime-polling-interval"),
        _render_metric("Loop Started", _format_local_datetime(runtime.get("started_at")), "runtime-started-at"),
        _render_metric("Last Cycle", _format_local_datetime(runtime.get("last_cycle_at")), "runtime-last-cycle"),
        _render_metric("Last Error", str(runtime.get("last_error") or "-"), "runtime-last-error"),
    ]
    pnl_cards = [
        _render_metric("Net PnL", format(metrics.net_profit, "f")),
        _render_metric("Gross PnL", format(metrics.gross_profit, "f")),
        _render_metric("Fees", format(metrics.fees, "f")),
        _render_metric("Win Rate %", format(metrics.win_rate, "f")),
        _render_metric("Trades", str(metrics.total_trades)),
        _render_metric("Open Trades", str(metrics.open_trades)),
        _render_metric("Closed Trades", str(metrics.closed_trades)),
        _render_metric("Avg Hold", str(metrics.average_holding_duration)),
    ]
    open_trade_markup = (
        _render_table(
            ["Trade ID", "Qty", "Buy Price", "Buy Time", "Status"],
            [[
                open_trade.id,
                format(open_trade.quantity, "f"),
                StatusService.format_decimal(open_trade.buy_price),
                _format_local_datetime(open_trade.buy_time) if open_trade.buy_time else "-",
                f"{open_trade.status.value} / {open_trade.strategy_name or '-'}",
            ]],
        )
        if open_trade
        else "<div class='empty'>No open trade</div>"
    )

    recent_trades = _render_table(
        ["Trade ID", "Asset", "Qty", "Buy", "Sell", "Net", "Status", "Created"],
        [
            [
                trade.id,
                trade.asset,
                format(trade.quantity, "f"),
                StatusService.format_decimal(trade.buy_price),
                StatusService.format_decimal(trade.sell_price),
                StatusService.format_decimal(trade.net_profit),
                trade.status.value,
                _format_local_datetime(trade.created_at),
            ]
            for trade in status.recent_trades
        ],
    )
    recent_orders = _render_table(
        ["Order ID", "Trade ID", "Type", "Price", "Qty", "Status", "Exchange ID", "Time"],
        [
            [
                order.id,
                order.trade_id or "-",
                order.type.value,
                format(order.price, "f"),
                format(order.quantity, "f"),
                order.status.value,
                order.exchange_id or "-",
                _format_local_datetime(order.time),
            ]
            for order in status.recent_orders
        ],
        table_class="table-compact table-recent-orders",
    )
    exchange_open_orders = _render_table(
        ["Exchange ID", "Asset", "Type", "Price", "Qty", "Filled", "Status", "Opened"],
        [
            [
                order.exchange_order_id,
                order.asset,
                order.type.value,
                format(order.price, "f"),
                format(order.quantity, "f"),
                format(order.filled_quantity, "f"),
                order.status,
                _format_local_datetime(order.opened_at),
            ]
            for order in status.exchange_open_orders
        ],
    )
    recent_logs = _render_table(
        ["Time", "Level", "Service", "Message", "Context"],
        [
            [
                _format_local_datetime(log.time),
                log.level,
                log.service,
                log.message,
                log.context_json or "-",
            ]
            for log in status.recent_logs
        ],
    )

    decision_reason = latest_decision.reason if latest_decision else "No strategy decision persisted yet"
    trade_counts = ", ".join(f"{key}: {value}" for key, value in sorted(status.trade_counts.items())) or "No trades yet"
    regime_reason = latest_snapshot.regime_reason if latest_snapshot and latest_snapshot.regime_reason else "No regime explanation persisted yet"
    timezone_label = _local_timezone_label()
    exchange_open_orders_summary = (
        f"Live Kraken open orders for {html.escape(status.asset)}."
        if status.exchange_open_orders_error is None
        else f"Kraken fetch error: {html.escape(status.exchange_open_orders_error)}"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kraken Bot Status</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffaf1;
      --ink: #1b1f1e;
      --muted: #6f756e;
      --accent: #155e63;
      --accent-soft: #d7eceb;
      --border: #d9d0c2;
      --danger: #9d3c2b;
      --font: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      --mono: "SFMono-Regular", "Menlo", monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--font);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff6de 0, transparent 35%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 100%);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px 16px 40px;
    }}
    .hero {{
      padding: 22px;
      border: 1px solid var(--border);
      background: linear-gradient(135deg, var(--panel), #f2ebe0);
      border-radius: 18px;
      box-shadow: 0 14px 40px rgba(27, 31, 30, 0.07);
    }}
    h1, h2 {{ margin: 0 0 10px; }}
    p {{
      margin: 6px 0 0;
      color: var(--muted);
      line-height: 1.45;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .card {{
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 0.84rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric .value {{
      margin-top: 8px;
      font-size: 1.12rem;
      color: var(--accent);
      font-family: var(--mono);
      word-break: break-word;
    }}
    .section {{
      margin-top: 18px;
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: var(--panel);
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-family: var(--mono);
      font-size: 0.88rem;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      white-space: nowrap;
    }}
    .table-compact {{
      table-layout: fixed;
    }}
    .table-compact th, .table-compact td {{
      padding: 8px 6px;
      font-size: 0.8rem;
    }}
    .table-recent-orders th:nth-child(1), .table-recent-orders td:nth-child(1) {{
      width: 16%;
    }}
    .table-recent-orders th:nth-child(2), .table-recent-orders td:nth-child(2) {{
      width: 16%;
    }}
    .table-recent-orders th:nth-child(3), .table-recent-orders td:nth-child(3) {{
      width: 8%;
    }}
    .table-recent-orders th:nth-child(4), .table-recent-orders td:nth-child(4),
    .table-recent-orders th:nth-child(5), .table-recent-orders td:nth-child(5) {{
      width: 9%;
    }}
    .table-recent-orders th:nth-child(6), .table-recent-orders td:nth-child(6) {{
      width: 10%;
    }}
    .table-recent-orders th:nth-child(7), .table-recent-orders td:nth-child(7) {{
      width: 16%;
    }}
    .table-recent-orders th:nth-child(8), .table-recent-orders td:nth-child(8) {{
      width: 16%;
    }}
    .tag {{
      display: inline-block;
      padding: 5px 9px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.82rem;
    }}
    .mini-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 0;
    }}
    .mini-tag {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      background: #efe7d7;
      color: #5d5549;
      font-size: 0.76rem;
      font-family: var(--mono);
    }}
    .reason {{
      margin-top: 12px;
      padding: 14px;
      border-left: 4px solid var(--accent);
      background: #f3f9f8;
    }}
    .empty {{
      padding: 16px;
      border: 1px dashed var(--border);
      border-radius: 12px;
      color: var(--muted);
    }}
    .rule-pill {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 0.76rem;
      letter-spacing: 0.03em;
      font-family: var(--mono);
    }}
    .rule-pass {{
      background: #d8efe2;
      color: #1b6b43;
    }}
    .rule-fail {{
      background: #f6d7d1;
      color: #9d3c2b;
    }}
    .rule-info {{
      background: #e0edf5;
      color: #285a7d;
    }}
    .rule-unknown {{
      background: #ece7db;
      color: #786f5f;
    }}
    .chart-shell {{
      margin-top: 16px;
      padding: 18px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.82), rgba(243,238,228,0.96)),
        radial-gradient(circle at top right, rgba(21, 94, 99, 0.10), transparent 38%);
    }}
    .chart-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      flex-wrap: wrap;
    }}
    .eyebrow {{
      color: var(--muted);
      font-size: 0.74rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .chart-frame {{
      margin-top: 12px;
      width: 100%;
      overflow: hidden;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: linear-gradient(180deg, #fffdf8, #f5eee1);
    }}
    #market-chart-svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .chart-legend {{
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .legend-swatch {{
      width: 14px;
      height: 14px;
      border-radius: 3px;
      display: inline-block;
    }}
    .swatch-candle {{
      background: #1b6b43;
    }}
    .swatch-close {{
      background: #155e63;
    }}
    .swatch-ema-fast {{
      background: #d37b32;
    }}
    .swatch-ema-slow {{
      background: #7057b2;
    }}
    .swatch-band {{
      background: rgba(66, 129, 182, 0.25);
      border: 1px solid rgba(66, 129, 182, 0.55);
    }}
    .band-zone {{
      fill: rgba(66, 129, 182, 0.15);
      stroke: rgba(66, 129, 182, 0.45);
      stroke-dasharray: 6 6;
    }}
    .price-grid {{
      stroke: rgba(111, 117, 110, 0.22);
      stroke-width: 1;
      stroke-dasharray: 3 5;
    }}
    .line-close {{
      fill: none;
      stroke: #155e63;
      stroke-width: 2;
    }}
    .line-ema-fast {{
      fill: none;
      stroke: #d37b32;
      stroke-width: 2.2;
    }}
    .line-ema-slow {{
      fill: none;
      stroke: #7057b2;
      stroke-width: 2.2;
    }}
    .candle-wick {{
      stroke-width: 1.4;
    }}
    .candle-body {{
      stroke-width: 1;
    }}
    .candle-up {{
      stroke: #1b6b43;
      fill: #1b6b43;
    }}
    .candle-down {{
      stroke: #9d3c2b;
      fill: #9d3c2b;
    }}
    .axis-label {{
      fill: #6f756e;
      font-size: 11px;
      font-family: var(--mono);
    }}
    .price-label {{
      fill: #4e554f;
      font-size: 11px;
      font-family: var(--mono);
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    @media (max-width: 760px) {{
      .two-col {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 16px 12px 28px; }}
      .hero, .section {{ border-radius: 14px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <span class="tag">Generated from SQLite state</span>
      <h1>Kraken Bot Status</h1>
      <p>Current bot state, latest market snapshot, strategy decision, and recent trade activity.</p>
      <div class="grid" id="market-metrics-grid">{''.join(market_cards)}</div>
    </section>
    <section class="section">
      <h2>Live Market Chart</h2>
      <p>Recent trend-timeframe candles with live EMA overlays and the currently attached range band.</p>
      <div id="market-chart-root">{_render_market_chart(market_chart)}</div>
    </section>
    <section class="section">
      <h2>Decision Context</h2>
      <p id="trade-counts">Trade counts: {html.escape(trade_counts)}</p>
      <div class="reason" id="regime-reason"><strong>Regime Reason:</strong> {html.escape(regime_reason)}</div>
      <div class="reason" id="decision-reason"><strong>Decision Reason:</strong> {html.escape(decision_reason)}</div>
    </section>
    <section class="section">
      <h2>{html.escape(rules_title)}</h2>
      <p>Rule-by-rule view of the latest strategy evaluation based on persisted snapshot and portfolio state.</p>
      <table>
        <thead>
          <tr>
            <th>Rule</th>
            <th>State</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody id="rules-table-body">
          {''.join(_render_rule_row(label, state, detail) for label, state, detail in strategy_snapshot["rules"])}
        </tbody>
      </table>
    </section>
    <section class="section">
      <h2>Runtime</h2>
      <div class="grid" id="runtime-grid">{''.join(runtime_cards)}</div>
    </section>
    <section class="section">
      <h2>Performance</h2>
      <div class="grid">{''.join(pnl_cards)}</div>
    </section>
    <section class="section">
      <h2>Open Trade</h2>
      {open_trade_markup}
    </section>
    <section class="section">
      <h2>Recent Orders</h2>
      {recent_orders}
    </section>
    <section class="section">
      <h2>Kraken Open Orders</h2>
      <p>{exchange_open_orders_summary}</p>
      {exchange_open_orders}
    </section>
    <section class="section">
      <h2>Recent Trades</h2>
      {recent_trades}
    </section>
    <section class="section">
      <h2>Recent Logs</h2>
      {recent_logs}
      <div class="footer" id="dashboard-footer">Refreshed at {html.escape(status.generated_at.isoformat())} · Timezone: {html.escape(timezone_label)}</div>
    </section>
  </div>
  <script>
    const statusEndpoint = "/api/status";

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function numberOrNull(value) {{
      if (value === null || value === undefined || value === "") return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }}

    function setText(id, value) {{
      const element = document.getElementById(id);
      if (!element) return;
      element.textContent = value ?? "-";
    }}

    function formatLocalDateTime(value) {{
      if (value === null || value === undefined || value === "") return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      const hours = String(date.getHours()).padStart(2, "0");
      const minutes = String(date.getMinutes()).padStart(2, "0");
      const seconds = String(date.getSeconds()).padStart(2, "0");
      return `${{year}}-${{month}}-${{day}} ${{hours}}:${{minutes}}:${{seconds}}`;
    }}

    function formatDecimal(value, places = null) {{
      if (value === null || value === undefined || value === "") return "-";
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return String(value);
      return places === null ? parsed.toString() : parsed.toFixed(places);
    }}

    function formatRuleDetail(detail) {{
      return String(detail ?? "").replace(/-?\\d+\\.\\d{3,}/g, (match) => Number(match).toFixed(2));
    }}

    function renderRules(strategyRules) {{
      const body = document.getElementById("rules-table-body");
      if (!body || !strategyRules) return;
      const rules = Array.isArray(strategyRules.rules) ? strategyRules.rules : [];
      body.innerHTML = rules.map((rule) => {{
        const [label, state, detail] = Array.isArray(rule) ? rule : ["Rule", "UNKNOWN", ""];
        let stateClass = "rule-unknown";
        if (state === "PASS") stateClass = "rule-pass";
        else if (state === "FAIL") stateClass = "rule-fail";
        else if (state === "INFO") stateClass = "rule-info";
        return `
          <tr>
            <td>${{escapeHtml(label)}}</td>
            <td><span class="rule-pill ${{stateClass}}">${{escapeHtml(state)}}</span></td>
            <td>${{escapeHtml(formatRuleDetail(detail))}}</td>
          </tr>
        `;
      }}).join("") || '<tr><td colspan="3">No data</td></tr>';
    }}

    function refreshStatusFields(payload) {{
      const snapshot = payload.latest_market_snapshot || null;
      const decision = payload.latest_strategy_decision || null;
      const runtime = payload.runtime || {{}};

      setText("metric-mode", payload.mode || "-");
      setText("metric-asset", payload.asset || "-");
      setText("metric-bot-loop", runtime.running ? "Running" : "External / Off");
      setText("metric-regime", snapshot?.regime || "-");
      setText("metric-strategy", decision?.strategy_name || "-");
      setText("metric-snapshot-time", snapshot ? formatLocalDateTime(snapshot.time) : "-");
      setText("metric-price", formatDecimal(snapshot?.price));
      setText("metric-ema-fast", formatDecimal(snapshot?.ema20, 2));
      setText("metric-ema-slow", formatDecimal(snapshot?.ema50, 2));
      setText("metric-band-low", formatDecimal(snapshot?.band_lower));
      setText("metric-band-high", formatDecimal(snapshot?.band_upper));
      setText("metric-band-width", formatDecimal(snapshot?.band_width_pct, 2));
      setText("metric-decision", decision?.decision || "-");

      setText("runtime-cycles", String(runtime.cycle_count ?? 0));
      setText("runtime-polling-interval", String(runtime.polling_interval_seconds ?? "-"));
      setText("runtime-started-at", formatLocalDateTime(runtime.started_at));
      setText("runtime-last-cycle", formatLocalDateTime(runtime.last_cycle_at));
      setText("runtime-last-error", runtime.last_error || "-");

      setText("trade-counts", `Trade counts: ${{
        Object.entries(payload.trade_counts || {{}})
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, value]) => `${{key}}: ${{value}}`)
          .join(", ") || "No trades yet"
      }}`);

      const regimeReason = document.getElementById("regime-reason");
      if (regimeReason) regimeReason.innerHTML = `<strong>Regime Reason:</strong> ${{escapeHtml(snapshot?.regime_reason || "No regime explanation persisted yet")}}`;
      const decisionReason = document.getElementById("decision-reason");
      if (decisionReason) decisionReason.innerHTML = `<strong>Decision Reason:</strong> ${{escapeHtml(decision?.reason || "No strategy decision persisted yet")}}`;

      const footer = document.getElementById("dashboard-footer");
      if (footer) {{
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";
        footer.textContent = `Refreshed at ${{formatLocalDateTime(payload.generated_at)}} · Timezone: ${{timezone}}`;
      }}

      renderRules(payload.strategy_rules);
    }}

    function renderMarketChart(chart) {{
      const root = document.getElementById("market-chart-root");
      if (!root || !chart) return;
      if (chart.error) {{
        root.innerHTML = `<div class="empty">Chart unavailable: ${{escapeHtml(chart.error)}}</div>`;
        return;
      }}
      const points = Array.isArray(chart.points) ? chart.points : [];
      if (!points.length) {{
        root.innerHTML = '<div class="empty">No chart data available</div>';
        return;
      }}

      const normalized = points.map((point) => ({{
        time: String(point.time || ""),
        open: numberOrNull(point.open),
        high: numberOrNull(point.high),
        low: numberOrNull(point.low),
        close: numberOrNull(point.close),
        ema_fast: numberOrNull(point.ema_fast),
        ema_slow: numberOrNull(point.ema_slow),
      }})).filter((point) =>
        point.open !== null && point.high !== null && point.low !== null && point.close !== null
      );

      if (!normalized.length) {{
        root.innerHTML = '<div class="empty">No chart data available</div>';
        return;
      }}

      const width = 960;
      const height = 320;
      const left = 18;
      const right = 18;
      const top = 16;
      const bottom = 34;
      const innerWidth = width - left - right;
      const innerHeight = height - top - bottom;
      const bandLower = numberOrNull(chart.band_lower);
      const bandUpper = numberOrNull(chart.band_upper);
      const values = normalized.flatMap((point) => [point.high, point.low]);
      if (bandLower !== null) values.push(bandLower);
      if (bandUpper !== null) values.push(bandUpper);
      let highBound = Math.max(...values);
      let lowBound = Math.min(...values);
      if (highBound === lowBound) {{
        highBound += 1;
        lowBound -= 1;
      }}
      const padding = (highBound - lowBound) * 0.08;
      highBound += padding;
      lowBound -= padding;
      const valueRange = highBound - lowBound;
      const priceTicks = Array.from({{ length: 5 }}, (_, step) => {{
        const ratio = step / 4;
        const value = highBound - (valueRange * ratio);
        return {{ value, y: top + innerHeight - (((value - lowBound) / valueRange) * innerHeight) }};
      }});

      const xPos = (index) => normalized.length === 1
        ? left + innerWidth / 2
        : left + (innerWidth * index / (normalized.length - 1));
      const yPos = (value) => top + innerHeight - (((value - lowBound) / valueRange) * innerHeight);
      const pathFor = (key) => normalized
        .map((point, index) => point[key] === null ? null : `${{index === 0 || normalized.slice(0, index).every((entry) => entry[key] === null) ? "M" : "L"}}${{xPos(index).toFixed(2)}},${{yPos(point[key]).toFixed(2)}}`)
        .filter(Boolean)
        .join(" ");

      const bodyWidth = Math.max(4, Math.min(16, innerWidth / Math.max(normalized.length * 1.8, 2)));
      const candles = normalized.map((point, index) => {{
        const x = xPos(index);
        const openY = yPos(point.open);
        const closeY = yPos(point.close);
        const highY = yPos(point.high);
        const lowY = yPos(point.low);
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(Math.abs(openY - closeY), 1.5);
        const candleClass = point.close >= point.open ? "candle-up" : "candle-down";
        return `
          <line class="candle-wick ${{candleClass}}" x1="${{x.toFixed(2)}}" y1="${{highY.toFixed(2)}}" x2="${{x.toFixed(2)}}" y2="${{lowY.toFixed(2)}}" />
          <rect class="candle-body ${{candleClass}}" x="${{(x - bodyWidth / 2).toFixed(2)}}" y="${{bodyTop.toFixed(2)}}" width="${{bodyWidth.toFixed(2)}}" height="${{bodyHeight.toFixed(2)}}" rx="1.5" />
        `;
      }}).join("");

      let bandMarkup = "";
      if (bandLower !== null && bandUpper !== null) {{
        const bandTop = yPos(Math.max(bandLower, bandUpper));
        const bandBottom = yPos(Math.min(bandLower, bandUpper));
        bandMarkup = `<rect class="band-zone" x="${{left}}" y="${{bandTop.toFixed(2)}}" width="${{innerWidth.toFixed(2)}}" height="${{Math.max(1, bandBottom - bandTop).toFixed(2)}}" rx="8" />`;
      }}

      const priceGrid = priceTicks.map((tick) =>
        `<line class="price-grid" x1="${{left.toFixed(2)}}" y1="${{tick.y.toFixed(2)}}" x2="${{(width - right).toFixed(2)}}" y2="${{tick.y.toFixed(2)}}" />`
      ).join("");
      const priceLabels = priceTicks.map((tick) =>
        `<text class="price-label" x="${{(width - right - 4).toFixed(2)}}" y="${{(tick.y - 4).toFixed(2)}}" text-anchor="end">${{escapeHtml(tick.value.toFixed(2))}}</text>`
      ).join("");

      const firstLabel = escapeHtml(normalized[0].time.replace("T", " ").slice(0, 16));
      const midLabel = escapeHtml(normalized[Math.floor(normalized.length / 2)].time.replace("T", " ").slice(0, 16));
      const lastLabel = escapeHtml(normalized[normalized.length - 1].time.replace("T", " ").slice(0, 16));
      const meta = [
        `<span class="mini-tag">Trend TF: ${{escapeHtml(chart.timeframe || "-")}}</span>`,
        `<span class="mini-tag">Candles: ${{normalized.length}}</span>`,
      ];
      if (chart.band_width_pct !== null && chart.band_width_pct !== undefined && chart.band_width_pct !== "") {{
        meta.push(`<span class="mini-tag">Band Width: ${{escapeHtml(Number(chart.band_width_pct).toFixed(2))}}%</span>`);
      }}

      root.innerHTML = `
        <div class="chart-shell">
          <div class="chart-head">
            <div><div class="eyebrow">Live Trend View</div><h3 id="market-chart-title">Price, candles, EMAs, and band</h3></div>
            <div class="mini-tags">${{meta.join("")}}</div>
          </div>
          <div id="market-chart-frame" class="chart-frame">
            <svg id="market-chart-svg" viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="Market chart">
              ${{priceGrid}}
              ${{bandMarkup}}
              <path class="line-close" d="${{pathFor("close")}}" />
              <path class="line-ema-fast" d="${{pathFor("ema_fast")}}" />
              <path class="line-ema-slow" d="${{pathFor("ema_slow")}}" />
              ${{candles}}
              ${{priceLabels}}
              <text class="axis-label" x="${{left}}" y="${{height - 10}}">${{firstLabel}}</text>
              <text class="axis-label" x="${{(width / 2).toFixed(2)}}" y="${{height - 10}}" text-anchor="middle">${{midLabel}}</text>
              <text class="axis-label" x="${{width - right}}" y="${{height - 10}}" text-anchor="end">${{lastLabel}}</text>
            </svg>
          </div>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-swatch swatch-candle"></span>Candles</span>
            <span class="legend-item"><span class="legend-swatch swatch-close"></span>Close</span>
            <span class="legend-item"><span class="legend-swatch swatch-ema-fast"></span>EMA Fast</span>
            <span class="legend-item"><span class="legend-swatch swatch-ema-slow"></span>EMA Slow</span>
            <span class="legend-item"><span class="legend-swatch swatch-band"></span>Band</span>
          </div>
        </div>
      `;
    }}

    async function refreshDashboardVisuals() {{
      try {{
        const response = await fetch(statusEndpoint, {{ headers: {{ "Accept": "application/json" }} }});
        if (!response.ok) return;
        const payload = await response.json();
        refreshStatusFields(payload);
        renderMarketChart(payload.market_chart);
      }} catch (_error) {{
      }}
    }}

    refreshDashboardVisuals();
    window.setInterval(refreshDashboardVisuals, 5000);
  </script>
</body>
</html>"""


def build_app(container: Container, loop_controller: BotLoopController | None = None):
    status_service = StatusService(container.repositories, container.reporting_service, container.exchange)
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
        ttl_seconds = max(int(container.config.bot.polling_interval_seconds), 15)

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

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
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
