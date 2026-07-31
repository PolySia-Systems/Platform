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

CREATE TABLE IF NOT EXISTS live_order_checkpoints (
    run_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    venue_order_id TEXT,
    payload_json TEXT NOT NULL,
    persisted_at TEXT NOT NULL,
    PRIMARY KEY (run_id, phase)
);

CREATE INDEX IF NOT EXISTS idx_live_order_checkpoints_client
    ON live_order_checkpoints (client_order_id, persisted_at);

CREATE TABLE IF NOT EXISTS live_round_trip_reconciliations (
    observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    classification TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    persisted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_round_trip_reconciliations_run
    ON live_round_trip_reconciliations (run_id, observed_at, observation_id);

CREATE TABLE IF NOT EXISTS live_lifecycle_alerts (
    alert_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    alert_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    order_reference TEXT,
    message TEXT NOT NULL,
    operator_action TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_lifecycle_alerts_run
    ON live_lifecycle_alerts (run_id, observed_at, alert_code);

CREATE TABLE IF NOT EXISTS copytrading_live_runs (
    run_id TEXT PRIMARY KEY,
    authorization_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    signal_window_end TEXT NOT NULL,
    total_entry_attempts INTEGER NOT NULL DEFAULT 0
        CHECK(total_entry_attempts BETWEEN 0 AND 3),
    completed_live_cycles INTEGER NOT NULL DEFAULT 0
        CHECK(completed_live_cycles BETWEEN 0 AND 3),
    signal_acceptance_open INTEGER NOT NULL DEFAULT 1,
    active_leader_alias TEXT,
    active_event_id TEXT,
    active_market_id TEXT,
    active_market_slug TEXT,
    active_token_id TEXT,
    entry_order_id TEXT,
    exit_order_id TEXT,
    entry_price TEXT,
    entry_quantity TEXT,
    entry_fee TEXT NOT NULL DEFAULT '0',
    entry_cancel_at TEXT,
    fill_price TEXT,
    position_size TEXT NOT NULL DEFAULT '0',
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copytrading_live_attempts (
    run_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),
    leader_alias TEXT NOT NULL,
    event_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    state TEXT NOT NULL,
    venue_order_id TEXT,
    entry_quantity TEXT,
    entry_debit TEXT,
    entry_fee TEXT,
    fill_size TEXT,
    fill_price TEXT,
    exit_price TEXT,
    exit_fee TEXT,
    gross_pnl TEXT,
    net_pnl TEXT,
    terminal_reason TEXT,
    leader_latency_ms INTEGER,
    leader_price_difference TEXT,
    claimed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, attempt_number),
    UNIQUE (run_id, leader_alias),
    UNIQUE (run_id, event_id),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_signal_reservations (
    run_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    UNIQUE (run_id, event_id),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_seen_events (
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_leader_inventory (
    run_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    size TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, leader_alias, market_reference, outcome_reference),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_baselined_leaders (
    run_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    baseline_digest TEXT NOT NULL,
    baselined_at TEXT NOT NULL,
    PRIMARY KEY (run_id, leader_alias),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_discovery_state (
    run_id TEXT PRIMARY KEY,
    ordering_version TEXT NOT NULL,
    ordered_aliases_json TEXT NOT NULL,
    cursor INTEGER NOT NULL CHECK(cursor BETWEEN 0 AND 101),
    active_aliases_json TEXT NOT NULL,
    subset_digest TEXT NOT NULL,
    rotated_at TEXT NOT NULL,
    outage_started_at TEXT,
    next_probe_at TEXT,
    cooldown_attempt INTEGER NOT NULL DEFAULT 0
        CHECK(cooldown_attempt >= 0),
    last_source_success_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_read_checkpoints (
    run_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    checkpoint_value TEXT,
    last_successful_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, leader_alias),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

CREATE TABLE IF NOT EXISTS copytrading_pending_read_events (
    run_id TEXT NOT NULL,
    leader_alias TEXT NOT NULL,
    event_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    staged_at TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id),
    FOREIGN KEY (run_id) REFERENCES copytrading_live_runs(run_id)
);

-- Research/Replay evidence for the Signal Arbiter. These tables contain only
-- protected internal leader keys; raw wallet addresses are prohibited by the
-- domain and repository contracts.
CREATE TABLE IF NOT EXISTS copytrading_wallet_signal_outcomes (
    outcome_id TEXT NOT NULL,
    leader_key TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL CHECK(timeframe_seconds > 0),
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    net_return TEXT NOT NULL,
    maximum_drawdown TEXT NOT NULL,
    labeling_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (outcome_id, labeling_version)
);

CREATE INDEX IF NOT EXISTS idx_copytrading_wallet_outcomes_score
    ON copytrading_wallet_signal_outcomes (
        labeling_version, leader_key, market_type, timeframe_seconds, closed_at
    );

CREATE TABLE IF NOT EXISTS copytrading_follower_execution_outcomes (
    execution_id TEXT PRIMARY KEY,
    leader_key TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL CHECK(timeframe_seconds > 0),
    closed_at TEXT NOT NULL,
    filled INTEGER NOT NULL CHECK(filled IN (0, 1)),
    completed_cycle INTEGER NOT NULL CHECK(completed_cycle IN (0, 1)),
    net_pnl TEXT,
    execution_cost TEXT,
    slippage TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_copytrading_follower_outcomes_score
    ON copytrading_follower_execution_outcomes (
        leader_key, market_type, timeframe_seconds, closed_at
    );

CREATE TABLE IF NOT EXISTS copytrading_concentration_events (
    event_id TEXT PRIMARY KEY,
    leader_key TEXT NOT NULL,
    cause TEXT NOT NULL CHECK(cause IN ('LATE_SIGNAL', 'COMPLETED_CYCLE')),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_copytrading_concentration_leader_time
    ON copytrading_concentration_events (leader_key, occurred_at);
