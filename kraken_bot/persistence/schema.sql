CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    quantity TEXT NOT NULL,
    buy_order_id TEXT,
    sell_order_id TEXT,
    buy_time TEXT,
    sell_time TEXT,
    buy_price TEXT,
    sell_price TEXT,
    buy_fee TEXT DEFAULT '0',
    sell_fee TEXT DEFAULT '0',
    gross_profit TEXT,
    total_fees TEXT,
    net_profit TEXT,
    holding_duration_seconds INTEGER,
    status TEXT NOT NULL,
    strategy_name TEXT,
    regime TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    trade_id TEXT,
    time TEXT NOT NULL,
    type TEXT NOT NULL,
    price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    status TEXT NOT NULL,
    post_only INTEGER NOT NULL,
    exchange_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE TABLE IF NOT EXISTS order_events (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    time TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_payload TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    asset TEXT NOT NULL,
    price TEXT NOT NULL,
    ema20 TEXT,
    ema50 TEXT,
    volatility TEXT,
    volume TEXT,
    trend_status TEXT,
    regime TEXT,
    band_lower TEXT,
    band_upper TEXT,
    band_width_pct TEXT,
    ema20_slope_pct TEXT,
    ema50_slope_pct TEXT,
    regime_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_decisions (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    asset TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    ema20 TEXT,
    ema50 TEXT,
    price TEXT,
    pullback TEXT,
    comment TEXT,
    config_snapshot TEXT,
    regime TEXT,
    strategy_name TEXT,
    target_price TEXT,
    band_lower TEXT,
    band_upper TEXT,
    band_width_pct TEXT,
    rule_states_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_config_history (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id TEXT PRIMARY KEY,
    time TEXT NOT NULL,
    level TEXT NOT NULL,
    service TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT
);
