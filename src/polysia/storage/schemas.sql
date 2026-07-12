PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS market_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    token_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    exchange_ts TEXT,
    payload_json TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_events_token_received
    ON market_events (token_id, received_at);

CREATE TABLE IF NOT EXISTS markets (
    market_id TEXT PRIMARY KEY,
    slug TEXT,
    question TEXT,
    category TEXT,
    active INTEGER,
    closed INTEGER,
    accepting_orders INTEGER,
    end_date TEXT,
    liquidity TEXT,
    volume TEXT,
    best_bid TEXT,
    best_ask TEXT,
    outcomes_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_markets_slug ON markets (slug);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    best_bid TEXT,
    best_ask TEXT,
    mid TEXT,
    spread TEXT,
    bid_depth TEXT NOT NULL,
    ask_depth TEXT NOT NULL,
    imbalance TEXT,
    microprice TEXT,
    bids_json TEXT NOT NULL,
    asks_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_token_captured
    ON orderbook_snapshots (token_id, captured_at);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    approved INTEGER,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_token_created
    ON decisions (token_id, created_at);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    strategy_id TEXT,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_token_status ON orders (token_id, status);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    fee TEXT,
    liquidity_role TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_fills_order ON fills (order_id);

CREATE TABLE IF NOT EXISTS positions (
    token_id TEXT PRIMARY KEY,
    market_id TEXT,
    size TEXT NOT NULL,
    avg_price TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_definitions (
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    runtime_mode TEXT NOT NULL,
    venue TEXT NOT NULL,
    market TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    run_json TEXT NOT NULL,
    FOREIGN KEY (strategy_id, strategy_version)
        REFERENCES strategy_definitions(strategy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_identity_started
    ON strategy_runs (strategy_id, strategy_version, started_at);

CREATE TABLE IF NOT EXISTS strategy_performance (
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy_id, strategy_version),
    FOREIGN KEY (strategy_id, strategy_version)
        REFERENCES strategy_definitions(strategy_id, version)
);

CREATE TABLE IF NOT EXISTS live_entry_attempts (
    authorization_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    state TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    instrument_id TEXT,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    order_id TEXT,
    fill_id TEXT,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_events_run_occurred
    ON ledger_events (run_id, occurred_at, event_id);
