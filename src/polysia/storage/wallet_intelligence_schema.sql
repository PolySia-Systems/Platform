PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS wallet_intelligence_metadata (
    schema_version INTEGER PRIMARY KEY CHECK(schema_version = 1),
    initialized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_source_runs (
    run_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed', 'quarantined')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    source_total_pages INTEGER CHECK(source_total_pages IS NULL OR source_total_pages > 0),
    record_count INTEGER CHECK(record_count IS NULL OR record_count > 0),
    schema_version TEXT,
    dataset_digest TEXT,
    error_code TEXT,
    error_message TEXT,
    warning_code TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_source_one_running
    ON candidate_source_runs (source_id) WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_candidate_source_runs_schedule
    ON candidate_source_runs (source_id, scheduled_for, started_at);

CREATE INDEX IF NOT EXISTS idx_candidate_source_runs_status
    ON candidate_source_runs (source_id, status, completed_at);

CREATE TABLE IF NOT EXISTS candidate_wallet_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_total_pages INTEGER NOT NULL CHECK(source_total_pages > 0),
    record_count INTEGER NOT NULL CHECK(record_count > 0),
    dataset_digest TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES candidate_source_runs(run_id),
    UNIQUE (source_id, snapshot_id)
);

-- Protected identity table. The SQLite file and its directory must remain private.
-- Reports and ordinary queries use wallet_key, never external_wallet_id.
CREATE TABLE IF NOT EXISTS candidate_wallet_identities (
    wallet_key TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    external_wallet_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (source_id, external_wallet_id)
);

CREATE TABLE IF NOT EXISTS candidate_wallet_snapshot_rows (
    snapshot_id TEXT NOT NULL,
    wallet_key TEXT NOT NULL,
    source_rank INTEGER NOT NULL CHECK(source_rank > 0),
    source_page INTEGER NOT NULL CHECK(source_page > 0),
    metrics_json TEXT NOT NULL CHECK(json_valid(metrics_json)),
    row_digest TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, wallet_key),
    UNIQUE (snapshot_id, source_rank),
    FOREIGN KEY (snapshot_id) REFERENCES candidate_wallet_snapshots(snapshot_id)
        ON DELETE CASCADE,
    FOREIGN KEY (wallet_key) REFERENCES candidate_wallet_identities(wallet_key)
);

CREATE INDEX IF NOT EXISTS idx_candidate_snapshot_rows_wallet
    ON candidate_wallet_snapshot_rows (wallet_key, snapshot_id);

CREATE TABLE IF NOT EXISTS candidate_current_snapshots (
    source_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_id, snapshot_id)
        REFERENCES candidate_wallet_snapshots(source_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS candidate_source_quarantines (
    quarantine_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    sample_gzip BLOB NOT NULL,
    sample_sha256 TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES candidate_source_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_quarantines_source_captured
    ON candidate_source_quarantines (source_id, captured_at);
