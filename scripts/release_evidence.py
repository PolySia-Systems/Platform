"""Verify and retain one explicitly requested full CI attempt for publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.classify_ci_changes import validate_projection  # noqa: E402

REPOSITORY = "PolySia-Systems/Platform"
ARTIFACTS = ("ci-policy", "polysia-release-image", "polysia-wheel", "polysia-sbom")
JOBS = (
    "changes", "quality", "container", "Windows Compatibility", "supply-chain",
    "browser-acceptance", "installation-acceptance", "CI Gate",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_run(run: dict, jobs: list[dict], workflow_id: int) -> None:
    require(
        run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("workflow_id") == workflow_id
        and run.get("path") == ".github/workflows/ci.yml"
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and bool(re.fullmatch("[0-9a-f]{40}", run.get("head_sha", "")))
        and type(run.get("id")) is int
        and type(run.get("run_attempt")) is int and run["run_attempt"] > 0,
        "release requires a successful explicit full CI run on trusted main",
    )
    for name in JOBS:
        matches = [job for job in jobs if job.get("name") == name]
        require(len(matches) == 1, f"missing or ambiguous job: {name}")
        job = matches[0]
        require(
            job.get("conclusion") == "success" and job.get("status") == "completed"
            and job.get("run_id") == run["id"]
            and job.get("run_attempt") == run["run_attempt"]
            and job.get("head_sha") == run["head_sha"],
            f"unsuccessful or mismatched job: {name}",
        )


def validate_receipt(receipt: dict, run: dict) -> None:
    require(
        receipt.get("repository") == REPOSITORY
        and receipt.get("run_id") == run["id"]
        and receipt.get("run_attempt") == run["run_attempt"],
        "policy receipt belongs to another run/attempt",
    )
    policy = validate_projection(receipt.get("policy"))
    require(
        policy["source"]["head"] == run["head_sha"]
        and policy["source"]["event"] == "workflow_dispatch"
        and policy["source"]["validation_scope"] == "full"
        and policy["source"]["run_windows"] == "true"
        and all(policy["flags"].values()),
        "release requires explicit full Windows opt-in and complete coverage",
    )


def select_artifacts(items: list[dict], run: dict) -> list[str]:
    names = []
    for prefix in ARTIFACTS:
        name = f"{prefix}-attempt-{run['run_attempt']}"
        matches = [item for item in items if item.get("name") == name]
        require(len(matches) == 1, f"missing or ambiguous artifact: {name}")
        item = matches[0]
        require(
            not item.get("expired", True)
            and item.get("workflow_run", {}).get("id") == run["id"]
            and item.get("workflow_run", {}).get("head_sha") == run["head_sha"],
            f"expired or mismatched artifact: {name}",
        )
        names.append(name)
    return names


def api(path: str) -> dict:
    return json.loads(subprocess.check_output([
        "gh", "api", f"repos/{REPOSITORY}/{path}",
    ]))


def assert_current_attempt(run: dict) -> None:
    current = api(f"actions/runs/{run['id']}")
    require(all(current.get(key) == run[key] for key in (
        "run_attempt", "head_sha", "status", "conclusion",
    )), "CI attempt changed during release preparation; select its completed attempt again")


def validate_archive(directory: Path, sha: str) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["commit"] == sha, "manifest source differs from tested revision")
    require(manifest["archive_name"] == "polysia-image.tar.gz", "unexpected image archive")
    for name, key in (
        ("platform_backup.py", "backup_job_sha256"),
        ("platform_bootstrap.py", "bootstrap_sha256"),
        ("platform_admin.py", "admin_sha256"), ("os-packages.txt", "os_packages_sha256"),
    ):
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == manifest[key],
                f"release source hash mismatch: {name}")
    with (directory / "polysia-image.tar.gz").open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == manifest["archive_sha256"],
                "release archive hash mismatch")


def main() -> None:
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_REF") == "refs/heads/main",
            "publisher requires trusted main")
    if "--recheck" in sys.argv:
        run = json.loads(Path("run.json").read_text(encoding="utf-8"))
        assert_current_attempt(run)
        return
    run_id = os.environ["CI_RUN_ID"]
    require(bool(re.fullmatch("[0-9]+", run_id)), "invalid CI run ID")
    run = api(f"actions/runs/{run_id}")
    workflow = api("actions/workflows/ci.yml")
    response = api(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs?per_page=100")
    require(response["total_count"] <= 100, "job inventory exceeds bounded coverage")
    validate_run(run, response["jobs"], workflow["id"])
    # main can advance; the selected revision must remain in its trusted history.
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", run["head_sha"], "origin/main"], check=True,
    )
    response = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    require(response["total_count"] <= 100, "artifact inventory exceeds bounded coverage")
    names = select_artifacts(response["artifacts"], run)
    for index, name in enumerate(names):
        subprocess.run([
            "gh", "run", "download", run_id, "--repo", REPOSITORY,
            "-n", name, "-D", "evidence" if index == 0 else "release",
        ], check=True)
        if index == 0:
            receipt = json.loads(Path("evidence/ci-policy.json").read_text(encoding="utf-8"))
            validate_receipt(receipt, run)
    assert_current_attempt(run)
    Path("run.json").write_text(json.dumps(run), encoding="utf-8")


if __name__ == "__main__":
    main()
