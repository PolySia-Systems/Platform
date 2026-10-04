"""Intentionally shared public-contract fixture for adapter/application/CLI tests."""

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def wallet_intelligence_artifact() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).parent / "fixtures/wallet_intelligence/v1.json").read_text(encoding="utf-8")
    )
