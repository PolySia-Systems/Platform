PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidate_intelligence_metadata (
    schema_version INTEGER PRIMARY KEY CHECK(schema_version = 1),
    initialized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_pipeline_leases (
    resource TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL
);

-- Protected canonical identity. Reports and ordinary consumers use wallet_id only.
CREATE TABLE IF NOT EXISTS canonical_wallets (
    wallet_id TEXT PRIMARY KEY,
    chain TEXT NOT NULL,
    normalized_address TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(chain, normalized_address)
);

CREATE TABLE IF NOT EXISTS wallet_source_links (
    source_id TEXT NOT NULL,
    source_wallet_key TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(source_id, source_wallet_key),
    FOREIGN KEY(source_wallet_key) REFERENCES candidate_wallet_identities(wallet_key)
        ON DELETE CASCADE,
    FOREIGN KEY(wallet_id) REFERENCES canonical_wallets(wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_wallet_source_links_wallet
    ON wallet_source_links(wallet_id, source_id);

CREATE TABLE IF NOT EXISTS candidate_intelligence_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    feature_set_version TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    ranking_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    calculated_at TEXT,
    published_at TEXT,
    failed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    evaluated_count INTEGER CHECK(evaluated_count IS NULL OR evaluated_count >= 0),
    selected_count INTEGER CHECK(selected_count IS NULL OR selected_count >= 0),
    watchlist_count INTEGER CHECK(watchlist_count IS NULL OR watchlist_count >= 0),
    ineligible_count INTEGER CHECK(ineligible_count IS NULL OR ineligible_count >= 0),
    ready_count INTEGER CHECK(ready_count IS NULL OR ready_count >= 0),
    partial_count INTEGER CHECK(partial_count IS NULL OR partial_count >= 0),
    stale_count INTEGER CHECK(stale_count IS NULL OR stale_count >= 0),
    invalid_count INTEGER CHECK(invalid_count IS NULL OR invalid_count >= 0),
    unknown_count INTEGER CHECK(unknown_count IS NULL OR unknown_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_intelligence_success_identity
    ON candidate_intelligence_runs(
        source_snapshot_id,
        feature_set_version,
        policy_id,
        policy_version,
        ranking_version
    ) WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS idx_candidate_intelligence_runs_source
    ON candidate_intelligence_runs(source_id, started_at);

CREATE TABLE IF NOT EXISTS candidate_wallet_features (
    run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    source_wallet_key TEXT NOT NULL,
    source_rank INTEGER NOT NULL CHECK(source_rank > 0),
    source_score TEXT,
    source_metrics_json TEXT NOT NULL CHECK(json_valid(source_metrics_json)),
    effective_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    observation_count INTEGER NOT NULL CHECK(observation_count > 0),
    observed_days INTEGER NOT NULL CHECK(observed_days > 0),
    eligible_snapshot_count INTEGER NOT NULL CHECK(eligible_snapshot_count > 0),
    presence_ratio TEXT NOT NULL,
    data_age_seconds INTEGER NOT NULL CHECK(data_age_seconds >= 0),
    stale_after_seconds INTEGER NOT NULL CHECK(stale_after_seconds > 0),
    is_stale INTEGER NOT NULL CHECK(is_stale IN (0, 1)),
    previous_rank INTEGER CHECK(previous_rank IS NULL OR previous_rank > 0),
    rank_delta_previous INTEGER,
    rank_delta_1d INTEGER,
    rank_delta_7d INTEGER,
    rank_delta_30d INTEGER,
    best_rank INTEGER NOT NULL CHECK(best_rank > 0),
    worst_rank INTEGER NOT NULL CHECK(worst_rank > 0),
    rank_volatility TEXT,
    rank_stability TEXT,
    score_delta_previous TEXT,
    score_delta_1d TEXT,
    score_delta_7d TEXT,
    score_delta_30d TEXT,
    score_volatility TEXT,
    score_stability TEXT,
    data_readiness_status TEXT NOT NULL CHECK(
        data_readiness_status IN ('READY', 'PARTIAL', 'STALE', 'INVALID', 'UNKNOWN')
    ),
    readiness_reasons_json TEXT NOT NULL CHECK(json_valid(readiness_reasons_json)),
    PRIMARY KEY(run_id, wallet_id),
    UNIQUE(run_id, source_wallet_key),
    FOREIGN KEY(run_id) REFERENCES candidate_intelligence_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(wallet_id) REFERENCES canonical_wallets(wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_features_wallet
    ON candidate_wallet_features(wallet_id, calculated_at);

CREATE TABLE IF NOT EXISTS candidate_policy_evaluations (
    run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK(
        candidate_status IN ('SELECTED', 'WATCHLIST', 'INELIGIBLE')
    ),
    candidate_rank INTEGER CHECK(candidate_rank IS NULL OR candidate_rank > 0),
    policy_reasons_json TEXT NOT NULL CHECK(json_valid(policy_reasons_json)),
    PRIMARY KEY(run_id, wallet_id),
    UNIQUE(run_id, candidate_rank),
    FOREIGN KEY(run_id, wallet_id)
        REFERENCES candidate_wallet_features(run_id, wallet_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS candidate_intelligence_current (
    source_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES candidate_intelligence_runs(run_id)
);

CREATE VIEW IF NOT EXISTS candidate_trading_pool_current AS
WITH effective_age AS (
    SELECT
        f.run_id,
        f.wallet_id,
        MAX(
            f.data_age_seconds,
            MAX(0, CAST(unixepoch('now') - unixepoch(f.ingested_at) AS INTEGER))
        ) AS data_age_seconds,
        CASE
            WHEN f.is_stale = 1 OR MAX(
                f.data_age_seconds,
                MAX(0, CAST(unixepoch('now') - unixepoch(f.ingested_at) AS INTEGER))
            ) > f.stale_after_seconds THEN 1
            ELSE 0
        END AS is_stale
    FROM candidate_intelligence_current c
    JOIN candidate_wallet_features f ON f.run_id = c.run_id
)
SELECT
    f.wallet_id,
    w.chain,
    r.source_id,
    r.source_snapshot_id,
    f.source_wallet_key,
    f.source_rank,
    f.source_score,
    f.source_metrics_json,
    f.effective_at,
    f.observed_at,
    f.ingested_at,
    f.calculated_at,
    f.first_seen_at,
    f.last_seen_at,
    f.observation_count,
    f.observed_days,
    f.eligible_snapshot_count,
    f.presence_ratio,
    a.data_age_seconds,
    f.stale_after_seconds,
    a.is_stale,
    f.data_age_seconds AS calculated_data_age_seconds,
    f.is_stale AS calculated_is_stale,
    f.previous_rank,
    f.rank_delta_previous,
    f.rank_delta_1d,
    f.rank_delta_7d,
    f.rank_delta_30d,
    f.best_rank,
    f.worst_rank,
    f.rank_volatility,
    f.rank_stability,
    f.score_delta_previous,
    f.score_delta_1d,
    f.score_delta_7d,
    f.score_delta_30d,
    f.score_volatility,
    f.score_stability,
    CASE
        WHEN f.data_readiness_status = 'INVALID' THEN 'INVALID'
        WHEN a.is_stale = 1 THEN 'STALE'
        ELSE f.data_readiness_status
    END AS data_readiness_status,
    CASE
        WHEN a.is_stale = 1 AND f.data_readiness_status != 'INVALID'
            THEN json_array('source_snapshot_stale')
        ELSE f.readiness_reasons_json
    END AS readiness_reasons_json,
    f.data_readiness_status AS calculated_data_readiness_status,
    f.readiness_reasons_json AS calculated_readiness_reasons_json,
    CASE
        WHEN e.candidate_status = 'INELIGIBLE' THEN 'INELIGIBLE'
        WHEN a.is_stale = 1 THEN 'WATCHLIST'
        ELSE e.candidate_status
    END AS candidate_status,
    CASE WHEN a.is_stale = 1 THEN NULL ELSE e.candidate_rank END AS candidate_rank,
    CASE
        WHEN a.is_stale = 1 AND e.candidate_status != 'INELIGIBLE'
            THEN json_array('readiness_stale')
        ELSE e.policy_reasons_json
    END AS policy_reasons_json,
    e.candidate_status AS calculated_candidate_status,
    e.candidate_rank AS calculated_candidate_rank,
    e.policy_reasons_json AS calculated_policy_reasons_json,
    r.feature_set_version,
    r.policy_id,
    r.policy_version,
    r.ranking_version,
    r.run_id,
    r.published_at
FROM candidate_intelligence_current c
JOIN candidate_intelligence_runs r ON r.run_id = c.run_id
JOIN candidate_wallet_features f ON f.run_id = r.run_id
JOIN candidate_policy_evaluations e
    ON e.run_id = f.run_id AND e.wallet_id = f.wallet_id
JOIN canonical_wallets w ON w.wallet_id = f.wallet_id
JOIN effective_age a ON a.run_id = f.run_id AND a.wallet_id = f.wallet_id
;
