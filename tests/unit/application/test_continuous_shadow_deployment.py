from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_continuous_shadow_service_is_data_only_and_has_no_execution_command() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    section = compose.split(
        "  wallet-intelligence-shadow-portfolio:", maxsplit=1
    )[1].split("\n  wallet-intelligence-handoff:", maxsplit=1)[0]

    assert 'LIVE_TRADING_ENABLED: "false"' in section
    assert "TRADING_MODE: DATA_ONLY" in section
    assert "portfolio-sync" in section
    assert "--loop" in section
    assert "continuous-shadow.json" in section
    assert "container_name: polysia-shadow-portfolio-worker" in section
    assert 'restart: "no"' in section
    assert "tiny-execute" not in section
    assert "tiny-copy" not in section
    assert "cancel-order" not in section
    assert "private" not in section.casefold()

    service = (
        ROOT
        / "deploy"
        / "systemd"
        / "polysia-wallet-intelligence-shadow-portfolio.service"
    ).read_text(encoding="utf-8")
    assert "Type=simple" in service
    assert "Restart=on-failure" in service
    assert "compose --profile wallet-intelligence up --abort-on-container-exit" in service
    assert (
        "compose --profile wallet-intelligence rm -fs "
        "wallet-intelligence-shadow-portfolio"
    ) in service
    assert "rm -fs --timeout" not in service
    assert "compose run" not in service
    assert "tiny-execute" not in service


def test_fast_timer_is_additive_and_stage4a_ten_minute_timer_is_preserved() -> None:
    fast = (
        ROOT
        / "deploy"
        / "systemd"
        / "polysia-wallet-intelligence-shadow-portfolio.timer"
    ).read_text(encoding="utf-8")
    stage4a = (
        ROOT / "deploy" / "systemd" / "polysia-wallet-intelligence-shadow.timer"
    ).read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* *:*:00 UTC" in fast
    assert "Persistent=true" in fast
    assert "OnCalendar=*-*-* *:00/10:00 UTC" in stage4a
