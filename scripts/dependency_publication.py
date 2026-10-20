"""Trusted publisher. Never install candidates or execute artifact/PR code here."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import dependency_locks as locks  # noqa: E402
from scripts.dependency_policy import (  # noqa: E402
    DEV_LOCK,
    EXPECTED_REPOSITORY,
    PYPROJECT,
    RUNTIME_LOCK,
)
from scripts.dependency_provenance import (  # noqa: E402
    WORKFLOW,
    artifact_path,
    binding,
    validate,
)


def command(*args: str, body: object = None) -> object:
    result = subprocess.run(
        ("gh", *args),
        input=None if body is None else json.dumps(body),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if args[0] == "api":
        return json.loads(result.stdout) if result.stdout.strip() else None
    return result.stdout.strip()


def api(path: str) -> object:
    return command("api", f"repos/{EXPECTED_REPOSITORY}/{path}")


def main_head() -> str:
    return str(api("git/ref/heads/main")["object"]["sha"])


def assessed_origin(run: dict, current_base: str) -> tuple[dict[str, str], dict | None]:
    if (
        run.get("path") != WORKFLOW
        or run.get("conclusion") != "success"
        or run.get("head_repository", {}).get("full_name") != EXPECTED_REPOSITORY
    ):
        raise ValueError("untrusted or unsuccessful dependency producer")
    event = run.get("event")
    if event == "pull_request":
        proposals = run.get("pull_requests", [])
        if len(proposals) != 1:
            raise ValueError("ambiguous originating pull request")
        pr = api(f"pulls/{int(proposals[0]['number'])}")
        if (
            pr["state"] != "open"
            or pr["user"]["login"] != "dependabot[bot]"
            or pr["head"]["repo"]["full_name"] != EXPECTED_REPOSITORY
            or pr["base"]["ref"] != "main"
            or pr["base"]["sha"] != current_base
            or pr["head"]["sha"] != run["head_sha"]
        ):
            raise ValueError("proposal identity/base/head changed")
        files = locks._pr_changed_files(EXPECTED_REPOSITORY, pr["number"])
        if not files or set(files) - {PYPROJECT, RUNTIME_LOCK, DEV_LOCK}:
            raise ValueError("proposal changes paths outside pip dependency scope")
        actor = "dependabot[bot]"
        head = pr["head"]["sha"]
    elif event in {"schedule", "workflow_dispatch"}:
        pr = None
        if run.get("head_branch") != "main" or run.get("head_sha") != current_base:
            raise ValueError("producer base is stale or is not main")
        actor = run["actor"]["login"]
        head = current_base
    else:
        raise ValueError("unexpected dependency producer event")
    return binding(
        repository=EXPECTED_REPOSITORY,
        actor=actor,
        base=current_base,
        head=head,
        run=str(run["id"]),
        attempt=str(run["run_attempt"]),
    ), pr


def publish(directory: Path, run_id: str) -> dict:
    run = api(f"actions/runs/{run_id}")
    base = main_head()
    local = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if local != base:
        raise ValueError("trusted publisher checkout is stale")
    identity, pr = assessed_origin(run, base)
    validate(directory, ROOT, identity)
    # An immutable manifest from the live assessed head must match the artifact,
    # independently of its self-declared hash.
    manifest = locks._git_text(EXPECTED_REPOSITORY, identity["head"], PYPROJECT)
    if artifact_path(directory, PYPROJECT).read_text(encoding="utf-8") != manifest:
        raise ValueError("artifact manifest differs from assessed proposal")
    branch = pr["head"]["ref"] if pr else "codex/scheduled-lock-refresh-pip"
    _, decision = locks.classify_from_artifact(
        actor="dependabot[bot]" if pr else "github-actions[bot]",
        head_branch=branch,
        artifact=directory,
        base_root=ROOT,
    )
    if decision.action == "reject":
        raise ValueError("dependency policy rejected generated proposal")
    files = {
        name: artifact_path(directory, name).read_text(encoding="utf-8")
        for name in (RUNTIME_LOCK, DEV_LOCK)
    }
    if main_head() != base:
        raise ValueError("base changed before publication; regenerate")
    if pr:
        live = api(f"pulls/{pr['number']}")
        if live["head"]["sha"] != identity["head"]:
            raise ValueError("proposal changed before publication")
        if all(
            locks._git_text(EXPECTED_REPOSITORY, identity["head"], name) == content
            for name, content in files.items()
        ):
            head = identity["head"]
        else:
            head = locks.commit_files_to_branch(
                repository=EXPECTED_REPOSITORY,
                branch=branch,
                files=files,
                message="chore(deps): synchronize canonical dependency locks",
                expected_head=identity["head"],
            )
    else:
        if all((ROOT / name).read_text(encoding="utf-8") == text for name, text in files.items()):
            return {"outcome": "unchanged", "base": base}
        # Stable branch identity makes interrupted reruns recoverable. Never
        # delete a branch on failure or overwrite a mismatching proposal.
        branches = api("branches?per_page=100")
        existing = next((b for b in branches if b["name"] == branch), None)
        if existing:
            head = existing["commit"]["sha"]
            if head != base and any(
                locks._git_text(EXPECTED_REPOSITORY, head, name) != text
                for name, text in files.items()
            ):
                raise ValueError("existing publication branch differs; preserve and review")
        else:
            command(
                "api",
                "--method",
                "POST",
                f"repos/{EXPECTED_REPOSITORY}/git/refs",
                "--input",
                "-",
                body={"ref": f"refs/heads/{branch}", "sha": base},
            )
            head = base
        if head == base:
            head = locks.commit_files_to_branch(
                repository=EXPECTED_REPOSITORY,
                branch=branch,
                files=files,
                message="chore(deps): refresh canonical dependency locks",
                expected_head=base,
            )
        proposals = api(f"pulls?state=all&head=PolySia-Systems:{branch}")
        if any(p["state"] != "open" for p in proposals):
            raise ValueError("proposal already disposed; preserve its record")
        if len(proposals) > 1:
            raise ValueError("ambiguous publication proposals")
        pr = (
            proposals[0]
            if proposals
            else command(
                "api",
                "--method",
                "POST",
                f"repos/{EXPECTED_REPOSITORY}/pulls",
                "--input",
                "-",
                body={
                    "head": branch,
                    "base": "main",
                    "draft": decision.action != "auto_merge",
                    "title": "chore(deps): refresh canonical dependency locks",
                    "body": f"Canonical runtime-first resolution. Policy: {decision.action}.\n"
                    f"Source run: {run['html_url']}\nExpected base: {base}\n"
                    "Runtime changes require owner review. CI must validate the final head.",
                },
            )
        )
    # GITHUB_TOKEN commits do not cause ordinary CI push/PR triggers.
    ci_runs = api(f"actions/workflows/ci.yml/runs?head_sha={head}&event=workflow_dispatch")
    if not any(
        r.get("head_sha") == head
        and r.get("head_branch") == branch
        and (r.get("status") in {"queued", "in_progress"} or r.get("conclusion") == "success")
        for r in ci_runs["workflow_runs"]
    ):
        command("workflow", "run", "ci.yml", "--ref", branch, "-f", "validation_scope=full")
    if main_head() != base or api(f"pulls/{pr['number']}")["head"]["sha"] != head:
        raise ValueError("base or proposal changed before merge decision")
    return dict(
        outcome="published",
        policy=decision.action,
        head=head,
        pull_request=pr["html_url"],
        run=run_id,
    )


def merge_after_ci(run_id: str) -> dict:
    run = api(f"actions/runs/{run_id}")
    if (
        run.get("path") != ".github/workflows/ci.yml"
        or run.get("conclusion") != "success"
        or run.get("head_repository", {}).get("full_name") != EXPECTED_REPOSITORY
        or run.get("event") not in {"pull_request", "workflow_dispatch"}
    ):
        raise ValueError("unexpected CI evidence")
    branch, head = run["head_branch"], run["head_sha"]
    proposals = api(f"pulls?state=open&head=PolySia-Systems:{branch}")
    if not proposals:
        return dict(outcome="no_eligible_proposal")
    if len(proposals) != 1:
        raise ValueError("ambiguous CI proposal")
    pr = api(f"pulls/{proposals[0]['number']}")
    actor = pr["user"]["login"]
    if actor not in {"dependabot[bot]", "github-actions[bot]"}:
        return dict(outcome="human_review", reason="maintainer proposal")
    base = main_head()
    local = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()
    if local != base:
        raise ValueError("trusted merge checkout is stale")
    if (
        pr["base"]["ref"] != "main"
        or pr["base"]["sha"] != base
        or pr["head"]["sha"] != head
        or pr["head"]["repo"]["full_name"] != EXPECTED_REPOSITORY
    ):
        raise ValueError("base/head changed since CI")
    comparison = api(f"compare/{base}...{head}")
    if comparison["behind_by"] != 0:
        raise ValueError("CI source does not include current main")
    changed = locks._pr_changed_files(EXPECTED_REPOSITORY, pr["number"])
    if not changed or set(changed) - {PYPROJECT, RUNTIME_LOCK, DEV_LOCK}:
        return dict(outcome="human_review", reason="outside pip lock/declaration scope")
    checks = api(f"commits/{head}/check-runs?per_page=100")["check_runs"]
    if not any(
        c["name"] == "CI Gate"
        and c.get("conclusion") == "success"
        and c.get("app", {}).get("slug") == "github-actions"
        and c.get("check_suite", {}).get("id") == run["check_suite_id"]
        for c in checks
    ):
        raise ValueError("no successful CI Gate from this exact run and head")
    with tempfile.TemporaryDirectory(prefix="polysia-dependency-merge-") as raw:
        artifact = Path(raw)
        for name in FILES_FOR_MERGE:
            target = artifact / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(locks._git_text(EXPECTED_REPOSITORY, head, name), encoding="utf-8")
        from scripts.dependency_provenance import validate_manifest

        validate_manifest(artifact, ROOT)
        _, decision = locks.classify_from_artifact(
            actor=actor, head_branch=branch, artifact=artifact, base_root=ROOT
        )
    if decision.action != "auto_merge":
        return dict(outcome="human_review", reason=decision.reason, head=head)
    if main_head() != base or api(f"pulls/{pr['number']}")["head"]["sha"] != head:
        raise ValueError("base/head changed immediately before merge")
    command("pr", "merge", str(pr["number"]), "--merge", "--match-head-commit", head)
    return dict(outcome="merged", head=head, pull_request=pr["html_url"], ci_run=run_id)


FILES_FOR_MERGE = (PYPROJECT, RUNTIME_LOCK, DEV_LOCK)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--merge-after-ci", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]*", args.run):
        parser.error("invalid source run")
    try:
        if args.merge_after_ci:
            result = merge_after_ci(args.run)
        else:
            if args.artifact is None:
                parser.error("publication requires --artifact")
            result = publish(args.artifact, args.run)
    except subprocess.CalledProcessError as error:
        # Provider stderr can contain private response data. Preserve run context,
        # not arbitrary provider output or a falsely successful capability skip.
        result = dict(
            outcome="failed",
            category="permission_or_provider",
            next_action="Inspect run; use approved maintainer fallback; do not expand token",
        )
        if "not permitted to create or approve pull requests" in (error.stderr or ""):
            result["missing_capability"] = "GITHUB_TOKEN pull-request creation"
    except ValueError, RuntimeError, KeyError, OSError:
        result = dict(
            outcome="failed",
            category="stale_or_invalid_evidence",
            next_action="Regenerate from current main and proposal head",
        )
    print(json.dumps(result, sort_keys=True))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("## Dependency publication\n\n```json\n" + json.dumps(result) + "\n```\n")
    return 1 if result["outcome"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
