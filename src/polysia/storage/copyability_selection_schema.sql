PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS copyability_selection_metadata (
    schema_version INTEGER PRIMARY KEY CHECK(schema_version = 1),
    initialized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copyability_selection_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    stage2_run_id TEXT NOT NULL,
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
    alpha_count INTEGER CHECK(alpha_count IS NULL OR alpha_count >= 0),
    stress_count INTEGER CHECK(stress_count IS NULL OR stress_count >= 0),
    live_review_count INTEGER CHECK(live_review_count IS NULL OR live_review_count >= 0),
    rejected_count INTEGER CHECK(rejected_count IS NULL OR rejected_count >= 0),
    watchlist_count INTEGER CHECK(watchlist_count IS NULL OR watchlist_count >= 0),
    overlap_count INTEGER CHECK(overlap_count IS NULL OR overlap_count >= 0),
    FOREIGN KEY(stage2_run_id) REFERENCES candidate_intelligence_runs(run_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_copyability_selection_success_identity
    ON copyability_selection_runs(
        stage2_run_id,
        feature_set_version,
        policy_id,
        policy_version,
        ranking_version
    ) WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS idx_copyability_selection_runs_source
    ON copyability_selection_runs(source_id, started_at);

CREATE TABLE IF NOT EXISTS copyability_wallet_scores (
    run_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    performance_score TEXT,
    recent_edge_score TEXT,
    activity_score TEXT,
    copyability_score TEXT,
    hedging_risk_score TEXT,
    confidence_score TEXT,
    stability_score TEXT,
    alpha_score TEXT,
    status TEXT NOT NULL CHECK(status IN ('REJECTED', 'WATCHLIST', 'SELECTED')),
    reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json)),
    effective_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    PRIMARY KEY(run_id, wallet_id),
    FOREIGN KEY(run_id) REFERENCES copyability_selection_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(wallet_id) REFERENCES canonical_wallets(wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_copyability_scores_status
    ON copyability_wallet_scores(run_id, status, wallet_id);

CREATE TABLE IF NOT EXISTS copyability_pool_memberships (
    run_id TEXT NOT NULL,
    pool_id TEXT NOT NULL CHECK(
        pool_id IN ('SHADOW_ALPHA', 'SHADOW_STRESS', 'LIVE_REVIEW_CANDIDATE', 'REJECTED')
    ),
    wallet_id TEXT NOT NULL,
    pool_rank INTEGER CHECK(pool_rank IS NULL OR pool_rank > 0),
    reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json)),
    PRIMARY KEY(run_id, pool_id, wallet_id),
    UNIQUE(run_id, pool_id, pool_rank),
    FOREIGN KEY(run_id, wallet_id)
        REFERENCES copyability_wallet_scores(run_id, wallet_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS copyability_selection_current (
    source_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES copyability_selection_runs(run_id)
);

CREATE VIEW IF NOT EXISTS copyability_pools_current AS
SELECT
    s.wallet_id,
    r.source_id,
    r.source_snapshot_id,
    r.stage2_run_id,
    m.pool_id,
    m.pool_rank,
    s.status,
    s.alpha_score,
    s.copyability_score,
    s.performance_score,
    s.recent_edge_score,
    s.activity_score,
    s.hedging_risk_score,
    s.confidence_score,
    s.stability_score,
    m.reasons_json,
    s.effective_at,
    s.observed_at,
    s.ingested_at,
    s.calculated_at,
    r.feature_set_version,
    r.policy_id,
    r.policy_version,
    r.ranking_version,
    r.run_id,
    c.published_at
FROM copyability_selection_current c
JOIN copyability_selection_runs r ON r.run_id = c.run_id
JOIN copyability_pool_memberships m ON m.run_id = r.run_id
JOIN copyability_wallet_scores s
    ON s.run_id = m.run_id AND s.wallet_id = m.wallet_id
;
