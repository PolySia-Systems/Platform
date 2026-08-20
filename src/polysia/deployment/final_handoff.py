from __future__ import annotations

from polysia.deployment.automation import DeploymentAutomationResult


def render_final_handoff_markdown(result: DeploymentAutomationResult) -> str:
    """Render a sanitized final project handoff."""

    manifest = result.release_manifest
    package = manifest.package.to_dict()
    git = manifest.git.to_dict()
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Final Handoff",
            "",
            "This handoff is generated from sanitized local checks. It does not include "
            "private keys, wallet addresses, allowlisted token values, transaction hashes, "
            "or raw live order responses.",
            "",
            "## Status",
            "",
            f"- Final handoff status: {result.status}",
            f"- Deployment readiness: {result.readiness.status}",
            f"- Geoblock readiness: {_readiness_check_status(result, 'geoblock')}",
            f"- Release manifest: {manifest.status}",
            f"- Package: {package['name']} {package['version']}",
            f"- CLI entrypoint: {package['cli_entrypoint']}",
            f"- Git branch: {git['branch']}",
            f"- Git commit: {git['commit']}",
            f"- Git clean: {git['clean']}",
            f"- Generated at: {result.timestamp.isoformat()}",
            "",
            "## Quality Gates",
            "",
            *_quality_gate_lines(result),
            "",
            "## Generated Artifacts",
            "",
            *_artifact_lines(result),
            "",
            "## Safe Operating Baseline",
            "",
            "- Default runtime mode remains DATA_ONLY.",
            "- Live submission remains disabled unless LIVE mode and explicit enable "
            "flags are set.",
            "- Live submit and cancel operations remain token-allowlist gated.",
            "- Tiny live order caps remain enforced by settings and risk checks.",
            "- Live order placement is blocked unless the official Polymarket geoblock "
            "endpoint returns blocked=false.",
            "- Paper trading, replay backtests, reports, runbooks, and manifests do "
            "not call live trading APIs.",
            "",
            "## Final Operator Commands",
            "",
            "- `python -m polysia.cli system health`",
            "- `python -m polysia.cli ops deployment-automation --require-clean-git "
            "--include-live-runbook`",
            "- `python -m polysia.cli system runbook --include-live`",
            "- `python -m polysia.cli ops release-manifest --require-clean-git`",
            "- `python -m polysia.cli ops post-live-reconciliation --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli system observability --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli research shadow-public --auto-btc-5m "
            "--max-events 100 --output-dir .\\release-artifacts`",
            "- `python -m polysia.cli research evaluate-extended --input "
            ".\\release-artifacts\\shadow-run-real-data.json --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli ops tiny-live-monitor --output-dir "
            ".\\release-artifacts --redact-secrets`",
            "- `python -m polysia.cli live controlled-second-attempt --auto-btc-5m "
            "--side BUY --outcome YES --max-notional 1.00 --order-type FOK "
            "--dry-run --output-dir .\\release-artifacts`",
            "- `python -m polysia.cli ops production-gap-audit --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli ops main-merge-review --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli ops local-release-closeout --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli ops reconcile-account --output-dir "
            ".\\release-artifacts`",
            "- `python -m polysia.cli live manual-intervention-test --auto-btc-5m "
            "--outcome YES --side BUY --max-notional 1.00 --order-type FOK "
            "--dry-run --output-dir .\\release-artifacts`",
            "",
            "## Stop Conditions",
            "",
            "- Any quality gate fails.",
            "- Deployment readiness or release manifest is blocked.",
            "- Generated output contains secret values, wallet addresses, token values, "
            "or transaction hashes.",
            "- A live workflow would move beyond dry-run before manual operator approval.",
            "",
        )
    )


def _quality_gate_lines(result: DeploymentAutomationResult) -> tuple[str, ...]:
    return tuple(
        f"- {gate.name}: {gate.status} (`{' '.join(gate.command)}`)"
        for gate in result.quality_gates
    )


def _readiness_check_status(result: DeploymentAutomationResult, name: str) -> str:
    for check in result.readiness.checks:
        if check.name == name:
            return check.status
    return "missing"


def _artifact_lines(result: DeploymentAutomationResult) -> tuple[str, ...]:
    return tuple(
        f"- {name}: `{path}`"
        for name, path in sorted(result.artifacts.items())
    )
