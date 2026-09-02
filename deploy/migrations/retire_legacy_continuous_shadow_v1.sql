-- One-time post-cutover retirement of the frozen Stage 4B schema from the
-- Wallet Intelligence database. Run only in explicit maintenance mode after
-- verified backups of both SQLite stores. The immutable cutover backup remains
-- the rollback and historical source of truth; this script does not VACUUM.
PRAGMA foreign_keys = OFF;

CREATE TEMP TABLE _continuous_shadow_retirement_guard (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

INSERT INTO _continuous_shadow_retirement_guard (valid)
SELECT
    EXISTS(
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'wallet_intelligence_metadata'
    )
    AND EXISTS(
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'continuous_shadow_metadata'
    )
    AND EXISTS(
        SELECT 1 FROM continuous_shadow_metadata WHERE schema_version = 4
    )
    AND NOT EXISTS(
        SELECT 1 FROM continuous_shadow_poll_runs WHERE status = 'running'
    );

BEGIN IMMEDIATE;

DROP VIEW IF EXISTS continuous_shadow_portfolio_current;
DROP TABLE IF EXISTS continuous_shadow_liquidity_consumption;
DROP TABLE IF EXISTS continuous_shadow_position_marks;
DROP TABLE IF EXISTS continuous_shadow_ledger;
DROP TABLE IF EXISTS continuous_shadow_evaluations;
DROP TABLE IF EXISTS continuous_shadow_follower_attribution;
DROP TABLE IF EXISTS continuous_shadow_positions;
DROP TABLE IF EXISTS continuous_shadow_terminal_book_cache;
DROP TABLE IF EXISTS continuous_shadow_checkpoint;
DROP TABLE IF EXISTS continuous_shadow_event_journal;
DROP TABLE IF EXISTS continuous_shadow_poll_runs;
DROP TABLE IF EXISTS continuous_shadow_portfolios;
DROP TABLE IF EXISTS continuous_shadow_candidates;
DROP TABLE IF EXISTS continuous_shadow_experiments;
DROP TABLE IF EXISTS continuous_shadow_leases;
DROP TABLE IF EXISTS continuous_shadow_selection_memberships;
DROP TABLE IF EXISTS continuous_shadow_wallets;
DROP TABLE IF EXISTS continuous_shadow_selection_snapshots;
DROP TABLE IF EXISTS continuous_shadow_metadata;

COMMIT;
DROP TABLE _continuous_shadow_retirement_guard;
PRAGMA foreign_keys = ON;
