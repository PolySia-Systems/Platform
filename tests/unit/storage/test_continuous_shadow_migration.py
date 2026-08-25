from __future__ import annotations

import sqlite3
from pathlib import Path

from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.dynamic_shadow import DynamicShadowRepository


def test_stage4b_schema_is_additive_and_keeps_stage4a_schema_v1(tmp_path: Path) -> None:
    database = tmp_path / "wallet-intelligence.sqlite3"
    DynamicShadowRepository(database).initialize()

    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()

    connection = sqlite3.connect(database)
    try:
        dynamic_version = connection.execute(
            "SELECT schema_version FROM dynamic_shadow_metadata"
        ).fetchone()[0]
        continuous_version = connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0]
        dynamic_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'dynamic_shadow_evaluations'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert dynamic_version == 1
    assert continuous_version == 2
    assert "evaluation_status" in dynamic_sql
