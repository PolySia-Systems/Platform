from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from typer.testing import CliRunner

from polysia.application.services.wallet_preparation import WalletPreparationConfig
from polysia.cli import app

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs/10-operations/research-shadow-ui-contracts.schema.json"
EXAMPLES = ROOT / "docs/10-operations/research-shadow-ui-contracts.examples.json"
PREPARATION_SCHEMA = ROOT / "docs/10-operations/wallet-preparation.schema.json"
PREPARATION_EXAMPLE = ROOT / "docs/10-operations/wallet-preparation.example.json"


def test_preparation_policy_example_matches_schema_and_application_contract() -> None:
    schema = json.loads(PREPARATION_SCHEMA.read_text(encoding="utf-8"))
    example = json.loads(PREPARATION_EXAMPLE.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(example, schema)
    policy = WalletPreparationConfig(**example)
    assert policy.mode == "adaptive"
    assert policy.candidate_pool_size > policy.maximum_wallets


def test_versioned_workflow_examples_validate_against_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker(),
    )
    assert len(examples) == 11
    for example in examples:
        validator.validate(example)
    invalid = dict(examples[5])
    invalid.pop("command_id")
    assert list(validator.iter_errors(invalid))


def test_actual_capabilities_command_obeys_versioned_contract() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    result = CliRunner().invoke(app, [
        "wallet-intelligence", "portfolio-capabilities",
    ])
    assert result.exit_code == 0, result.output
    jsonschema.validate(json.loads(result.stdout), schema)


def test_preflight_failure_obeys_versioned_contract() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    result = CliRunner().invoke(app, [
        "wallet-intelligence", "portfolio-preflight", "--wallet-count", "5",
        "--code-sha", "a" * 40,
    ])
    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "FAILED"
    jsonschema.validate(payload, schema)
