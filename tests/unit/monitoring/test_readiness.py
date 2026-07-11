from __future__ import annotations

from datetime import UTC, datetime

from polysia.adapters.geoblock import GeoblockStatus
from polysia.config.settings import AppSettings, TradingMode
from polysia.monitoring.readiness import build_deployment_readiness


def test_deployment_readiness_passes_default_safe_project(tmp_path) -> None:
    project_root = ready_project(tmp_path)

    report = build_deployment_readiness(
        settings=AppSettings(),
        project_root=project_root,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    payload = report.to_dict()

    assert payload["status"] == "ready"
    assert payload["summary"] == {"fail": 0, "pass": 7, "warn": 0}
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_deployment_readiness_blocks_live_mode_without_guardrails(tmp_path) -> None:
    project_root = ready_project(tmp_path)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_PRIVATE_KEY=None,
        POLYMARKET_FUNDER_ADDRESS="",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="",
    )

    report = build_deployment_readiness(settings=settings, project_root=project_root)

    assert report.status == "blocked"
    failed_checks = [check for check in report.checks if check.status == "fail"]
    assert [check.name for check in failed_checks] == ["live-guardrails"]
    assert "POLYMARKET_PRIVATE_KEY" in failed_checks[0].message
    assert "POLYMARKET_FUNDER_ADDRESS" in failed_checks[0].message
    assert "POLYMARKET_LIVE_TOKEN_ALLOWLIST" in failed_checks[0].message


def test_deployment_readiness_is_sanitized_for_configured_live_mode(tmp_path) -> None:
    project_root = ready_project(tmp_path)
    settings = AppSettings(
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING_ENABLED=True,
        POLYMARKET_FUNDER_ADDRESS="0xfunder",
        POLYMARKET_WALLET_ADDRESS="0xwallet",
        POLYMARKET_LIVE_TOKEN_ALLOWLIST="token-secret",
        **{"POLYMARKET_PRIVATE_KEY": "not-for-output"},
    )

    payload = build_deployment_readiness(
        settings=settings,
        project_root=project_root,
    ).to_dict()

    assert payload["status"] == "ready"
    assert "not-for-output" not in str(payload)
    assert "0xwallet" not in str(payload)
    assert "token-secret" not in str(payload)


def test_deployment_readiness_blocks_unsafe_env_example(tmp_path) -> None:
    project_root = ready_project(tmp_path)
    (project_root / ".env.example").write_text(
        "\n".join(
            (
                "TRADING_MODE=LIVE",
                "LIVE_TRADING_ENABLED=true",
                "POLYMARKET_PRIVATE_KEY = filled",
            )
        ),
        encoding="utf-8",
    )

    report = build_deployment_readiness(settings=AppSettings(), project_root=project_root)

    assert report.status == "blocked"
    assert _check_by_name(report, "env-example").status == "fail"


def test_deployment_readiness_can_require_clean_git(tmp_path) -> None:
    project_root = ready_project(tmp_path)

    dirty_report = build_deployment_readiness(
        settings=AppSettings(),
        project_root=project_root,
        require_clean_git=True,
        git_status_reader=lambda _root: " M README.md\n",
    )
    clean_report = build_deployment_readiness(
        settings=AppSettings(),
        project_root=project_root,
        require_clean_git=True,
        git_status_reader=lambda _root: "",
    )

    assert dirty_report.status == "blocked"
    assert _check_by_name(dirty_report, "clean-git").status == "fail"
    assert clean_report.status == "ready"
    assert _check_by_name(clean_report, "clean-git").status == "pass"


def test_deployment_readiness_reports_geoblock_status(tmp_path) -> None:
    project_root = ready_project(tmp_path)
    allowed = build_deployment_readiness(
        settings=AppSettings(),
        project_root=project_root,
        geoblock_status=GeoblockStatus(
            status="allowed",
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            blocked=False,
        ),
    )
    blocked = build_deployment_readiness(
        settings=AppSettings(),
        project_root=project_root,
        geoblock_status=GeoblockStatus(
            status="blocked",
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            blocked=True,
        ),
    )

    assert _check_by_name(allowed, "geoblock").status == "pass"
    assert blocked.status == "blocked"
    assert _check_by_name(blocked, "geoblock").status == "fail"


def ready_project(tmp_path):
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
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
    return tmp_path


def _check_by_name(report, name: str):
    return next(check for check in report.checks if check.name == name)
