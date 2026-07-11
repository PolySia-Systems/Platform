"""Deployment and release handoff helpers."""

from pm_trader.deployment.automation import (
    DeploymentAutomationResult,
    DeploymentAutomationStep,
    run_deployment_automation,
)
from pm_trader.deployment.final_handoff import render_final_handoff_markdown
from pm_trader.deployment.manifest import (
    GitSnapshot,
    PackageMetadata,
    ReleaseManifest,
    ReleaseManifestCheck,
    build_release_manifest,
)

__all__ = [
    "DeploymentAutomationResult",
    "DeploymentAutomationStep",
    "GitSnapshot",
    "PackageMetadata",
    "ReleaseManifest",
    "ReleaseManifestCheck",
    "build_release_manifest",
    "render_final_handoff_markdown",
    "run_deployment_automation",
]
