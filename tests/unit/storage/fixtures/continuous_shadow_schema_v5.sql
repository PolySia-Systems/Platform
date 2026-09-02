PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS continuous_shadow_metadata (
    schema_version INTEGER PRIMARY KEY CHECK(schema_version = 5),
    initialized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuous_shadow_selection_snapshots (
    selection_run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    feature_set_version TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    ranking_version TEXT NOT NULL,
    published_at TEXT NOT NULL,
    candidate_count INTEGER NOT NULL CHECK(candidate_count > 0),
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuous_shadow_wallets (
    wallet_id TEXT PRIMARY KEY,
    normalized_address TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuous_shadow_selection_memberships (
    selection_run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    pools_json TEXT NOT NULL CHECK(json_valid(pools_json)),
    alpha_rank INTEGER CHECK(alpha_rank IS NULL OR alpha_rank > 0),
    stress_rank INTEGER CHECK(stress_rank IS NULL OR stress_rank > 0),
    PRIMARY KEY(selection_run_id, wallet_id),
    FOREIGN KEY(selection_run_id)
        REFERENCES continuous_shadow_selection_snapshots(selection_run_id),
    FOREIGN KEY(wallet_id) REFERENCES continuous_shadow_wallets(wallet_id)
);

CREATE TABLE IF NOT EXISTS continuous_shadow_leases (
    resource TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuous_shadow_experiments (
    experiment_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    selection_run_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    cost_model_version TEXT NOT NULL,
    bankroll_version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    lifecycle TEXT NOT NULL CHECK(lifecycle IN ('RUNNING', 'DRAINING', 'FINALIZED')),
    started_at TEXT NOT NULL,
    draining_at TEXT,
    finalized_at TEXT,
    last_successful_poll_at TEXT,
    last_error_code TEXT,
    FOREIGN KEY(selection_run_id)
        REFERENCES continuous_shadow_selection_snapshots(selection_run_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_continuous_shadow_one_active
    ON continuous_shadow_experiments(source_id)
    WHERE lifecycle IN ('RUNNING', 'DRAINING');

CREATE TABLE IF NOT EXISTS continuous_shadow_candidates (
    experiment_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    pools_json TEXT NOT NULL CHECK(json_valid(pools_json)),
    alpha_rank INTEGER CHECK(alpha_rank IS NULL OR alpha_rank > 0),
    stress_rank INTEGER CHECK(stress_rank IS NULL OR stress_rank > 0),
    selection_run_id TEXT NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0, 1)),
    first_selected_at TEXT NOT NULL,
    last_selected_at TEXT NOT NULL,
    PRIMARY KEY(experiment_id, wallet_id),
    FOREIGN KEY(experiment_id) REFERENCES continuous_shadow_experiments(experiment_id),
    FOREIGN KEY(wallet_id) REFERENCES continuous_shadow_wallets(wallet_id),
    FOREIGN KEY(selection_run_id)
        REFERENCES continuous_shadow_selection_snapshots(selection_run_id)
);

CREATE TABLE IF NOT EXISTS continuous_shadow_poll_runs (
    poll_run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    selection_run_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    failed_at TEXT,
    last_error_code TEXT,
    candidate_count INTEGER NOT NULL CHECK(candidate_count > 0),
    selection_snapshot_digest TEXT NOT NULL CHECK(length(selection_snapshot_digest) = 64),
    selection_published_at TEXT NOT NULL,
    selection_fresh INTEGER NOT NULL CHECK(selection_fresh IN (0, 1)),
    raw_event_count INTEGER NOT NULL DEFAULT 0 CHECK(raw_event_count >= 0),
    new_event_count INTEGER NOT NULL DEFAULT 0 CHECK(new_event_count >= 0),
    duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK(duplicate_count >= 0),
    evaluation_count INTEGER NOT NULL DEFAULT 0 CHECK(evaluation_count >= 0),
    simulated_count INTEGER NOT NULL DEFAULT 0 CHECK(simulated_count >= 0),
    unknown_count INTEGER NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK(rejected_count >= 0),
    settlement_count INTEGER NOT NULL DEFAULT 0 CHECK(settlement_count >= 0),
    settlement_backlog_count INTEGER NOT NULL DEFAULT 0 CHECK(settlement_backlog_count >= 0),
    realized_pnl_delta TEXT NOT NULL DEFAULT '0',
    fee_delta TEXT NOT NULL DEFAULT '0',
    source_api_lag_max_ms INTEGER NOT NULL DEFAULT 0 CHECK(source_api_lag_max_ms >= 0),
    signal_delay_max_ms INTEGER NOT NULL DEFAULT 0 CHECK(signal_delay_max_ms >= 0),
    request_telemetry_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_telemetry_json)),
    FOREIGN KEY(experiment_id) REFERENCES continuous_shadow_experiments(experiment_id),
    FOREIGN KEY(selection_run_id)
        REFERENCES continuous_shadow_selection_snapshots(selection_run_id)
);

CREATE INDEX IF NOT EXISTS idx_continuous_shadow_polls
    ON continuous_shadow_poll_runs(experiment_id, started_at);

CREATE TABLE IF NOT EXISTS continuous_shadow_checkpoint (
    experiment_id TEXT PRIMARY KEY,
    watermark TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_poll_run_id TEXT NOT NULL,
    FOREIGN KEY(experiment_id) REFERENCES continuous_shadow_experiments(experiment_id),
    FOREIGN KEY(last_poll_run_id) REFERENCES continuous_shadow_poll_runs(poll_run_id)
);

CREATE TABLE IF NOT EXISTS continuous_shadow_event_journal (
    event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('BUY', 'SELL')),
    leader_price TEXT NOT NULL,
    leader_size TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    first_poll_run_id TEXT NOT NULL,
    external_evidence_reference TEXT,
    pools_json TEXT NOT NULL CHECK(json_valid(pools_json)),
    processing_status TEXT NOT NULL DEFAULT 'PROCESSED'
        CHECK(processing_status = 'PROCESSED'),
    FOREIGN KEY(wallet_id) REFERENCES continuous_shadow_wallets(wallet_id),
    FOREIGN KEY(first_poll_run_id) REFERENCES continuous_shadow_poll_runs(poll_run_id)
);

CREATE INDEX IF NOT EXISTS idx_continuous_shadow_journal_wallet
    ON continuous_shadow_event_journal(wallet_id, executed_at);

CREATE TABLE IF NOT EXISTS continuous_shadow_portfolios (
    experiment_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(
        kind IN ('WALLET', 'FOLLOWER', 'FOLLOWER_ALPHA', 'FOLLOWER_STRESS')
    ),
    wallet_id TEXT,
    initial_cash TEXT NOT NULL,
    cash TEXT NOT NULL,
    realized_pnl TEXT NOT NULL DEFAULT '0',
    unrealized_pnl TEXT NOT NULL DEFAULT '0',
    fees TEXT NOT NULL DEFAULT '0',
    nav TEXT NOT NULL,
    high_water_nav TEXT NOT NULL,
    drawdown TEXT NOT NULL DEFAULT '0',
    exposure TEXT NOT NULL DEFAULT '0',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(experiment_id, portfolio_id),
    UNIQUE(experiment_id, wallet_id),
    FOREIGN KEY(experiment_id) REFERENCES continuous_shadow_experiments(experiment_id),
    FOREIGN KEY(wallet_id) REFERENCES continuous_shadow_wallets(wallet_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_continuous_shadow_one_follower_kind
    ON continuous_shadow_portfolios(experiment_id, kind)
    WHERE kind IN ('FOLLOWER', 'FOLLOWER_ALPHA', 'FOLLOWER_STRESS');

CREATE TABLE IF NOT EXISTS continuous_shadow_positions (
    experiment_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    quantity TEXT NOT NULL,
    cost_basis TEXT NOT NULL,
    entry_fees TEXT NOT NULL,
    mark_price TEXT,
    marked_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(experiment_id, portfolio_id, market_reference, outcome_reference),
    FOREIGN KEY(experiment_id, portfolio_id)
        REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS continuous_shadow_follower_attribution (
    experiment_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    quantity TEXT NOT NULL,
    cost_basis TEXT NOT NULL,
    pool_class TEXT NOT NULL,
    last_event_id TEXT,
    PRIMARY KEY(
        experiment_id, portfolio_id, wallet_id, market_reference, outcome_reference
    ),
    FOREIGN KEY(experiment_id, wallet_id)
        REFERENCES continuous_shadow_candidates(experiment_id, wallet_id)
        ON DELETE CASCADE,
    FOREIGN KEY(experiment_id, portfolio_id)
        REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS continuous_shadow_evaluations (
    experiment_id TEXT NOT NULL,
    poll_run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    pool_class TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SIMULATED', 'UNKNOWN', 'REJECTED')),
    reason TEXT NOT NULL,
    requested_size TEXT NOT NULL,
    filled_size TEXT NOT NULL,
    follower_price TEXT,
    gross_notional TEXT,
    fee TEXT,
    fee_status TEXT NOT NULL,
    fee_source TEXT NOT NULL,
    fee_rate TEXT,
    fee_exponent TEXT,
    realized_pnl TEXT,
    source_api_lag_ms INTEGER NOT NULL CHECK(source_api_lag_ms >= 0),
    signal_delay_ms INTEGER NOT NULL CHECK(signal_delay_ms >= 0),
    price_movement TEXT,
    spread_cost TEXT,
    depth_impact TEXT,
    liquidity_loss TEXT,
    available_liquidity TEXT,
    quote_timestamp TEXT,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY(experiment_id, event_id, portfolio_id),
    FOREIGN KEY(poll_run_id) REFERENCES continuous_shadow_poll_runs(poll_run_id),
    FOREIGN KEY(event_id) REFERENCES continuous_shadow_event_journal(event_id),
    FOREIGN KEY(experiment_id, portfolio_id)
        REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id),
    FOREIGN KEY(experiment_id, wallet_id)
        REFERENCES continuous_shadow_candidates(experiment_id, wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_continuous_shadow_evaluations_wallet
    ON continuous_shadow_evaluations(experiment_id, wallet_id, evaluated_at);

CREATE TABLE IF NOT EXISTS continuous_shadow_liquidity_consumption (
    experiment_id TEXT NOT NULL,
    poll_run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    price TEXT NOT NULL,
    consumed_size TEXT NOT NULL,
    PRIMARY KEY(experiment_id, event_id, portfolio_id, price),
    FOREIGN KEY(experiment_id, event_id, portfolio_id)
        REFERENCES continuous_shadow_evaluations(experiment_id, event_id, portfolio_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS continuous_shadow_ledger (
    experiment_id TEXT NOT NULL,
    entry_id TEXT PRIMARY KEY,
    poll_run_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    event_id TEXT,
    entry_type TEXT NOT NULL CHECK(
        entry_type IN ('OPEN', 'INCREASE', 'REDUCE', 'CLOSE', 'FEE', 'SETTLEMENT', 'MARK')
    ),
    market_reference TEXT,
    outcome_reference TEXT,
    quantity_delta TEXT NOT NULL,
    cash_delta TEXT NOT NULL,
    cost_basis_delta TEXT NOT NULL,
    realized_pnl_delta TEXT NOT NULL,
    fee_delta TEXT NOT NULL,
    created_at TEXT NOT NULL,
    wallet_id TEXT,
    pool_class TEXT,
    FOREIGN KEY(poll_run_id) REFERENCES continuous_shadow_poll_runs(poll_run_id),
    FOREIGN KEY(experiment_id, portfolio_id)
        REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id)
);

CREATE TABLE IF NOT EXISTS continuous_shadow_position_marks (
    experiment_id TEXT NOT NULL,
    poll_run_id TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    quantity TEXT NOT NULL,
    mark_price TEXT,
    market_value TEXT,
    unrealized_pnl TEXT,
    mark_status TEXT NOT NULL,
    marked_at TEXT NOT NULL,
    source_timestamp TEXT,
    source_age_ms INTEGER,
    freshness TEXT NOT NULL DEFAULT 'MISSING',
    PRIMARY KEY(experiment_id, poll_run_id, portfolio_id, market_reference, outcome_reference),
    FOREIGN KEY(poll_run_id) REFERENCES continuous_shadow_poll_runs(poll_run_id),
    FOREIGN KEY(experiment_id, portfolio_id)
        REFERENCES continuous_shadow_portfolios(experiment_id, portfolio_id)
);

CREATE TABLE IF NOT EXISTS continuous_shadow_terminal_book_cache (
    token_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL CHECK(reason IN ('TERMINAL_404', 'MARKET_CLOSED')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1 CHECK(hit_count >= 1)
);

CREATE VIEW IF NOT EXISTS continuous_shadow_portfolio_current AS
SELECT
    e.source_id,
    e.experiment_id,
    e.lifecycle,
    e.policy_version,
    e.cost_model_version,
    e.bankroll_version,
    e.started_at,
    e.last_successful_poll_at,
    p.portfolio_id,
    p.kind,
    p.wallet_id,
    p.initial_cash,
    p.cash,
    p.realized_pnl,
    p.unrealized_pnl,
    p.fees,
    p.nav,
    p.high_water_nav,
    p.drawdown,
    p.exposure,
    p.updated_at
FROM continuous_shadow_experiments e
JOIN continuous_shadow_portfolios p ON p.experiment_id = e.experiment_id;
