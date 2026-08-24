PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dynamic_shadow_metadata (
    schema_version INTEGER PRIMARY KEY CHECK(schema_version = 1),
    initialized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dynamic_shadow_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    selection_run_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('HISTORICAL', 'FORWARD')),
    policy_version TEXT NOT NULL,
    cost_model_version TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    failed_at TEXT,
    last_error_code TEXT,
    candidate_count INTEGER NOT NULL CHECK(candidate_count > 0),
    event_count INTEGER NOT NULL DEFAULT 0 CHECK(event_count >= 0),
    simulated_count INTEGER NOT NULL DEFAULT 0 CHECK(simulated_count >= 0),
    unknown_count INTEGER NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK(rejected_count >= 0),
    realized_pnl TEXT NOT NULL DEFAULT '0',
    fees TEXT NOT NULL DEFAULT '0',
    slippage TEXT NOT NULL DEFAULT '0',
    FOREIGN KEY(selection_run_id) REFERENCES copyability_selection_runs(run_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dynamic_shadow_success_identity
    ON dynamic_shadow_runs(
        selection_run_id,
        mode,
        policy_version,
        cost_model_version,
        window_start,
        window_end
    ) WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS idx_dynamic_shadow_runs_source
    ON dynamic_shadow_runs(source_id, mode, started_at);

CREATE TABLE IF NOT EXISTS dynamic_shadow_candidates (
    run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    pools_json TEXT NOT NULL CHECK(json_valid(pools_json)),
    alpha_rank INTEGER CHECK(alpha_rank IS NULL OR alpha_rank > 0),
    stress_rank INTEGER CHECK(stress_rank IS NULL OR stress_rank > 0),
    PRIMARY KEY(run_id, wallet_id),
    FOREIGN KEY(run_id) REFERENCES dynamic_shadow_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(wallet_id) REFERENCES canonical_wallets(wallet_id)
);

CREATE TABLE IF NOT EXISTS dynamic_shadow_evaluations (
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    market_reference TEXT NOT NULL,
    outcome_reference TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('BUY', 'SELL')),
    evaluation_status TEXT NOT NULL CHECK(
        evaluation_status IN ('SIMULATED', 'UNKNOWN', 'REJECTED')
    ),
    reason TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('HISTORICAL', 'FORWARD')),
    leader_price TEXT NOT NULL,
    requested_size TEXT NOT NULL,
    filled_size TEXT NOT NULL,
    follower_price TEXT,
    gross_notional TEXT,
    fee TEXT,
    slippage TEXT,
    delay_ms INTEGER NOT NULL CHECK(delay_ms >= 0),
    available_liquidity TEXT,
    realized_pnl TEXT,
    quote_source TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY(run_id, event_id),
    FOREIGN KEY(run_id, wallet_id)
        REFERENCES dynamic_shadow_candidates(run_id, wallet_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dynamic_shadow_evaluations_wallet
    ON dynamic_shadow_evaluations(run_id, wallet_id, executed_at);

CREATE TABLE IF NOT EXISTS dynamic_shadow_wallet_summaries (
    run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK(event_count >= 0),
    simulated_count INTEGER NOT NULL CHECK(simulated_count >= 0),
    unknown_count INTEGER NOT NULL CHECK(unknown_count >= 0),
    rejected_count INTEGER NOT NULL CHECK(rejected_count >= 0),
    buy_count INTEGER NOT NULL CHECK(buy_count >= 0),
    sell_count INTEGER NOT NULL CHECK(sell_count >= 0),
    realized_pnl TEXT NOT NULL,
    fees TEXT NOT NULL,
    slippage TEXT NOT NULL,
    open_notional TEXT NOT NULL,
    PRIMARY KEY(run_id, wallet_id),
    FOREIGN KEY(run_id, wallet_id)
        REFERENCES dynamic_shadow_candidates(run_id, wallet_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dynamic_shadow_current (
    source_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('HISTORICAL', 'FORWARD')),
    run_id TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    PRIMARY KEY(source_id, mode),
    FOREIGN KEY(run_id) REFERENCES dynamic_shadow_runs(run_id)
);

CREATE VIEW IF NOT EXISTS dynamic_shadow_wallets_current AS
SELECT
    r.source_id,
    r.selection_run_id,
    r.mode,
    r.policy_version,
    r.cost_model_version,
    r.window_start,
    r.window_end,
    r.completed_at,
    c.wallet_id,
    c.pools_json,
    c.alpha_rank,
    c.stress_rank,
    s.event_count,
    s.simulated_count,
    s.unknown_count,
    s.rejected_count,
    s.buy_count,
    s.sell_count,
    s.realized_pnl,
    s.fees,
    s.slippage,
    s.open_notional,
    r.run_id
FROM dynamic_shadow_current current
JOIN dynamic_shadow_runs r ON r.run_id = current.run_id
JOIN dynamic_shadow_candidates c ON c.run_id = r.run_id
JOIN dynamic_shadow_wallet_summaries s
    ON s.run_id = c.run_id AND s.wallet_id = c.wallet_id;
