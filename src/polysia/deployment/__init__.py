"""Deployment and release handoff helpers."""

from polysia.deployment.automation import (
    DeploymentAutomationResult,
    DeploymentAutomationStep,
    run_deployment_automation,
)
from polysia.deployment.final_handoff import render_final_handoff_markdown
from polysia.deployment.manifest import (
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
