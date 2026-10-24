"""Bounded observation of trusted-main full Windows CI; no test dispatch/install."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta

REPOSITORY = "PolySia-Systems/Platform"
MARKER = "<!-- polysia-windows-health-v1 -->"
STEPS = (
    "Install compatibility environment",
    "Compile",
    "Full Pytest",
    "Environment integrity",
    "Dependency lock check",
    "Build package",
    "CLI smoke",
)
INPUTS = (
    ".github/workflows/ci.yml",
    "locks/requirements-dev-py314.txt",
    "locks/requirements-runtime-py314.txt",
    "pyproject.toml",
)


def api(path: str, *, body: dict | None = None, method: str = "GET"):
    command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    if body is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    return json.loads(result.stdout)


def trusted(run: dict) -> bool:
    return (
        run.get("event") in {"push", "schedule", "workflow_dispatch"}
        and run.get("head_branch") == "main"
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("path") == ".github/workflows/ci.yml"
        and bool(re.fullmatch("[0-9a-f]{40}", run.get("head_sha", "")))
    )


def assess(
    runs: list[dict],
    jobs: dict[int, list[dict]],
    sources: dict[int, dict],
    now: datetime,
    *,
    history_complete: bool = True,
) -> dict:
    attempts, successes, failures = [], [], []
    for run in sorted(runs, key=lambda r: r["created_at"]):
        if not trusted(run):
            continue
        candidates = [
            j for j in jobs.get(run["id"], []) if j.get("name") == "Windows Compatibility"
        ]
        periodic = run["event"] in {"schedule", "workflow_dispatch"}
        classification_failed = any(
            j.get("name") == "changes" and j.get("conclusion") not in {"success", None}
            for j in jobs.get(run["id"], [])
        )
        if not periodic and not classification_failed and (
            not candidates or all(j.get("conclusion") == "skipped" for j in candidates)
        ):
            continue
        attempts.append(run)
        if run.get("status") != "completed":
            continue
        complete = False
        if len(candidates) == 1:
            job = candidates[0]
            step_results = {s["name"]: s.get("conclusion") for s in job.get("steps", [])}
            complete = (
                run.get("conclusion") == "success"
                and job.get("conclusion") == "success"
                and job.get("head_sha") == run["head_sha"]
                and "windows-latest" in job.get("labels", [])
                and all(step_results.get(name) == "success" for name in STEPS)
                and bool(sources.get(run["id"]))
                and all(
                    step_results.get(name) == "success"
                    for name in sources.get(run["id"], {}).get("required_steps", [])
                )
            )
        if complete:
            successes.append(run)
            failures.clear()  # Only a later complete, qualifying run clears failures.
        else:
            failures.append(run)
    last = successes[-1] if successes else None
    overdue = last is None or now - datetime.fromisoformat(
        last["created_at"].replace("Z", "+00:00")
    ) > timedelta(days=9)
    problems = []
    if failures:
        problems.append("failed_or_partial_full_windows")
    if overdue:
        problems.append("full_windows_overdue_9_days")
    if not history_complete:
        problems.append("bounded_history_incomplete")
    failure = failures[-1] if failures else None
    return {
        "outcome": "action_required" if problems else "healthy",
        "problems": problems,
        "last_complete": identity(last, sources),
        "unresolved_failure": identity(failure, sources),
        "overdue_days": 9,
        "in_progress": any(r.get("status") != "completed" for r in attempts[-1:]),
        "next_action": "Inspect native CI Windows steps and source inputs; repair and rerun CI.",
        "notification": "GitHub Issue only; external delivery and future clock firing unverified",
    }


def identity(run: dict | None, sources: dict[int, dict]) -> dict | None:
    if run is None:
        return None
    return {
        key: run.get(key)
        for key in ("id", "run_attempt", "head_sha", "event", "html_url", "created_at")
    } | {"inputs": sources.get(run["id"], {})}


def source_identity(sha: str) -> dict:
    inputs = {}
    for path in INPUTS:
        content = api(f"contents/{path}?ref={sha}")
        data = base64.b64decode(content["content"], validate=False)
        inputs[path] = hashlib.sha256(data).hexdigest()
        if path == INPUTS[0]:
            text = data.decode("utf-8")
            start = text.index("  windows-compatibility:\n")
            block = text[start:].split("\n  container:", 1)[0]
            # Source is trusted main, never executed by this observer.
            if not all(f"name: {name}" in block for name in STEPS):
                raise ValueError("unsupported Windows step contract at trusted source")
            for command in (
                "python -m pytest -q",
                "python -m build",
                "python -m pip check",
                "python -m compileall -q src tests",
                "python -m polysia.cli --help",
                "python -m pip install --no-deps -e .",
                "python scripts/dependency_locks.py check",
                "python -m pip install -r locks/requirements-dev-py314.txt",
            ):
                if command not in block:
                    raise ValueError("unsupported Windows command contract")
            inputs["windows_job_sha256"] = hashlib.sha256(block.encode()).hexdigest()
            inputs["required_steps"] = list(STEPS)
            if "--junitxml=artifacts/windows-pytest.xml" in block:
                inputs["required_steps"].append("Retain Windows timing")
    return inputs


def observe() -> dict:
    response = api("actions/workflows/ci.yml/runs?branch=main&per_page=100")
    runs = [run for run in response["workflow_runs"] if trusted(run)]
    # Up to twelve meaningful candidates; unrelated lightweight green runs cannot heal failures.
    jobs, sources = {}, {}
    examined = 0
    processed = []
    complete_history = response["total_count"] <= 100
    for run in runs:
        if examined >= 12 or len(processed) >= 30:
            complete_history = False
            break
        result = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
        if result["total_count"] > 100:
            raise ValueError("job history exceeds bounded coverage")
        jobs[run["id"]] = result["jobs"]
        processed.append(run)
        if any(
            j.get("name") == "Windows Compatibility" and j.get("conclusion") != "skipped"
            for j in result["jobs"]
        ) or run["event"] in {"schedule", "workflow_dispatch"}:
            sources[run["id"]] = source_identity(run["head_sha"])
            examined += 1
            candidate = assess([run], jobs, sources, datetime.now(UTC))
            if candidate["last_complete"] is not None:
                complete_history = True
                break
    now = datetime.now(UTC)
    # Older history is unnecessary once a qualifying success within nine days establishes
    # a complete boundary; all newer failures/partial attempts remain examined.
    recent = assess(processed, jobs, sources, now)
    if recent["last_complete"] is not None:
        complete_history = True
    return assess(processed, jobs, sources, now, history_complete=complete_history)


def notify(result: dict, request=api) -> None:
    # Exclude transient progress: meaningful outcome/failure/freshness transitions only.
    stable = {k: v for k, v in result.items() if k != "in_progress"}
    response = request("issues?state=all&per_page=100")
    matches = [i for i in response if MARKER in (i.get("body") or "") and "pull_request" not in i]
    if len(matches) > 1 or (not matches and len(response) >= 100):
        raise ValueError("ambiguous or incomplete health Issue inventory")
    issue = matches[0] if matches else None
    if stable["outcome"] == "healthy":
        if issue and issue["state"] == "open":
            request(
                f"issues/{issue['number']}",
                method="PATCH",
                body={
                    "state": "closed",
                    "state_reason": "completed",
                    "body": MARKER + "\n" + json.dumps(stable, sort_keys=True, indent=2),
                },
            )
        return
    body = MARKER + "\n" + json.dumps(stable, sort_keys=True, indent=2)
    if issue and issue["body"] == body and issue["state"] == "open":
        return
    request(
        f"issues/{issue['number']}" if issue else "issues",
        method="PATCH" if issue else "POST",
        body={"title": "Full Windows CI requires maintainer action", "body": body, "state": "open"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") == "true" and (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") != "schedule"
    ):
        raise ValueError("observer requires scheduled trusted main")
    try:
        result = observe()
        print(json.dumps(result, sort_keys=True, indent=2), flush=True)
        if args.notify:
            notify(result)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(
            "Windows health API/source/notification failure; inspect workflow diagnostics.",
            flush=True,
        )
        if isinstance(error, subprocess.CalledProcessError):
            print((error.stderr or "API request failed without diagnostics")[:2000], flush=True)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
