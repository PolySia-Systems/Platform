"""Trusted publisher. Never install candidates or execute artifact/PR code here."""

from __future__ import annotations

import argparse
import hashlib
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


def trusted_bot_commit(head: str) -> bool:
    commit = api(f"commits/{head}")
    bots = {"github-actions[bot]", "dependabot[bot]"}
    committer = (commit.get("committer") or {}).get("login")
    author = (commit.get("author") or {}).get("login")
    # Our GraphQL writer uses GitHub's web-flow committer and the bot author.
    # Full diff, immutable origin and hashes are independently required.
    return (committer in bots or (committer == "web-flow" and author in bots)) and (
        commit.get("commit", {}).get("verification", {}).get("verified") is True
    )


def scheduled_target(base: str, files: dict[str, str]) -> dict:
    key = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    proposed = f"codex/scheduled-lock-refresh-{base[:12]}-{key}"
    branches = api("branches?per_page=100")
    if len(branches) >= 100:
        raise ValueError("branch inventory is incomplete; preserve proposals")
    active, disposed = [], None
    for branch in branches:
        name = branch["name"]
        if not name.startswith("codex/scheduled-lock-refresh-"):
            continue
        prs = api(f"pulls?state=all&head=PolySia-Systems:{name}")
        opened = [pr for pr in prs if pr["state"] == "open"]
        if len(opened) > 1:
            raise ValueError("ambiguous scheduled proposal")
        if opened or not prs:
            active.append((branch, opened[0] if opened else None))
        elif name == proposed:
            disposed = prs[0]
    if len(active) > 1:
        raise ValueError("multiple active or unpublished scheduled proposals; preserve and review")
    if not active:
        return dict(branch=proposed, head=None, pr=None, disposed=disposed)
    branch, pr = active[0]
    head = branch["commit"]["sha"]
    if pr and (
        pr["user"]["login"] != "github-actions[bot]"
        or pr["head"]["repo"]["full_name"] != EXPECTED_REPOSITORY
        or pr["base"]["ref"] != "main"
        or pr["head"]["sha"] != head
    ):
        raise ValueError("scheduled proposal identity changed")
    if head != base:
        comparison = api(f"compare/{base}...{head}")
        if (
            comparison["behind_by"] != 0
            or not comparison["files"]
            or any(item["filename"] not in {RUNTIME_LOCK, DEV_LOCK} for item in comparison["files"])
            or not trusted_bot_commit(head)
        ):
            raise ValueError("scheduled branch is stale, untrusted or changes executable paths")
    return dict(branch=branch["name"], head=head, pr=pr, disposed=None)


def assessed_origin(run: dict, current_base: str) -> tuple[dict[str, str], dict | None]:
    if (
        run.get("path") != WORKFLOW
        or run.get("conclusion") != "success"
        or run.get("head_repository", {}).get("full_name") != EXPECTED_REPOSITORY
    ):
        raise ValueError("untrusted or unsuccessful dependency producer")
    event = run.get("event")
    if event == "pull_request":
        if run.get("actor", {}).get("login") != "dependabot[bot]":
            raise ValueError("proposal event actor is not Dependabot")
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
        target = scheduled_target(base, files)
        if target["disposed"]:
            return dict(outcome="previously_disposed", pull_request=target["disposed"]["html_url"])
        branch, head, pr = target["branch"], target["head"], target["pr"]
        if head is None:
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
        if head == base or any(
            locks._git_text(EXPECTED_REPOSITORY, head, name) != text for name, text in files.items()
        ):
            head = locks.commit_files_to_branch(
                repository=EXPECTED_REPOSITORY,
                branch=branch,
                files=files,
                message="chore(deps): refresh canonical dependency locks",
                expected_head=head,
            )
        pr = (
            pr
            if pr
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
    if main_head() != base or api(f"pulls/{pr['number']}")["head"]["sha"] != head:
        raise ValueError("base or proposal changed before CI dispatch")
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
    if not trusted_bot_commit(head):
        return dict(
            outcome="human_review", reason="final head is not a verified bot commit", head=head
        )
    command("pr", "merge", str(pr["number"]), "--merge", "--match-head-commit", head)
    return dict(outcome="merged", head=head, pull_request=pr["html_url"], ci_run=run_id)


FILES_FOR_MERGE = (PYPROJECT, RUNTIME_LOCK, DEV_LOCK)


def report_scan(path: Path, run_id: str) -> dict:
    run = api(f"actions/runs/{run_id}")
    base = main_head()
    if (
        run.get("path") != WORKFLOW
        or run.get("head_sha") != base
        or run.get("head_branch") != "main"
        or run.get("event") not in {"schedule", "workflow_dispatch"}
        or run.get("head_repository", {}).get("full_name") != EXPECTED_REPOSITORY
    ):
        raise ValueError("scan report does not originate from current main")
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError("invalid scan report")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != 1 or payload.get("source_hashes") != {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES_FOR_MERGE
    }:
        raise ValueError("scan report source mismatch")
    rows = []
    for item in payload["packages"]:
        name, current = item["package"], item["resolved"]
        latest = item.get("latest_published_stable", "UNKNOWN")
        if not re.fullmatch(r"[a-z0-9-]+", name) or not all(
            re.fullmatch(r"[a-zA-Z0-9.+!-]+", value) for value in (current, latest)
        ):
            raise ValueError("invalid package report identity")
        if current != latest or item.get("advisory_ids") or item.get("current_yanked"):
            state = "HELD_PARENT_BOUND" if item.get("candidate_blocked_by") else "REVIEW_REQUIRED"
            if item.get("advisory_ids") or item.get("current_yanked"):
                state = "ADVISORY_OR_YANKED_ACTION"
            rows.append((name, current, latest, state))
    state_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    marker = "<!-- polysia-dependency-backlog-v1 -->"
    issues = api("issues?state=all&per_page=100")
    matches = [
        issue
        for issue in issues
        if marker in (issue.get("body") or "") and "pull_request" not in issue
    ]
    if len(matches) > 1:
        raise ValueError("ambiguous dependency backlog")
    issue = matches[0] if matches else None
    if not rows and not issue:
        return dict(outcome="unchanged")
    if issue and state_hash in (issue.get("body") or ""):
        return dict(outcome="unchanged", issue=issue["html_url"])
    body = (
        f"{marker}\n<!-- state:{state_hash} -->\n"
        f"Owner: Platform dependency maintainer. Source: {run['html_url']}\n\n"
        "For every row: review on the next weekly scan, advisory or parent/compatibility release; "
        "retain until a coherent resolver delta and final-head CI are accepted. "
        "Runtime/build/crypto/Actions require review. Installed/tested versions are UNKNOWN "
        "until separately evidenced; metadata does not replace the strict OSV gate.\n\n"
        "| Package (official metadata) | Resolved | Latest stable | Disposition |\n"
        "|---|---|---|---|\n"
        + "\n".join(
            f"| [{name}](https://pypi.org/pypi/{name}/json) | {old} | {new} | {state} |"
            for name, old, new, state in rows
        )
    )
    target = f"repos/{EXPECTED_REPOSITORY}/issues" + (f"/{issue['number']}" if issue else "")
    result = command(
        "api",
        "--method",
        "PATCH" if issue else "POST",
        target,
        "--input",
        "-",
        body={
            "title": "Dependency review backlog",
            "body": body,
            "state": "open" if rows else "closed",
        },
    )
    return dict(outcome="backlog_updated", issue=result["html_url"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--merge-after-ci", action="store_true")
    parser.add_argument("--report-scan", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]*", args.run):
        parser.error("invalid source run")
    try:
        if args.report_scan:
            if args.artifact is None:
                parser.error("scan report requires --artifact")
            result = report_scan(args.artifact, args.run)
        elif args.merge_after_ci:
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
