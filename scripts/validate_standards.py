from __future__ import annotations

import argparse
import ast
import json
import keyword
import re
import subprocess
import sys
import tomllib
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXPECTED_RELEASE = "v0.1.1"
EXPECTED_COMMIT = "921db357c07bf1d940f72cfbb662d940288132ca"
EXPECTED_PROFILES = {"PRF-BASE", "PRF-PYS"}
EXPECTED_REQUIREMENTS = {
    *(f"PRF-FRM-{number:03d}" for number in range(1, 17)),
    *(f"PRF-BASE-{number:03d}" for number in range(1, 10)),
    *(f"PRF-PYS-{number:03d}" for number in range(1, 8)),
    *(f"ENG-PY-{number:03d}" for number in range(1, 22)),
    "CORE-REQ-020",
    "CORE-REQ-021",
    "CORE-REQ-022",
    "CORE-REQ-024",
    "CORE-REQ-026",
    "CORE-REQ-027",
    "CORE-REQ-029",
    "CORE-REQ-030",
    "CORE-REQ-032",
    "CORE-REQ-034",
    "CORE-REQ-052",
    "CORE-REQ-053",
    "CORE-REQ-054",
    "CORE-REQ-055",
    "CORE-REQ-057",
    "CORE-REQ-059",
    "CORE-NAM-025",
    "CORE-NAM-028",
    "CORE-NAM-029",
    "CORE-NAM-031",
    "CORE-NAM-032",
    "CORE-NAM-033",
    *(f"CORE-NAM-{number:03d}" for number in range(36, 43)),
    *(f"CORE-NAM-{number:03d}" for number in range(54, 58)),
    "CORE-NAM-061",
    "CORE-NAM-062",
    "CORE-NAM-070",
    "CORE-NAM-071",
    "CORE-NAM-075",
    "CORE-NAM-082",
    *(f"CORE-NAM-{number:03d}" for number in range(85, 103)),
    "CORE-NAM-104",
    "CORE-NAM-105",
    "CORE-LCY-001",
    "CORE-VER-012",
}
EXPECTED_OUTCOME_COUNTS = {
    "applicable": 89,
    "not_applicable": 15,
    "source_authority": 10,
}
EXPECTED_CONFORMANCE_VERDICTS = {
    "applicable": "pass",
    "not_applicable": "not_applicable",
    "source_authority": "verified_source_authority",
}
SNAKE_CASE = re.compile(r"^_?[a-z][a-z0-9_]*$")
CAP_WORDS = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")
KEBAB_CASE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(?P<target><[^>\n]+>|[^)\s]+)")
REFERENCE_LINK = re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?P<target><[^>\n]+>|[^\s]+)")
FENCED_CODE = re.compile(
    r"(?ms)^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=fence)[ \t]*$"
)
INLINE_CODE = re.compile(r"`+[^`\n]*`+")
EXTERNAL_SCHEMES = frozenset({"data", "http", "https", "mailto", "tel"})
HISTORICAL_PREFIXES = (
    "docs/13-ai-handoffs/",
    "docs/18-ai-handoffs/",
    "docs/99-archive/",
    "prompts/archive/",
)
CANONICAL_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})
ENVIRONMENT_ALIASES = {
    "dev": "development",
    "local": "development",
    "prd": "production",
    "prod": "production",
    "qa": "test",
    "server": "production",
    "stage": "staging",
    "stg": "staging",
    "testing": "test",
}


@dataclass(frozen=True, order=True)
class Finding:
    requirement_id: str
    path: str
    message: str
    line: int = 0

    @property
    def fingerprint(self) -> str:
        return f"{self.requirement_id}|{self.path}|{self.line}|{self.message}"


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True
    )


def _tracked_paths(repository: Path) -> list[Path]:
    result = _git(repository, "ls-files", "-z")
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _manifest_findings(manifest: dict[str, object]) -> list[Finding]:
    path = "standards/adoption.toml"
    findings: list[Finding] = []

    def require(condition: bool, requirement_id: str, message: str) -> None:
        if not condition:
            findings.append(Finding(requirement_id, path, message))

    require(manifest.get("schema_version") == 1, "PRF-FRM-013", "schema_version must be 1")
    require(
        manifest.get("standards_release") == EXPECTED_RELEASE,
        "CORE-VER-012",
        f"Standards release must be pinned to {EXPECTED_RELEASE}",
    )
    require(
        manifest.get("standards_commit") == EXPECTED_COMMIT,
        "CORE-LCY-001",
        f"Standards commit must be pinned to {EXPECTED_COMMIT}",
    )
    require(
        manifest.get("standards_release_immutable") is True,
        "CORE-LCY-001",
        "Standards release must be recorded as immutable",
    )
    require(
        set(manifest.get("profiles", [])) == EXPECTED_PROFILES,
        "PRF-FRM-006",
        "Selected profiles must be exactly PRF-BASE and PRF-PYS",
    )
    groups = manifest.get("requirement_groups", [])
    require(isinstance(groups, list), "PRF-FRM-006", "requirement_groups must be an array")
    observed: set[str] = set()
    duplicates: set[str] = set()
    counts: dict[str, int] = {}
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                findings.append(
                    Finding("PRF-FRM-006", path, "Every requirement group must be a table")
                )
                continue
            outcome = str(group.get("outcome", ""))
            ids = group.get("ids", [])
            if outcome not in EXPECTED_OUTCOME_COUNTS:
                findings.append(
                    Finding("PRF-FRM-007", path, f"Unknown requirement outcome {outcome!r}")
                )
            if not isinstance(ids, list):
                findings.append(
                    Finding("PRF-FRM-006", path, "Requirement group ids must be an array")
                )
                continue
            counts[outcome] = counts.get(outcome, 0) + len(ids)
            for requirement_id in map(str, ids):
                if requirement_id in observed:
                    duplicates.add(requirement_id)
                observed.add(requirement_id)
    require(not duplicates, "PRF-PYS-003", f"Duplicate requirement IDs: {sorted(duplicates)}")
    require(
        observed == EXPECTED_REQUIREMENTS,
        "PRF-PYS-005",
        "Resolved requirement IDs differ from the v0.1.1 PRF-BASE + PRF-PYS set: "
        f"missing={sorted(EXPECTED_REQUIREMENTS - observed)}, "
        f"unexpected={sorted(observed - EXPECTED_REQUIREMENTS)}",
    )
    require(
        counts == EXPECTED_OUTCOME_COUNTS,
        "PRF-FRM-007",
        f"Requirement outcome counts must be {EXPECTED_OUTCOME_COUNTS}, got {counts}",
    )
    facts = manifest.get("consumer_facts", {})
    require(isinstance(facts, dict), "PRF-PYS-004", "consumer_facts must be a table")
    if isinstance(facts, dict):
        expected_true = {
            "controlled_repository",
            "installable_project",
            "public_cli",
            "python_serialized_models",
            "repeatable_verification_environment",
        }
        require(
            all(facts.get(name) is True for name in expected_true),
            "PRF-PYS-001",
            "Observable Python selection facts are incomplete",
        )
        require(
            facts.get("external_effect_tests_by_default") is False,
            "ENG-PY-019",
            "External-effect tests must remain disabled by default",
        )
    return findings


def _conformance_findings(repository: Path) -> list[Finding]:
    path = "standards/conformance.toml"
    target = repository / path
    if not target.exists():
        return [Finding("PRF-FRM-014", path, "Complete conformance report is missing")]
    report = _load_toml(target)
    findings: list[Finding] = []

    def require(condition: bool, requirement_id: str, message: str) -> None:
        if not condition:
            findings.append(Finding(requirement_id, path, message))

    require(report.get("schema_version") == 1, "PRF-FRM-013", "schema_version must be 1")
    require(
        report.get("standards_release") == EXPECTED_RELEASE,
        "CORE-VER-012",
        f"Conformance release must be pinned to {EXPECTED_RELEASE}",
    )
    require(
        report.get("standards_commit") == EXPECTED_COMMIT,
        "CORE-LCY-001",
        f"Conformance commit must be pinned to {EXPECTED_COMMIT}",
    )
    require(
        set(report.get("profiles", [])) == EXPECTED_PROFILES,
        "PRF-FRM-006",
        "Conformance profiles must be exactly PRF-BASE and PRF-PYS",
    )
    require(
        report.get("status") in {"remediated_pending_full_enforcement", "conformant"},
        "PRF-FRM-014",
        "Conformance status is invalid",
    )
    require(
        report.get("enforcement") in {"changed", "full"},
        "PRF-FRM-014",
        "Conformance enforcement mode is invalid",
    )
    require(
        report.get("unresolved_findings") == 0,
        "CORE-REQ-052",
        "Conformance report must have zero unresolved findings",
    )
    require(
        report.get("approved_exceptions") == [],
        "CORE-REQ-053",
        "This adoption has no approved exceptions",
    )
    require(
        report.get("deferred_requirements") == [],
        "CORE-REQ-020",
        "Future requirements must not be represented as deferred consumer obligations",
    )

    observed: set[str] = set()
    duplicates: set[str] = set()
    counts: dict[str, int] = {}
    results = report.get("results", [])
    require(isinstance(results, list), "PRF-FRM-014", "results must be an array")
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                findings.append(Finding("PRF-FRM-014", path, "Every result must be a table"))
                continue
            classification = str(result.get("classification", ""))
            verdict = str(result.get("verdict", ""))
            ids = result.get("ids", [])
            require(
                classification in EXPECTED_OUTCOME_COUNTS,
                "PRF-FRM-007",
                f"Unknown conformance classification {classification!r}",
            )
            require(
                verdict == EXPECTED_CONFORMANCE_VERDICTS.get(classification),
                "PRF-FRM-014",
                f"Invalid verdict {verdict!r} for {classification!r}",
            )
            require(
                bool(str(result.get("evidence", "")).strip()),
                "PRF-FRM-014",
                f"Conformance result {result.get('name')!r} has no evidence",
            )
            if not isinstance(ids, list):
                findings.append(Finding("PRF-FRM-014", path, "Result ids must be an array"))
                continue
            counts[classification] = counts.get(classification, 0) + len(ids)
            for requirement_id in map(str, ids):
                if requirement_id in observed:
                    duplicates.add(requirement_id)
                observed.add(requirement_id)
    require(not duplicates, "PRF-PYS-003", f"Duplicate conformance IDs: {sorted(duplicates)}")
    require(
        observed == EXPECTED_REQUIREMENTS,
        "PRF-PYS-005",
        "Conformance IDs differ from the resolved v0.1.1 requirement universe: "
        f"missing={sorted(EXPECTED_REQUIREMENTS - observed)}, "
        f"unexpected={sorted(observed - EXPECTED_REQUIREMENTS)}",
    )
    require(
        counts == EXPECTED_OUTCOME_COUNTS,
        "PRF-FRM-007",
        f"Conformance classifications must be {EXPECTED_OUTCOME_COUNTS}, got {counts}",
    )
    totals = report.get("totals", {})
    require(isinstance(totals, dict), "PRF-FRM-014", "totals must be a table")
    if isinstance(totals, dict):
        expected_totals = {
            "requirements": 114,
            "applicable": 89,
            "not_applicable": 15,
            "source_authority": 10,
            "pass": 89,
            "verified_source_authority": 10,
            "unresolved": 0,
        }
        require(
            totals == expected_totals,
            "PRF-FRM-014",
            f"Conformance totals must be {expected_totals}, got {totals}",
        )
    return findings


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _path_findings(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    siblings: dict[tuple[str, str], list[str]] = {}
    prohibited = {"bar", "final", "foo", "latest", "misc", "new", "old", "tmp"}
    for relative in paths:
        parts = relative.as_posix().split("/")
        parent = "/".join(parts[:-1])
        key = (parent, _normalized_name(parts[-1]))
        siblings.setdefault(key, []).append(relative.as_posix())
        if any(_normalized_name(part) in prohibited for part in parts):
            findings.append(
                Finding(
                    "CORE-NAM-082",
                    relative.as_posix(),
                    "Durable path contains an unqualified prohibited placeholder token",
                )
            )
    for group in siblings.values():
        if len(group) > 1:
            message = f"Normalized sibling collision: {', '.join(sorted(group))}"
            findings.extend(Finding("CORE-NAM-033", path, message) for path in group)
    return findings


def _local_link_target(repository: Path, markdown: Path, raw_target: str) -> Path | None:
    target = raw_target.strip("<>")
    parsed = urlsplit(target)
    if target.startswith(("#", "//")) or parsed.scheme.lower() in EXTERNAL_SCHEMES:
        return None
    if parsed.scheme or not parsed.path:
        return None
    path = Path(unquote(parsed.path.replace("\\", "/")))
    if parsed.path.startswith("/"):
        return (repository / str(path).lstrip("/")).resolve()
    return (markdown.parent / path).resolve()


def _has_exact_case(repository: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(repository)
    except ValueError:
        return False
    current = repository
    for part in relative.parts:
        try:
            names = {entry.name for entry in current.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        current /= part
    return True


def _documentation_findings(repository: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for relative in paths:
        posix = relative.as_posix()
        if relative.suffix.lower() != ".md" or posix.startswith(HISTORICAL_PREFIXES):
            continue
        target = repository / relative
        text = target.read_text(encoding="utf-8")
        if not re.search(r"(?m)^#\s+\S", text):
            findings.append(Finding("CORE-NAM-070", posix, "Document has no plain H1 title"))
        link_text = INLINE_CODE.sub("", FENCED_CODE.sub("", text))
        for pattern in (MARKDOWN_LINK, REFERENCE_LINK):
            for match in pattern.finditer(link_text):
                raw_target = match.group("target")
                link_target = _local_link_target(repository, target, raw_target)
                if link_target is None:
                    continue
                try:
                    link_target.relative_to(repository)
                except ValueError:
                    findings.append(
                        Finding("CORE-NAM-071", posix, f"Link escapes repository: {raw_target}")
                    )
                    continue
                if not link_target.exists():
                    findings.append(
                        Finding("CORE-NAM-071", posix, f"Missing link target: {raw_target}")
                    )
                elif not _has_exact_case(repository, link_target):
                    findings.append(
                        Finding(
                            "CORE-NAM-071",
                            posix,
                            f"Link target has incorrect case: {raw_target}",
                        )
                    )
    return findings


def _python_name_findings(repository: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for relative in paths:
        posix = relative.as_posix()
        if relative.suffix != ".py" or not posix.startswith(("src/polysia/", "scripts/")):
            continue
        stem = relative.stem
        if stem != "__init__" and (not SNAKE_CASE.fullmatch(stem) or keyword.iskeyword(stem)):
            findings.append(
                Finding("ENG-PY-006", posix, "Python module filename must be lowercase snake_case")
            )
        if posix.startswith("src/polysia/") and stem in sys.stdlib_module_names:
            findings.append(
                Finding(
                    "ENG-PY-006",
                    posix,
                    f"Module filename collides with Python standard-library module {stem!r}",
                )
            )
        try:
            tree = ast.parse((repository / relative).read_text(encoding="utf-8"), filename=posix)
        except (SyntaxError, UnicodeError) as error:
            findings.append(
                Finding("ENG-PY-008", posix, f"Unable to inspect Python syntax: {error}")
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not (SNAKE_CASE.fullmatch(node.name) or re.fullmatch(r"^__.*__$", node.name)):
                    findings.append(
                        Finding(
                            "ENG-PY-008",
                            posix,
                            f"Function {node.name!r} is not snake_case",
                            node.lineno,
                        )
                    )
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if node.args.vararg is not None:
                    arguments.append(node.args.vararg)
                if node.args.kwarg is not None:
                    arguments.append(node.args.kwarg)
                for argument in arguments:
                    if not SNAKE_CASE.fullmatch(argument.arg):
                        findings.append(
                            Finding(
                                "ENG-PY-008",
                                posix,
                                f"Parameter {argument.arg!r} is not snake_case",
                                argument.lineno,
                            )
                        )
            elif isinstance(node, ast.ClassDef) and not CAP_WORDS.fullmatch(node.name):
                findings.append(
                    Finding(
                        "ENG-PY-008",
                        posix,
                        f"Class {node.name!r} is not CapWords",
                        node.lineno,
                    )
                )
    return findings


def _project_findings(
    repository: Path, paths: list[Path], manifest: dict[str, object]
) -> list[Finding]:
    findings: list[Finding] = []
    pyproject = _load_toml(repository / "pyproject.toml")
    project = pyproject.get("project", {})
    if not isinstance(project, dict):
        return [Finding("ENG-PY-002", "pyproject.toml", "Missing [project] metadata")]
    if project.get("requires-python") != ">=3.14,<3.15":
        findings.append(
            Finding("ENG-PY-001", "pyproject.toml", "requires-python must be >=3.14,<3.15")
        )
    build_targets = pyproject.get("tool", {})
    if "src/polysia" not in json.dumps(build_targets, sort_keys=True):
        findings.append(
            Finding(
                "ENG-PY-004",
                "pyproject.toml",
                "Built package root src/polysia is not declared",
            )
        )
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict) or scripts.get("polysia") != "polysia.cli:app":
        findings.append(
            Finding("ENG-PY-010", "pyproject.toml", "Canonical polysia CLI entry point is missing")
        )

    dependency_names: set[str] = set()
    dependencies = project.get("dependencies", [])
    if isinstance(dependencies, list):
        for dependency in dependencies:
            match = re.match(r"[A-Za-z0-9_.-]+", str(dependency))
            if match:
                dependency_names.add(match.group(0).lower().replace("_", "-"))
    python_config = manifest.get("python", {})
    mappings: dict[str, str] = {}
    if isinstance(python_config, dict):
        raw_mappings = python_config.get("dependency_imports", {})
        if isinstance(raw_mappings, dict):
            mappings = {str(key): str(value) for key, value in raw_mappings.items()}
    imported_roots: set[str] = set()
    for relative in paths:
        if relative.suffix != ".py" or not relative.as_posix().startswith("src/polysia/"):
            continue
        tree = ast.parse((repository / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots.add(node.module.split(".")[0])
    third_party = imported_roots - sys.stdlib_module_names - {"polysia", "__future__"}
    for import_root in sorted(third_party):
        distribution = mappings.get(import_root)
        if distribution is None:
            findings.append(
                Finding(
                    "ENG-PY-015",
                    "standards/adoption.toml",
                    f"Third-party import {import_root!r} has no dependency mapping",
                )
            )
        elif distribution.lower().replace("_", "-") not in dependency_names:
            findings.append(
                Finding(
                    "ENG-PY-015",
                    "pyproject.toml",
                    f"Direct import {import_root!r} maps to undeclared dependency {distribution!r}",
                )
            )
    duplicate_configs = [
        path
        for path in ("mypy.ini", ".mypy.ini", "pytest.ini", "ruff.toml", ".ruff.toml", "setup.cfg")
        if (repository / path).exists()
    ]
    if duplicate_configs:
        findings.append(
            Finding(
                "ENG-PY-003",
                "pyproject.toml",
                f"Duplicate Python tool configuration sources exist: {duplicate_configs}",
            )
        )
    return findings


def _environment_findings(repository: Path) -> list[Finding]:
    findings: list[Finding] = []
    patterns = {
        ".env.example": re.compile(r"(?m)^APP_ENV=(?P<value>[A-Za-z0-9_-]+)$"),
        "deploy/polysia.env.example": re.compile(
            r"(?m)^APP_ENV=(?P<value>[A-Za-z0-9_-]+)$"
        ),
        "Dockerfile": re.compile(r"(?m)^ENV APP_ENV=(?P<value>[A-Za-z0-9_-]+)"),
        "compose.yaml": re.compile(r"(?m)^\s*APP_ENV:\s*(?P<value>[A-Za-z0-9_-]+)\s*$"),
        "src/polysia/config/settings.py": re.compile(
            r'app_env:\s*str\s*=\s*Field\(default="(?P<value>[A-Za-z0-9_-]+)"'
        ),
    }
    for path, pattern in patterns.items():
        text = (repository / path).read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            value = match.group("value")
            if value not in CANONICAL_ENVIRONMENTS:
                replacement = ENVIRONMENT_ALIASES.get(value, "a documented canonical token")
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    Finding(
                        "CORE-NAM-055",
                        path,
                        f"APP_ENV uses noncanonical token {value!r}; map it to {replacement!r}",
                        line,
                    )
                )
    return findings


def scan_repository(repository: Path, manifest: dict[str, object]) -> list[Finding]:
    paths = _tracked_paths(repository)
    findings = [
        *_manifest_findings(manifest),
        *_conformance_findings(repository),
        *_path_findings(paths),
        *_documentation_findings(repository, paths),
        *_python_name_findings(repository, paths),
        *_project_findings(repository, paths, manifest),
        *_environment_findings(repository),
    ]
    return sorted(set(findings))


def _baseline_fingerprints(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    baseline = _load_toml(path)
    raw_findings = baseline.get("findings", [])
    if not isinstance(raw_findings, list):
        raise ValueError("baseline findings must be an array")
    return {
        Finding(
            requirement_id=str(item["requirement_id"]),
            path=str(item["path"]),
            line=int(item.get("line", 0)),
            message=str(item["message"]),
        ).fingerprint
        for item in raw_findings
        if isinstance(item, dict)
    }


def _changed_paths(repository: Path, base: str, head: str) -> set[str]:
    resolved_base = base
    if not resolved_base or re.fullmatch(r"0+", resolved_base):
        resolved_base = _git(repository, "rev-parse", f"{head}^").stdout.decode().strip()
    _git(repository, "cat-file", "-e", f"{resolved_base}^{{commit}}")
    result = _git(
        repository,
        "diff",
        "--name-only",
        "--diff-filter=ACMRTUXB",
        "-z",
        resolved_base,
        head,
        "--",
    )
    return {item.decode() for item in result.stdout.split(b"\0") if item}


def classify_findings(
    findings: list[Finding],
    baseline: set[str],
    changed_paths: set[str],
    mode: str,
    allow_baseline: bool,
) -> tuple[list[Finding], list[Finding]]:
    acknowledged: list[Finding] = []
    blocking: list[Finding] = []
    for finding in findings:
        baselined = finding.fingerprint in baseline
        baseline_allowed = allow_baseline or (
            mode == "changed" and finding.path not in changed_paths
        )
        if baselined and baseline_allowed:
            acknowledged.append(finding)
        else:
            blocking.append(finding)
    return blocking, acknowledged


def _print_findings(label: str, findings: list[Finding]) -> None:
    for finding in findings:
        location = finding.path if finding.line == 0 else f"{finding.path}:{finding.line}"
        print(f"{label} {finding.requirement_id} {location}: {finding.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PolySia Standards adoption.")
    parser.add_argument("--mode", choices=("changed", "full"), default="changed")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--manifest", default="standards/adoption.toml")
    parser.add_argument("--baseline", default="standards/baseline.toml")
    parser.add_argument("--allow-baseline", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    arguments = parser.parse_args()

    repository = Path.cwd().resolve()
    manifest_path = (repository / arguments.manifest).resolve()
    baseline_path = (repository / arguments.baseline).resolve() if arguments.baseline else None
    try:
        manifest = _load_toml(manifest_path)
        findings = scan_repository(repository, manifest)
        baseline = _baseline_fingerprints(baseline_path)
        changed = (
            _changed_paths(repository, arguments.base, arguments.head)
            if arguments.mode == "changed"
            else set()
        )
        blocking, acknowledged = classify_findings(
            findings, baseline, changed, arguments.mode, arguments.allow_baseline
        )
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"Standards validation failed to execute: {error}")
        return 2
    except subprocess.CalledProcessError as error:
        details = b"\n".join(part for part in (error.stdout, error.stderr) if part)
        if details:
            print(details.decode(errors="replace").strip())
        print(f"Standards validation failed to execute: {error}")
        return 2

    if arguments.format == "json":
        print(
            json.dumps(
                {
                    "standards_release": EXPECTED_RELEASE,
                    "mode": arguments.mode,
                    "blocking": [asdict(finding) for finding in blocking],
                    "acknowledged_baseline": [asdict(finding) for finding in acknowledged],
                    "total_findings": len(findings),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_findings("BLOCK", blocking)
        _print_findings("BASELINE", acknowledged)
        print(
            "Standards validation summary: "
            f"mode={arguments.mode} blocking={len(blocking)} "
            f"acknowledged_baseline={len(acknowledged)} total={len(findings)}"
        )
    if blocking:
        print("Standards validation failed")
        return 1
    print("Standards validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
