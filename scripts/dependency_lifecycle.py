"""Bounded metadata discovery and read-only dependency generation/health checks."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from polysia.developer.dependency_preflight import input_hashes  # noqa: E402
from scripts import dependency_locks as locks  # noqa: E402
from scripts.dependency_policy import DEV_LOCK, RUNTIME_LOCK, parse_lock_pins  # noqa: E402
from scripts.dependency_provenance import FILES, binding, digest, seal  # noqa: E402

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.version import InvalidVersion, Version


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def metadata(name: str, version: str | None = None) -> dict:
    suffix = f"/{version}" if version else ""
    url = f"https://pypi.org/pypi/{name}{suffix}/json"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise RuntimeError("registry metadata denied or unavailable") from None
        except urllib.error.URLError, TimeoutError:
            pass
        if attempt < 2:
            time.sleep(2**attempt)
    raise RuntimeError("registry metadata retry budget exhausted")


def inspect_package(name: str, current: str, runtime: bool) -> dict:
    observed = utc_now()
    source = f"https://pypi.org/pypi/{name}/json"
    try:
        project, installed = metadata(name), metadata(name, current)
        releases = []
        for text, files in project["releases"].items():
            try:
                version = Version(text)
            except InvalidVersion:
                continue
            usable = [f for f in files if not f.get("yanked")]
            if not version.is_prerelease and not version.is_devrelease and usable:
                releases.append((version, text, usable))
        if not releases:
            raise ValueError("no stable release")
        _, latest, files = max(releases)
        compatible = any(
            SpecifierSet(f.get("requires_python") or "").contains("3.14.8") for f in files
        )
        return dict(
            package=name,
            resolved=current,
            latest_published_stable=latest,
            scope="runtime" if runtime else "development/build",
            source=source,
            observed_at=observed,
            coverage="complete",
            requires_python=sorted({f.get("requires_python") or "" for f in files}),
            supports_python314=compatible,
            published_wheel=any(f.get("packagetype") == "bdist_wheel" for f in files),
            current_yanked=bool(installed["urls"])
            and all(f.get("yanked") for f in installed["urls"]),
            parent_requirements=installed["info"].get("requires_dist") or [],
            state="current" if latest == current else "review_candidate",
            owner="Platform dependency maintainer",
            tested="UNKNOWN",
            installed="UNKNOWN",
            advisory_ids=sorted(v["id"] for v in installed.get("vulnerabilities", [])),
            advisory_status="PyPI response; strict candidate OSV gate still required",
            next_action="Review coherent resolver delta and required CI before disposition",
            review_trigger="Next weekly scan, advisory, parent release or compatibility change",
        )
    except RuntimeError, ValueError, KeyError:
        return dict(
            package=name,
            resolved=current,
            source=source,
            observed_at=observed,
            coverage="UNKNOWN",
            state="metadata_failed",
            retryable=True,
            next_action="Retry bounded registry scan; preserve prior complete observation",
        )


def parent_edges(items: list[dict], declarations: list[str]) -> dict[str, list[str]]:
    extras: dict[str, set[str]] = {}
    for text in declarations:
        requirement = Requirement(text)
        extras.setdefault(requirement.name.lower().replace("_", "-"), set()).update(
            requirement.extras
        )
    edges: dict[str, list[str]] = {}
    changed = True
    while changed:
        changed = False
        for item in items:
            for text in item.get("parent_requirements", []):
                requirement = Requirement(text)
                environments = []
                for platform, system in (("linux", "Linux"), ("win32", "Windows")):
                    for extra in {"", *extras.get(item["package"], set())}:
                        environments.append(
                            dict(
                                default_environment(),
                                python_version="3.14",
                                python_full_version="3.14.8",
                                sys_platform=platform,
                                platform_system=system,
                                extra=extra,
                            )
                        )
                if requirement.marker and not any(
                    requirement.marker.evaluate(env) for env in environments
                ):
                    continue
                child = requirement.name.lower().replace("_", "-")
                edge = f"{item['package']}: {text}"
                if edge not in edges.setdefault(child, []):
                    edges[child].append(edge)
                active = extras.setdefault(child, set())
                if not requirement.extras <= active:
                    active.update(requirement.extras)
                    changed = True
    return edges


def scan(root: Path) -> dict:
    runtime = parse_lock_pins((root / RUNTIME_LOCK).read_text(encoding="utf-8"))
    dev = parse_lock_pins((root / DEV_LOCK).read_text(encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(inspect_package, name, version, name in runtime)
            for name, version in sorted(dev.items())
        ]
        items = [future.result() for future in futures]
    manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declarations = (
        manifest["project"]["dependencies"]
        + manifest["project"].get("optional-dependencies", {}).get("dev", [])
        + manifest["build-system"]["requires"]
    )
    parents = parent_edges(items, declarations)
    for item in items:
        item["parent_constraints"] = parents.get(item["package"], [])
        if item.get("latest_published_stable"):
            item["candidate_blocked_by"] = [
                edge
                for edge in item["parent_constraints"]
                if not Requirement(edge.split(": ", 1)[1]).specifier.contains(
                    item["latest_published_stable"]
                )
            ]
            if item["candidate_blocked_by"] or not item["supports_python314"]:
                item["state"] = "held_constraint"
                item["next_action"] = "Retain pin; reassess on parent/Python compatibility release"
    complete = all(item["coverage"] == "complete" for item in items)
    actionable = any(item.get("advisory_ids") or item.get("current_yanked") for item in items)
    inventory = [
        {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "sha256": digest(path),
            "owner": "Platform dependency maintainer",
            "status": "declared; not installed-state evidence",
            "declared_versions": sorted(
                set(
                    re.findall(
                        r"(?:[0-9]+\.)+[0-9]+(?:[a-z][a-z0-9]*)?", path.read_text(encoding="utf-8")
                    )
                )
            )[:100],
            "review_trigger": "Weekly review, source change or upstream support change",
        }
        for pattern in (
            ".github/workflows/*.yml",
            ".github/actions/**/action.yml",
            ".github/dependabot.yml",
            "Dockerfile",
            "environment.yml",
            "locks/conda*.lock",
            ".python-version",
            "deploy/*bootstrap*",
            "deploy/*install*",
            ".pre-commit-config.yaml",
        )
        for path in root.glob(pattern)
        if path.is_file()
    ]
    return dict(
        schema=1,
        stage="registry_scan",
        outcome="action_required" if actionable else "complete" if complete else "partial",
        last_attempt=utc_now(),
        last_complete_scan=utc_now() if complete else None,
        last_success=utc_now() if complete and not actionable else None,
        coverage=dict(
            packages=len(items), complete=sum(item["coverage"] == "complete" for item in items)
        ),
        source_hashes={name: digest(root / name) for name in FILES},
        input_hashes=input_hashes(root),
        packages=items,
        declared_infrastructure=inventory,
        advisories="separate strict OSV CI gate; metadata success is not audit success",
    )


def generate(destination: Path, head: str | None) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    base = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()
    identity = binding(
        repository=os.environ["GITHUB_REPOSITORY"],
        actor=os.environ["DEPENDENCY_ACTOR"],
        base=base,
        head=head or base,
        run=os.environ["GITHUB_RUN_ID"],
        attempt=os.environ["GITHUB_RUN_ATTEMPT"],
    )
    with tempfile.TemporaryDirectory(prefix="polysia-dependency-generation-") as raw:
        work = Path(raw) / "work"
        shutil.copytree(
            ROOT,
            work,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "artifacts", "dist", "build", "__pycache__", ".*cache"
            ),
        )
        if head:
            manifest = locks._git_text(os.environ["GITHUB_REPOSITORY"], head, "pyproject.toml")
            (work / "pyproject.toml").write_text(manifest, encoding="utf-8")
        locks.generate_pip_locks(work, upgrade=head is None)
        for name in FILES:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / name, target)
    seal(destination, ROOT, identity)


def maintenance_health(
    runs: list[dict], jobs: dict[int, list[dict]], now: datetime, grace_days: int = 9
) -> dict:
    meaningful = [
        r
        for r in runs
        if r.get("event") in {"schedule", "workflow_dispatch"} and r.get("head_branch") == "main"
    ]
    attempts = sorted(meaningful, key=lambda r: r["created_at"], reverse=True)
    successes = [
        r
        for r in attempts
        if r.get("conclusion") == "success"
        and all(
            any(
                j["name"] == name and j.get("conclusion") == "success"
                for j in jobs.get(r["id"], [])
            )
            for name in ("generate", "scan")
        )
    ]
    last = successes[0] if successes else None
    stale = last is None or now - datetime.fromisoformat(
        last["created_at"].replace("Z", "+00:00")
    ) > timedelta(days=grace_days)
    failed = bool(attempts and attempts[0].get("conclusion") in {"failure", "cancelled"})
    return dict(
        outcome="action_required" if stale or failed else "healthy",
        last_attempt=attempts[0]["created_at"] if attempts else None,
        last_complete_scan=last["created_at"] if last else None,
        stale=stale,
        latest_attempt_failed=failed,
        cadence_days=7,
        grace_days=grace_days - 7,
        next_action="Inspect dependency workflow and retained scan; disposition blockers",
        notification="GitHub maintenance issue; delivery beyond GitHub is unverified",
    )


def health() -> dict:
    from scripts.dependency_publication import api

    runs = api("actions/workflows/dependency-automation.yml/runs?per_page=50")["workflow_runs"]
    meaningful = [
        r
        for r in runs
        if r["event"] in {"schedule", "workflow_dispatch"} and r.get("head_branch") == "main"
    ]
    jobs = {
        r["id"]: api(f"actions/runs/{r['id']}/attempts/{r['run_attempt']}/jobs")["jobs"]
        for r in meaningful[:12]
    }
    result = maintenance_health(runs, jobs, datetime.now(UTC))
    publications = api("actions/workflows/dependency-publish.yml/runs?per_page=20")["workflow_runs"]
    relevant = [r for r in publications if r.get("conclusion") in {"success", "failure"}]
    if relevant and relevant[0]["conclusion"] == "failure":
        result["outcome"] = "action_required"
        result["publication"] = "failed"
        result["publication_run"] = relevant[0]["html_url"]
    return result


def notify_health(result: dict) -> None:
    from scripts.dependency_policy import EXPECTED_REPOSITORY
    from scripts.dependency_publication import api, command

    marker = "<!-- polysia-dependency-maintenance-health-v1 -->"
    issues = api("issues?state=all&per_page=100")
    matches = [
        issue
        for issue in issues
        if marker in (issue.get("body") or "") and "pull_request" not in issue
    ]
    if len(matches) > 1:
        raise ValueError("ambiguous maintenance health issues")
    issue = matches[0] if matches else None
    if result["outcome"] == "healthy":
        if issue and issue["state"] == "open":
            command(
                "api",
                "--method",
                "PATCH",
                f"repos/{EXPECTED_REPOSITORY}/issues/{issue['number']}",
                "--input",
                "-",
                body={"state": "closed", "state_reason": "completed"},
            )
        return
    body = (
        marker
        + "\nOwner: Platform dependency maintainer.\n\n"
        + json.dumps(result, sort_keys=True, indent=2)
        + "\n\nInspect the linked dependency workflows; "
        "resolve the failed/missed scan or publication route. No token expansion is authorized."
    )
    if issue and issue.get("body") == body and issue["state"] == "open":
        return
    path = f"repos/{EXPECTED_REPOSITORY}/issues"
    payload = {
        "title": "Dependency maintenance requires owner action",
        "body": body,
        "state": "open",
    }
    if issue:
        path += f"/{issue['number']}"
    command("api", "--method", "PATCH" if issue else "POST", path, "--input", "-", body=payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "generate", "health"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--head")
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            if args.output is None:
                parser.error("generate requires --output")
            generate(args.output, args.head)
            return 0
        result = scan(ROOT) if args.command == "scan" else health()
        if args.notify:
            if args.command != "health":
                parser.error("notifications are restricted to maintenance health")
            notify_health(result)
        serialized = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        print(serialized)
        return 0 if result["outcome"] in {"complete", "healthy"} else 1
    except OSError, RuntimeError, ValueError, subprocess.CalledProcessError:
        print(
            json.dumps(
                dict(
                    stage=args.command,
                    outcome="failed",
                    retryable=False,
                    next_action="Inspect sanitized workflow context; do not publish",
                )
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
