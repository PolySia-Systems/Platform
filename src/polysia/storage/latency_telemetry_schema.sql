-- Additive observational telemetry. Never referenced by financial FKs.
-- Independent schema_version; Continuous Shadow remains at v4.

CREATE TABLE IF NOT EXISTS latency_telemetry_metadata (
    schema_version INTEGER PRIMARY KEY CHECK (schema_version = 1),
    initialized_at TEXT NOT NULL,
    policy_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS latency_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    performance_contract_version TEXT NOT NULL,
    component TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ns INTEGER CHECK (duration_ns IS NULL OR duration_ns >= 0),
    started_at_utc TEXT NOT NULL,
    venue_id TEXT,
    endpoint_id TEXT,
    host_id TEXT,
    provider TEXT,
    region TEXT,
    deploy_sha TEXT,
    runtime_version TEXT,
    image_digest TEXT,
    configuration_version TEXT,
    policy_version TEXT,
    poll_run_id TEXT,
    experiment_id TEXT,
    recorded_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_latency_spans_started
    ON latency_spans (started_at_utc);
CREATE INDEX IF NOT EXISTS idx_latency_spans_trace
    ON latency_spans (trace_id, started_at_utc);
CREATE INDEX IF NOT EXISTS idx_latency_spans_operation
    ON latency_spans (operation, started_at_utc);

CREATE TABLE IF NOT EXISTS latency_measurements (
    measurement_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    value_ns INTEGER CHECK (value_ns IS NULL OR value_ns >= 0),
    started_at_utc TEXT NOT NULL,
    venue_id TEXT,
    endpoint_id TEXT,
    host_id TEXT,
    provider TEXT,
    region TEXT,
    deploy_sha TEXT,
    runtime_version TEXT,
    image_digest TEXT,
    configuration_version TEXT,
    policy_version TEXT,
    poll_run_id TEXT,
    experiment_id TEXT,
    recorded_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_latency_measurements_started
    ON latency_measurements (started_at_utc);
CREATE INDEX IF NOT EXISTS idx_latency_measurements_kind
    ON latency_measurements (kind, started_at_utc);

CREATE TABLE IF NOT EXISTS latency_aggregates (
    bucket_start_utc TEXT NOT NULL,
    operation TEXT NOT NULL,
    deploy_sha TEXT NOT NULL,
    host_id TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    p50_ns INTEGER,
    p95_ns INTEGER,
    p99_ns INTEGER,
    variance_ns2 TEXT,
    best_observed_ns INTEGER,
    confidence TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    PRIMARY KEY (bucket_start_utc, operation, deploy_sha, host_id)
);

CREATE TABLE IF NOT EXISTS latency_telemetry_health (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    telemetry_errors INTEGER NOT NULL DEFAULT 0,
    dropped_measurements INTEGER NOT NULL DEFAULT 0,
    buffer_capacity INTEGER NOT NULL,
    buffer_usage INTEGER NOT NULL,
    last_successful_flush_utc TEXT,
    last_telemetry_write_duration_ns INTEGER,
    probe_failures INTEGER NOT NULL DEFAULT 0,
    last_successful_probe_utc TEXT,
    artifact_written_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS latency_telemetry_copy_state (
    source_fingerprint TEXT PRIMARY KEY,
    copied_at TEXT NOT NULL,
    span_count INTEGER NOT NULL,
    measurement_count INTEGER NOT NULL
);
