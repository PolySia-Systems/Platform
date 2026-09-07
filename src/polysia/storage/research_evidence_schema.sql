PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS research_evidence_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_intervals (
    interval_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    validity TEXT NOT NULL,
    reason TEXT NOT NULL,
    code_sha TEXT,
    configuration_digest TEXT,
    policy_version TEXT NOT NULL,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS research_events (
    evidence_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    classification TEXT NOT NULL,
    market_reference TEXT,
    outcome_reference TEXT,
    side TEXT,
    price TEXT,
    size TEXT,
    source_time_utc TEXT,
    observed_time_utc TEXT NOT NULL,
    receive_monotonic_ns INTEGER NOT NULL,
    normalize_monotonic_ns INTEGER NOT NULL,
    attribution_status TEXT NOT NULL,
    leader_alias TEXT,
    confirmation TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    source_event_id TEXT,
    provenance_json TEXT NOT NULL,
    related_evidence_id TEXT,
    run_id TEXT NOT NULL,
    interval_id TEXT NOT NULL,
    FOREIGN KEY (interval_id) REFERENCES research_intervals (interval_id)
);

CREATE INDEX IF NOT EXISTS research_events_source_observed
    ON research_events (source_id, observed_time_utc);
CREATE INDEX IF NOT EXISTS research_events_kind_class
    ON research_events (event_kind, classification);

CREATE TABLE IF NOT EXISTS research_watermarks (
    source_id TEXT PRIMARY KEY,
    last_source_time_utc TEXT,
    last_evidence_id TEXT,
    last_observed_time_utc TEXT NOT NULL,
    reconnect_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS research_decisions (
    decision_id TEXT PRIMARY KEY,
    interval_id TEXT NOT NULL,
    observed_time_utc TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    code_sha TEXT,
    configuration_digest TEXT,
    FOREIGN KEY (interval_id) REFERENCES research_intervals (interval_id)
);

CREATE TABLE IF NOT EXISTS research_duplicate_counts (
    evidence_id TEXT PRIMARY KEY,
    duplicate_count INTEGER NOT NULL,
    updated_at_utc TEXT NOT NULL
);
