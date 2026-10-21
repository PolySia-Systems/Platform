"""Bounded, provisional release eligibility; resolution/CI still own acceptance."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from scripts.dependency_policy import SENSITIVE_RUNTIME_PACKAGES, is_low_risk_version_bump

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import InvalidVersion, Version

MAX_RELEASES = 100
MAX_METADATA_ATTEMPTS = 3


def environments(extras: Iterable[str] = ()) -> list[dict[str, str]]:
    return [
        dict(default_environment(), python_version="3.14", python_full_version="3.14.8",
             sys_platform=platform, platform_system=system,
             os_name="nt" if platform == "win32" else "posix",
             platform_machine="AMD64" if platform == "win32" else "x86_64",
             implementation_name="cpython", implementation_version="3.14.8", extra=extra)
        for platform, system in (("linux", "Linux"), ("win32", "Windows"))
        for extra in {"", *extras}
    ]


def active(requirement: Requirement, extras: Iterable[str] = ()) -> bool:
    return not requirement.marker or any(
        requirement.marker.evaluate(env) for env in environments(extras)
    )


def release_catalog(releases: dict, current: str) -> dict:
    """Enumerate all version-policy-eligible releases before applying the bound.

    Newer majors must not crowd an eligible patch out of the assessment window.
    Excluded-version counts retain visibility without an unbounded report.
    """
    candidates, rejected = [], 0
    for text, files in releases.items():
        try:
            if Version(text) <= Version(current):
                continue
        except InvalidVersion:
            rejected += 1
            continue
        if not is_low_risk_version_bump(current, text):
            rejected += 1
            continue
        usable = [file for file in files if not file.get("yanked")]
        candidates.append(dict(
            version=text, yanked=not usable,
            python=any(SpecifierSet(f.get("requires_python") or "").contains("3.14.8")
                       for f in usable),
        ))
    candidates.sort(key=lambda row: Version(row["version"]), reverse=True)
    return dict(releases=candidates[:MAX_RELEASES], truncated=len(candidates) > MAX_RELEASES,
                version_policy_exclusions=rejected)


def assess_candidates(
    item: dict, declarations: list[str], parents: list[str], fetch: Callable,
) -> dict:
    """Evaluate incoming bounds and a bounded set of real version metadata.

    Candidate outgoing dependencies are provisional: canonical resolution with
    frozen runtime/sensitive pins and complete-delta classification is required.
    """
    constraints = [Requirement(edge.split(": ", 1)[1]) for edge in parents]
    constraints += [req for text in declarations
                    if canonicalize_name((req := Requirement(text)).name) == item["package"]
                    and active(req, ("dev",))]
    held = item["scope"] == "runtime" or item["package"] in SENSITIVE_RUNTIME_PACKAGES
    catalog = item.get("release_catalog", {})
    assessed, eligible, attempts, unknown = [], [], 0, False

    def reasons(version: str, row: dict) -> list[str]:
        result = []
        if held:
            result.append("runtime_or_sensitive_review")
        if not is_low_risk_version_bump(item["resolved"], version):
            result.append("version_policy")
        if row.get("yanked"):
            result.append("yanked_or_no_files")
        if not row.get("python", False):
            result.append("supported_python")
        for req in constraints:
            if req.url or not req.specifier.contains(version):
                result.append(f"constraint:{req}")
        return result

    latest = item.get("latest_published_stable")
    item["latest_eligibility_exclusions"] = reasons(latest, dict(
        yanked=False, python=item.get("supports_python314", False),
    )) if latest else ["metadata_unknown"]
    for row in catalog.get("releases", []):
        version = row["version"]
        excluded = reasons(version, row)
        evidence = dict(version=version, exclusions=excluded, metadata_checked=False)
        if not excluded:
            if attempts >= MAX_METADATA_ATTEMPTS:
                evidence["exclusions"] = ["metadata_attempt_bound"]
                unknown = True
            else:
                attempts += 1
                try:
                    data = fetch(item["package"], version)
                    if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
                        raise ValueError("malformed candidate metadata")
                    if Version(data["info"]["version"]) != Version(version):
                        raise ValueError("candidate metadata identity mismatch")
                    evidence["metadata_checked"] = True
                    if data.get("vulnerabilities"):
                        excluded.append("candidate_advisory")
                    if not data.get("urls") or all(f.get("yanked") for f in data["urls"]):
                        excluded.append("yanked_or_no_files")
                    if not SpecifierSet(data["info"].get("requires_python") or "").contains(
                        "3.14.8"
                    ):
                        excluded.append("supported_python")
                    if not excluded:
                        eligible.append(version)
                except RuntimeError, ValueError, KeyError, TypeError, AttributeError:
                    excluded.append("candidate_metadata_unknown")
                    unknown = True
        assessed.append(evidence)
    # A failed higher metadata request cannot be silently skipped and relabelled
    # as proof of the highest eligible release. Bounds are explicit, not absence.
    failed = any("candidate_metadata_unknown" in row["exclusions"] and (
        not eligible or Version(row["version"]) > Version(eligible[0])
    ) for row in assessed)
    item.update(
        parent_constraints=parents,
        candidate_versions=[] if failed else eligible,
        highest_eligible_version=None if failed or not eligible else eligible[0],
        release_assessments=assessed,
        eligibility_observed_at=item["observed_at"],
        eligibility_provisional=True,
        eligibility_coverage="UNKNOWN" if not held and (failed or (
            not eligible and (unknown or catalog.get("truncated"))
        )) else "complete",
    )
    item["eligibility_outcome"] = (
        "UNKNOWN" if item["eligibility_coverage"] == "UNKNOWN"
        else "REVIEW_REQUIRED" if held
        else "PROVISIONAL_CANDIDATE" if eligible
        else "NO_ELIGIBLE_UPDATE"
    )
    return item
