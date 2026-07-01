const statusEndpoint = document.body.dataset.statusEndpoint || "/api/status";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value ?? "-";
}

function formatLocalDateTime(value) {
  if (value === null || value === undefined || value === "") return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

function formatLocalDateTimeShort(value) {
  const formatted = formatLocalDateTime(value);
  return formatted === "-" ? formatted : formatted.slice(0, 16);
}

function formatDurationSeconds(value) {
  if (value === null || value === undefined || value === "") return "-";
  const totalSeconds = Number(value);
  if (!Number.isFinite(totalSeconds)) return String(value);
  const normalized = Math.max(0, Math.trunc(totalSeconds));
  const hours = Math.floor(normalized / 3600);
  const remainder = normalized % 3600;
  const minutes = Math.floor(remainder / 60);
  const seconds = remainder % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function formatDecimal(value, places = null) {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return places === null ? parsed.toString() : parsed.toFixed(places);
}

function formatMoneyTotal(price, quantity, fee = null, subtractFee = false) {
  const priceValue = numberOrNull(price);
  const quantityValue = numberOrNull(quantity);
  if (priceValue === null || quantityValue === null) return "-";
  let total = priceValue * quantityValue;
  const feeValue = numberOrNull(fee);
  if (feeValue !== null) total = subtractFee ? total - feeValue : total + feeValue;
  return formatDecimal(total, 4);
}

function formatRuleDetail(detail) {
  return String(detail ?? "").replace(
    /(^|[^\w.])([-+]?(?:\d+\.\d{3,}|\.\d{3,}|\d+(?:\.\d+)?[eE][-+]?\d+))/g,
    (_fullMatch, prefix, numericPart) => {
      const parsed = Number(numericPart);
      if (!Number.isFinite(parsed)) return `${prefix}${numericPart}`;
      return `${prefix}${parsed.toFixed(2)}`;
    }
  );
}

function tableShell(content, minWidth = "min-w-full", extraClass = "") {
  return `<div class="overflow-x-auto"><table class="w-full ${minWidth} border-collapse font-mono text-sm ${extraClass}">${content}</table></div>`;
}

function renderTable(headers, rows, tableClass = "", colspan = 99) {
  const head = headers
    .map((header) => `<th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">${escapeHtml(header)}</th>`)
    .join("");
  const bodyRows = rows
    .map((row) => {
      const cells = row
        .map((cell) => `<td class="border-b border-stone-900 px-3 py-3 align-top">${escapeHtml(cell)}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  const body = bodyRows || `<tr><td class="border-b border-stone-900 px-3 py-3 text-stone-500" colspan="${colspan}">No data</td></tr>`;
  const classAttr = tableClass ? ` ${tableClass}` : "";
  return tableShell(`<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`, "min-w-full", classAttr);
}

function renderDetailTags(values) {
  const tags = values
    .filter((value) => value !== null && value !== undefined && value !== "" && value !== "-")
    .map((value) => `<span class="detail-tag">${escapeHtml(String(value))}</span>`);
  return tags.join("") || "-";
}

function renderRules(strategyRules) {
  const title = document.getElementById("strategy-rules-title");
  const body = document.getElementById("rules-table-body");
  if (!body || !strategyRules) return;
  if (title) {
    title.textContent = strategyRules.context === "sell" ? "SELL Rules" : "BUY Rules";
  }
  const rules = Array.isArray(strategyRules.rules) ? strategyRules.rules : [];
  body.innerHTML =
    rules
      .map((rule) => {
        const [label, state, detail] = Array.isArray(rule) ? rule : ["Rule", "UNKNOWN", ""];
        let stateClass = "rule-unknown";
        if (state === "PASS") stateClass = "rule-pass";
        else if (state === "FAIL") stateClass = "rule-fail";
        else if (state === "INFO") stateClass = "rule-info";
        return `
          <tr>
            <td class="border-b border-stone-900 px-3 py-3 align-top">${escapeHtml(label)}</td>
            <td class="border-b border-stone-900 px-3 py-3 align-top"><span class="rule-pill ${stateClass}">${escapeHtml(state)}</span></td>
            <td class="border-b border-stone-900 px-3 py-3 align-top">${escapeHtml(formatRuleDetail(detail))}</td>
          </tr>
        `;
      })
      .join("") || '<tr><td class="border-b border-stone-900 px-3 py-3 text-stone-500" colspan="3">No data</td></tr>';
}

function renderMetricCard(label, valueId) {
  return `
    <article class="rounded-2xl border border-stone-800/80 bg-stone-900/80 p-4 shadow-sm shadow-black/20">
      <div class="text-[0.72rem] uppercase tracking-[0.18em] text-stone-400">${escapeHtml(label)}</div>
      <div id="${escapeHtml(valueId)}" class="mt-2 break-words font-mono text-[1.02rem] text-cyan-300">-</div>
    </article>
  `;
}

function renderMetricGrid(metricsHtml, extraClass = "") {
  return `<div class="grid grid-cols-2 gap-3 xl:grid-cols-4 ${extraClass}">${metricsHtml}</div>`;
}

function renderPerformance(prefix, reportMetrics) {
  const idPrefix = prefix ? `${prefix}-` : "";
  setText(`metric-${idPrefix}net-pnl`, formatDecimal(reportMetrics?.net_profit));
  setText(`metric-${idPrefix}gross-pnl`, formatDecimal(reportMetrics?.gross_profit));
  setText(`metric-${idPrefix}fees`, formatDecimal(reportMetrics?.fees));
  setText(`metric-${idPrefix}win-rate`, formatDecimal(reportMetrics?.win_rate));
  setText(`metric-${idPrefix}total-trades`, String(reportMetrics?.total_trades ?? 0));
  setText(`metric-${idPrefix}open-trades`, String(reportMetrics?.open_trades ?? 0));
  setText(`metric-${idPrefix}closed-trades`, String(reportMetrics?.closed_trades ?? 0));
  setText(`metric-${idPrefix}average-hold`, String(reportMetrics?.average_holding_duration ?? "-"));
}

function escapeStrategyMetricPrefix(value) {
  return String(value || "unknown").replaceAll(/[^a-zA-Z0-9_-]/g, "-");
}

function renderStrategyPerformance(containerId, strategyReports, prefix, emptyLabel) {
  const root = document.getElementById(containerId);
  if (!root) return;
  const entries = Object.entries(strategyReports || {});
  if (!entries.length) {
    root.innerHTML = `<div class="empty">${escapeHtml(emptyLabel)}</div>`;
    return;
  }
  root.innerHTML = entries
    .map(([strategyName], index) => {
      const safePrefix = `${prefix}${escapeStrategyMetricPrefix(strategyName)}-`;
      return `
        <div class="${index === 0 ? "" : "mt-4 border-t border-stone-800 pt-4"}">
          <h4 class="mb-3 font-mono text-sm text-stone-100">${escapeHtml(strategyName)}</h4>
          ${renderMetricGrid(
            renderMetricCard("Net PnL", `metric-${safePrefix}net-pnl`) +
              renderMetricCard("Gross PnL", `metric-${safePrefix}gross-pnl`) +
              renderMetricCard("Fees", `metric-${safePrefix}fees`) +
              renderMetricCard("Win Rate %", `metric-${safePrefix}win-rate`) +
              renderMetricCard("Trades", `metric-${safePrefix}total-trades`) +
              renderMetricCard("Open Trades", `metric-${safePrefix}open-trades`) +
              renderMetricCard("Closed Trades", `metric-${safePrefix}closed-trades`) +
              renderMetricCard("Avg Hold", `metric-${safePrefix}average-hold`)
          )}
        </div>
      `;
    })
    .join("");
  for (const [strategyName, metrics] of entries) {
    renderPerformance(`${prefix}${escapeStrategyMetricPrefix(strategyName)}`, metrics);
  }
}

function renderOpenTrade(openTrade) {
  const root = document.getElementById("open-trade-root");
  if (!root) return;
  if (!openTrade) {
    root.innerHTML = "<div class='empty'>No open trade</div>";
    return;
  }
  root.innerHTML = renderTable(
    ["Trade ID", "Qty", "Buy Price", "Buy Time", "Status"],
    [[
      String(openTrade.id || "-"),
      formatDecimal(openTrade.quantity),
      formatDecimal(openTrade.buy_price),
      formatLocalDateTime(openTrade.buy_time),
      `${String(openTrade.status || "-")} / ${String(openTrade.strategy_name || "-")}`,
    ]],
    "",
    5
  );
}

function renderRecentOrders(orders) {
  const root = document.getElementById("recent-orders-root");
  if (!root) return;
  const entries = (Array.isArray(orders) ? orders : [])
    .map((order) => {
      const detail = renderDetailTags([
        `Trade ${String(order.trade_id || "-")}`,
        `Notional ${formatMoneyTotal(order.price, order.quantity)}`,
        `Exchange ${String(order.exchange_id || "-")}`,
        `Post Only ${order.post_only ? "yes" : "no"}`,
      ]);
      return `
        <tr class="entry-summary">
          <td class="px-3 py-2">${escapeHtml(`${String(order.id || "-")} · ${String(order.type || "-")}`)}</td>
          <td class="px-3 py-2">${escapeHtml(`Qty ${formatDecimal(order.quantity)} @ ${formatDecimal(order.price)}`)}</td>
          <td class="px-3 py-2">${escapeHtml(String(order.status || "-"))}</td>
          <td class="px-3 py-2">${escapeHtml(formatLocalDateTime(order.time))}</td>
        </tr>
        <tr class="entry-detail">
          <td class="px-3 pb-3 pt-0" colspan="4">${detail}</td>
        </tr>
      `;
    })
    .join("") || '<tr><td class="border-b border-stone-900 px-3 py-3 text-stone-500" colspan="4">No data</td></tr>';
  root.innerHTML = tableShell(
    `<thead><tr><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Order</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Execution</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Status</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Time</th></tr></thead><tbody>${entries}</tbody>`,
    "min-w-[720px] table-fixed text-[0.82rem]"
  );
}

function renderExchangeOpenOrders(asset, orders, error) {
  const summary = document.getElementById("exchange-open-orders-summary");
  if (summary) {
    summary.textContent = error ? `Kraken fetch error: ${error}` : `Live Kraken open orders for ${asset || "-"}.`;
  }
  const root = document.getElementById("exchange-open-orders-root");
  if (!root) return;
  const rows = (Array.isArray(orders) ? orders : []).map((order) => [
    String(order.exchange_order_id || "-"),
    String(order.type || "-"),
    formatDecimal(order.price),
    formatDecimal(order.quantity),
    formatDecimal(order.filled_quantity),
    String(order.status || "-"),
    formatLocalDateTime(order.opened_at),
  ]);
  root.innerHTML = renderTable(
    ["Exchange ID", "Type", "Price", "Qty", "Filled", "Status", "Opened"],
    rows,
    "",
    7
  );
}

function renderRecentTrades(trades) {
  const root = document.getElementById("recent-trades-root");
  if (!root) return;
  const entries = (Array.isArray(trades) ? trades : [])
    .map((trade) => {
      const detail = renderDetailTags([
        `Buy Total ${formatMoneyTotal(trade.buy_price, trade.quantity, trade.buy_fee, false)}`,
        `Sell Total ${formatMoneyTotal(trade.sell_price, trade.quantity, trade.sell_fee, true)}`,
        `Fees ${formatDecimal(trade.total_fees ?? ((numberOrNull(trade.buy_fee) ?? 0) + (numberOrNull(trade.sell_fee) ?? 0)), 4)}`,
        `Held ${formatDurationSeconds(trade.holding_duration_seconds)}`,
        `Regime ${String(trade.regime || "-")}`,
        `Strategy ${String(trade.strategy_name || "-")}`,
        `Buy Order ${String(trade.buy_order_id || "-")}`,
        `Sell Order ${String(trade.sell_order_id || "-")}`,
      ]);
      return `
        <tr class="entry-summary">
          <td class="px-3 py-2">${escapeHtml(`${String(trade.id || "-")} · ${String(trade.status || "-")}`)}</td>
          <td class="px-3 py-2">${escapeHtml(`Qty ${formatDecimal(trade.quantity)} · Buy ${formatDecimal(trade.buy_price)} · Sell ${formatDecimal(trade.sell_price)}`)}</td>
          <td class="px-3 py-2">${escapeHtml(`Net ${formatDecimal(trade.net_profit)}`)}</td>
          <td class="px-3 py-2">${escapeHtml(formatLocalDateTime(trade.created_at))}</td>
        </tr>
        <tr class="entry-detail">
          <td class="px-3 pb-3 pt-0" colspan="4">${detail}</td>
        </tr>
      `;
    })
    .join("") || '<tr><td class="border-b border-stone-900 px-3 py-3 text-stone-500" colspan="4">No data</td></tr>';
  root.innerHTML = tableShell(
    `<thead><tr><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Trade</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Execution</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Outcome</th><th class="border-b border-stone-800 px-3 py-3 text-left font-medium text-stone-400">Created</th></tr></thead><tbody>${entries}</tbody>`,
    "min-w-[720px] table-fixed text-[0.82rem]"
  );
}

function renderRecentLogs(logs) {
  const root = document.getElementById("recent-logs-root");
  if (!root) return;
  const rows = (Array.isArray(logs) ? logs : []).map((log) => [
    formatLocalDateTime(log.time),
    String(log.level || "-"),
    String(log.service || "-"),
    String(log.message || "-"),
    String(log.context_json || "-"),
  ]);
  root.innerHTML = renderTable(["Time", "Level", "Service", "Message", "Context"], rows, "", 5);
}

function refreshStatusFields(payload) {
  const snapshot = payload.latest_market_snapshot || null;
  const decision = payload.latest_strategy_decision || null;
  const cooldown = payload.cooldown_status || null;
  const runtime = payload.runtime || {};

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
  setText(
    "metric-cooldown",
    (cooldown?.configured_minutes ?? 0) > 0 ? (cooldown?.active ? "Active" : "Ready") : "Disabled"
  );
  setText(
    "metric-cooldown-left",
    (cooldown?.configured_minutes ?? 0) > 0 ? `${cooldown?.minutes_remaining ?? 0} min` : "-"
  );
  setText("metric-last-sell", formatLocalDateTime(cooldown?.last_sell_time));

  setText("runtime-cycles", String(runtime.cycle_count ?? 0));
  setText("runtime-polling-interval", String(runtime.polling_interval_seconds ?? "-"));
  setText("runtime-started-at", formatLocalDateTime(runtime.started_at));
  setText("runtime-last-cycle", formatLocalDateTime(runtime.last_cycle_at));
  setText("runtime-last-error", runtime.last_error || "-");

  setText(
    "trade-counts",
    `Trade counts: ${
      Object.entries(payload.trade_counts || {})
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, value]) => `${key}: ${value}`)
        .join(", ") || "No trades yet"
    }`
  );

  const regimeReason = document.getElementById("regime-reason");
  if (regimeReason) regimeReason.innerHTML = `<strong>Regime Reason:</strong> ${escapeHtml(snapshot?.regime_reason || "No regime explanation persisted yet")}`;
  const decisionReason = document.getElementById("decision-reason");
  if (decisionReason) decisionReason.innerHTML = `<strong>Decision Reason:</strong> ${escapeHtml(decision?.reason || "No strategy decision persisted yet")}`;

  const footerMeta = document.getElementById("dashboard-refresh-meta");
  if (footerMeta) {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";
    footerMeta.textContent = `Refreshed at ${formatLocalDateTime(payload.generated_at)} · Timezone: ${timezone}`;
  }

  setText("dashboard-app-version", payload.app_version || "unknown");

  renderPerformance("", payload.report_metrics || null);
  renderPerformance("today", payload.today_report_metrics || null);
  renderStrategyPerformance(
    "performance-by-strategy-root",
    payload.strategy_report_metrics || {},
    "strategy-",
    "No strategy-specific performance yet"
  );
  renderStrategyPerformance(
    "performance-today-by-strategy-root",
    payload.today_strategy_report_metrics || {},
    "today-strategy-",
    "No strategy-specific performance for today"
  );
  renderOpenTrade(payload.open_trade || null);
  renderRecentOrders(payload.recent_orders || []);
  renderExchangeOpenOrders(payload.asset || "-", payload.exchange_open_orders || [], payload.exchange_open_orders_error || null);
  renderRecentTrades(payload.recent_trades || []);
  renderRecentLogs(payload.recent_logs || []);
  renderRules(payload.strategy_rules);
}

function renderMarketChart(chart) {
  const root = document.getElementById("market-chart-root");
  if (!root || !chart) return;
  if (chart.error) {
    root.innerHTML = `<div class="empty">Chart unavailable: ${escapeHtml(chart.error)}</div>`;
    return;
  }
  const points = Array.isArray(chart.points) ? chart.points : [];
  if (!points.length) {
    root.innerHTML = '<div class="empty">No chart data available</div>';
    return;
  }

  const normalized = points
    .map((point) => ({
      time: String(point.time || ""),
      open: numberOrNull(point.open),
      high: numberOrNull(point.high),
      low: numberOrNull(point.low),
      close: numberOrNull(point.close),
      ema_fast: numberOrNull(point.ema_fast),
      ema_slow: numberOrNull(point.ema_slow),
    }))
    .filter((point) => point.open !== null && point.high !== null && point.low !== null && point.close !== null);

  if (!normalized.length) {
    root.innerHTML = '<div class="empty">No chart data available</div>';
    return;
  }

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
  if (highBound === lowBound) {
    highBound += 1;
    lowBound -= 1;
  }
  const padding = (highBound - lowBound) * 0.08;
  highBound += padding;
  lowBound -= padding;
  const valueRange = highBound - lowBound;
  const priceTicks = Array.from({ length: 5 }, (_, step) => {
    const ratio = step / 4;
    const value = highBound - valueRange * ratio;
    return { value, y: top + innerHeight - ((value - lowBound) / valueRange) * innerHeight };
  });

  const xPos = (index) =>
    normalized.length === 1 ? left + innerWidth / 2 : left + (innerWidth * index) / (normalized.length - 1);
  const yPos = (value) => top + innerHeight - ((value - lowBound) / valueRange) * innerHeight;
  const pathFor = (key) =>
    normalized
      .map((point, index) =>
        point[key] === null
          ? null
          : `${index === 0 || normalized.slice(0, index).every((entry) => entry[key] === null) ? "M" : "L"}${xPos(index).toFixed(2)},${yPos(point[key]).toFixed(2)}`
      )
      .filter(Boolean)
      .join(" ");

  const bodyWidth = Math.max(4, Math.min(16, innerWidth / Math.max(normalized.length * 1.8, 2)));
  const candles = normalized
    .map((point, index) => {
      const x = xPos(index);
      const openY = yPos(point.open);
      const closeY = yPos(point.close);
      const highY = yPos(point.high);
      const lowY = yPos(point.low);
      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(openY - closeY), 1.5);
      const candleClass = point.close >= point.open ? "candle-up" : "candle-down";
      return `
        <line class="candle-wick ${candleClass}" x1="${x.toFixed(2)}" y1="${highY.toFixed(2)}" x2="${x.toFixed(2)}" y2="${lowY.toFixed(2)}" />
        <rect class="candle-body ${candleClass}" x="${(x - bodyWidth / 2).toFixed(2)}" y="${bodyTop.toFixed(2)}" width="${bodyWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}" rx="1.5" />
      `;
    })
    .join("");

  let bandMarkup = "";
  if (bandLower !== null && bandUpper !== null) {
    const bandTop = yPos(Math.max(bandLower, bandUpper));
    const bandBottom = yPos(Math.min(bandLower, bandUpper));
    bandMarkup = `<rect class="band-zone" x="${left}" y="${bandTop.toFixed(2)}" width="${innerWidth.toFixed(2)}" height="${Math.max(1, bandBottom - bandTop).toFixed(2)}" rx="8" />`;
  }

  const priceGrid = priceTicks
    .map(
      (tick) =>
        `<line class="price-grid" x1="${left.toFixed(2)}" y1="${tick.y.toFixed(2)}" x2="${(width - right).toFixed(2)}" y2="${tick.y.toFixed(2)}" />`
    )
    .join("");
  const priceLabels = priceTicks
    .map(
      (tick) =>
        `<text class="price-label" x="${(width - right - 4).toFixed(2)}" y="${(tick.y - 4).toFixed(2)}" text-anchor="end">${escapeHtml(tick.value.toFixed(2))}</text>`
    )
    .join("");

  const firstLabel = escapeHtml(formatLocalDateTimeShort(normalized[0].time));
  const midLabel = escapeHtml(formatLocalDateTimeShort(normalized[Math.floor(normalized.length / 2)].time));
  const lastLabel = escapeHtml(formatLocalDateTimeShort(normalized[normalized.length - 1].time));
  const meta = [
    `<span class="mini-tag">Trend TF: ${escapeHtml(chart.timeframe || "-")}</span>`,
    `<span class="mini-tag">Candles: ${normalized.length}</span>`,
  ];
  if (chart.band_width_pct !== null && chart.band_width_pct !== undefined && chart.band_width_pct !== "") {
    meta.push(`<span class="mini-tag">Band Width: ${escapeHtml(Number(chart.band_width_pct).toFixed(2))}%</span>`);
  }

  root.innerHTML = `
    <div class="chart-shell">
      <div class="chart-head">
        <div><div class="eyebrow">Live Trend View</div><h3 id="market-chart-title" class="text-lg font-semibold">Price, candles, EMAs, and band</h3></div>
        <div class="flex flex-wrap gap-2">${meta.join("")}</div>
      </div>
      <div id="market-chart-frame" class="chart-frame">
        <svg id="market-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Market chart">
          ${priceGrid}
          ${bandMarkup}
          <path class="line-close" d="${pathFor("close")}" />
          <path class="line-ema-fast" d="${pathFor("ema_fast")}" />
          <path class="line-ema-slow" d="${pathFor("ema_slow")}" />
          ${candles}
          ${priceLabels}
          <text class="axis-label" x="${left}" y="${height - 10}">${firstLabel}</text>
          <text class="axis-label" x="${(width / 2).toFixed(2)}" y="${height - 10}" text-anchor="middle">${midLabel}</text>
          <text class="axis-label" x="${width - right}" y="${height - 10}" text-anchor="end">${lastLabel}</text>
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
}

async function refreshDashboardVisuals() {
  try {
    const response = await fetch(statusEndpoint, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const payload = await response.json();
    refreshStatusFields(payload);
    renderMarketChart(payload.market_chart);
  } catch (_error) {
  }
}

refreshDashboardVisuals();
window.setInterval(refreshDashboardVisuals, Number(document.body.dataset.refreshSeconds || "30") * 1000);
