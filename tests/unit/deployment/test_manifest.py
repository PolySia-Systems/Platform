from __future__ import annotations

from datetime import UTC, datetime

from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.deployment.manifest import build_release_manifest


def test_release_manifest_passes_ready_project(tmp_path) -> None:
    project_root = ready_project(tmp_path)

    manifest = build_release_manifest(
        settings=AppSettings(),
        project_root=project_root,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        git_runner=clean_git,
    )
    payload = manifest.to_dict()

    assert payload["status"] == "ready"
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert payload["summary"] == {"fail": 0, "pass": 4, "warn": 0}
    assert payload["package"]["name"] == "polymarket-trading-system"
    assert payload["package"]["cli_entrypoint"] == "pm_trader.cli:app"
    assert payload["git"]["clean"] is True
    assert payload["readiness"]["status"] == "ready"


def test_release_manifest_blocks_missing_cli_entrypoint(tmp_path) -> None:
    project_root = ready_project(tmp_path)
    (project_root / "pyproject.toml").write_text(
        """
[build-system]
build-backend = "hatchling.build"

[project]
name = "polymarket-trading-system"
version = "0.1.0"
requires-python = ">=3.11"

[tool.hatch.build.targets.wheel]
packages = ["src/pm_trader"]
""".strip(),
        encoding="utf-8",
    )

    manifest = build_release_manifest(
        settings=AppSettings(),
        project_root=project_root,
        git_runner=clean_git,
    )

    assert manifest.status == "blocked"
    metadata_check = _check_by_name(manifest, "package-metadata")
    assert metadata_check.status == "fail"
    assert "cli_entrypoint" in metadata_check.message


def test_release_manifest_blocks_dirty_git_when_required(tmp_path) -> None:
    manifest = build_release_manifest(
        settings=AppSettings(),
        project_root=ready_project(tmp_path),
        require_clean_git=True,
        git_runner=dirty_git,
    )

    assert manifest.status == "blocked"
    assert _check_by_name(manifest, "git-snapshot").status == "fail"


def test_release_manifest_is_sanitized_for_live_settings(tmp_path) -> None:
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    payload = build_release_manifest(
        settings=settings,
        project_root=ready_project(tmp_path),
        git_runner=clean_git,
    ).to_dict()

    assert payload["status"] == "ready"
    assert "not-for-output" not in str(payload)
    assert "0xwallet" not in str(payload)
    assert "token-secret" not in str(payload)


def ready_project(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "docs" / "OPERATOR_RUNBOOK.md").write_text("# Runbook\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "TRADING_MODE=DATA_ONLY",
                "LIVE_TRADING_ENABLED=false",
                "POLYMARKET_PRIVATE_KEY" + "=",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            (
                ".env",
                ".env.*",
                "!.env.example",
                "*.key",
                "*.pem",
                "*.sqlite3",
                "secrets/",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
build-backend = "hatchling.build"

[project]
name = "polymarket-trading-system"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
pm-trader = "pm_trader.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/pm_trader"]
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


def clean_git(_root, command: tuple[str, ...]) -> str:
    if command == ("git", "branch", "--show-current"):
        return "main\n"
    if command == ("git", "rev-parse", "--short", "HEAD"):
        return "abc1234\n"
    if command == ("git", "status", "--short"):
        return ""
    raise AssertionError(f"unexpected git command: {command}")


def dirty_git(_root, command: tuple[str, ...]) -> str:
    if command == ("git", "status", "--short"):
        return " M README.md\n"
    return clean_git(_root, command)


def _check_by_name(manifest, name: str):
    return next(check for check in manifest.checks if check.name == name)
