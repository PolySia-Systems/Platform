"""Bounded indexes of instruction, requirement, and ADR owners.

This is a path catalog, not a second knowledge base. File contents remain
owned by Git, requirements, and approved ADRs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PACKET_VERSION = "developer-context-packet-v1"
DOCUMENTATION_ENTRANCE = "docs/README.md"
ROOT_AGENTS = "AGENTS.md"
ADR_DIRECTORY = "docs/04-architecture/adrs"
REQUIREMENTS_DIRECTORY = "docs/03-requirements"
MAX_NON_SAFETY_EXCERPT_CHARS = 4_000
SAFETY_SECTION_MARKERS = (
    "## 6. Architectural Invariants",
    "## 7. Runtime and Trading Safety",
    "## 8. Scope and Change Discipline",
)


@dataclass(frozen=True, slots=True)
class CatalogHit:
    path: str
    role: str
    why: str
    safety: bool = False


SCOPE_RULES: tuple[tuple[tuple[str, ...], tuple[CatalogHit, ...]], ...] = (
    (
        ("src/polysia/adapters/polymarket/",),
        (
            CatalogHit(
                "src/polysia/adapters/polymarket/AGENTS.md",
                "instruction",
                "Nested adapter MUST/NEVER rules apply on this path.",
                True,
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0004-polymarket-first-adapter.md",
                "adr",
                "Polymarket is the first venue adapter, not the product identity.",
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0005-polymarket-sdk.md",
                "adr",
                "SDK confinement and upgrade/rollback rules live here.",
            ),
        ),
    ),
    (
        (
            "src/polysia/deployment/",
            "src/polysia/backtesting/",
            "src/polysia/domain/research_evidence/",
            "src/polysia/application/services/persistent_prospective_collector.py",
            "src/polysia/application/services/prospective_collector.py",
            "docs/03-requirements/prospective-evidence-collector.md",
        ),
        (
            CatalogHit(
                "docs/03-requirements/prospective-evidence-collector.md",
                "requirement",
                "Required prospective collection, replay, and Runner behavior.",
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0017-research-evidence-store.md",
                "adr",
                "Isolated research-evidence store and Runner orchestration.",
            ),
            CatalogHit(
                "docs/10-operations/server-deployment.md",
                "runbook",
                "Operator start/resume/finalize for the research Runner.",
            ),
        ),
    ),
    (
        ("src/polysia/control/",),
        (
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0012-shadow-control-kernel.md",
                "adr",
                "Control Kernel ownership and SHADOW-only authority.",
            ),
        ),
    ),
    (
        ("src/polysia/risk/", "src/polysia/execution/", "src/polysia/cli_commands/live.py"),
        (
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0008-live-safety-gates.md",
                "adr",
                "Live gates cannot be weakened by tooling or a context packet.",
                True,
            ),
            CatalogHit(
                "docs/03-requirements/live-verified-state-and-approved-order.md",
                "requirement",
                "Verified Live state and exact approved-order contract.",
                True,
            ),
        ),
    ),
    (
        ("docs/04-architecture/",),
        (
            CatalogHit(
                "docs/04-architecture/AGENTS.md",
                "instruction",
                "Architecture CURRENT/TARGET labeling and diagram rules.",
                True,
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0010-document-architecture.md",
                "adr",
                "Canonical documentation architecture and archive policy.",
            ),
        ),
    ),
    (
        ("tests/",),
        (
            CatalogHit(
                "tests/AGENTS.md",
                "instruction",
                "Test-layer boundaries and non-mutating ordinary tests.",
                True,
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0009-testing-layers.md",
                "adr",
                "Approved testing-layer responsibilities.",
            ),
        ),
    ),
    (
        ("src/polysia/developer/", "src/polysia/cli_commands/developer.py"),
        (
            CatalogHit(
                "docs/03-requirements/developer-context-packet.md",
                "requirement",
                "Required developer-context packet behavior.",
            ),
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0018-developer-context-packets.md",
                "adr",
                "Packets are disposable views, not project truth.",
            ),
        ),
    ),
    (
        ("src/polysia/storage/",),
        (
            CatalogHit(
                "docs/04-architecture/adrs/ADR-0006-sqlite-mvp.md",
                "adr",
                "SQLite remains the CURRENT persistence choice.",
            ),
        ),
    ),
)


ALWAYS_HITS: tuple[CatalogHit, ...] = (
    CatalogHit(
        ROOT_AGENTS,
        "instruction",
        "Root operating instructions and safety invariants.",
        True,
    ),
    CatalogHit(
        DOCUMENTATION_ENTRANCE,
        "documentation_entrance",
        "Canonical documentation entrance; do not add a parallel wiki.",
    ),
    CatalogHit(
        "docs/04-architecture/adrs/ADR-0002-modular-monolith-hexagonal.md",
        "adr",
        "CURRENT architecture is one Python modular monolith.",
    ),
    CatalogHit(
        "docs/04-architecture/adrs/ADR-0008-live-safety-gates.md",
        "adr",
        "Safety remains independent of developer tooling.",
        True,
    ),
)


def posix(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized).as_posix()


def discover_instruction_files(root: Path, scope: tuple[str, ...]) -> tuple[str, ...]:
    """Load at most one AGENTS file per directory from root toward each scope path."""

    ordered: list[str] = []
    seen: set[str] = set()
    targets = scope or (ROOT_AGENTS,)
    for target in targets:
        relative = posix(target)
        parts = PurePosixPath(relative).parts
        directories = [Path(".")]
        current = Path()
        walk = parts if (root / relative).is_dir() else parts[:-1]
        for part in walk:
            current = current / part
            directories.append(current)
        for directory in directories:
            chosen = _agents_in(root, directory)
            if chosen is None or chosen in seen:
                continue
            seen.add(chosen)
            ordered.append(chosen)
    return tuple(ordered)


def _agents_in(root: Path, directory: Path) -> str | None:
    override = directory / "AGENTS.override.md"
    agents = directory / "AGENTS.md"
    if (root / override).is_file():
        return posix(override.as_posix())
    if (root / agents).is_file():
        return posix(agents.as_posix())
    return None


def catalog_for(scope: tuple[str, ...]) -> tuple[CatalogHit, ...]:
    hits = list(ALWAYS_HITS)
    seen = {hit.path for hit in hits}
    for prefixes, matched in SCOPE_RULES:
        if scope and not any(_scope_matches(item, prefixes) for item in scope):
            continue
        if not scope:
            continue
        for hit in matched:
            if hit.path in seen:
                continue
            seen.add(hit.path)
            hits.append(hit)
    return tuple(hits)


def _scope_matches(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = posix(path)
    return any(
        normalized == prefix.rstrip("/")
        or normalized.startswith(prefix)
        or prefix.rstrip("/").startswith(normalized)
        for prefix in prefixes
    )


def gates_for(change_map: object) -> tuple[dict[str, object], ...]:
    quality = bool(getattr(change_map, "quality", False))
    python = bool(getattr(change_map, "python", False))
    package = bool(getattr(change_map, "package", False))
    container = bool(getattr(change_map, "container", False))
    dependencies = bool(getattr(change_map, "dependencies", False))
    gates: list[dict[str, object]] = [
        {
            "command": "git diff --check",
            "applies": True,
            "why": "Whitespace and conflict-marker hygiene for every delivery.",
            "owner": "CI quality job / AGENTS.md validation policy",
        },
        {
            "command": "python scripts/validate_standards.py --mode full",
            "applies": quality,
            "why": "Adopted Standards pin and local evidence stay valid.",
            "owner": ".github/workflows/ci.yml quality job",
        },
        {
            "command": "python -m polysia.security.secret_scan",
            "applies": quality,
            "why": "Tracked content must not introduce secrets.",
            "owner": ".github/workflows/ci.yml quality job",
        },
        {
            "command": "python -m compileall -q src tests",
            "applies": python,
            "why": "Python syntax of the package and tests.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python -m ruff check .",
            "applies": python,
            "why": "Lint of the changed Python surface.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python -m mypy src",
            "applies": python,
            "why": "Type check of the package.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python -m pytest -q",
            "applies": python,
            "why": "Behavior, contract, and safety tests.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python -m pip check",
            "applies": python,
            "why": "Installed environment integrity.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python scripts/dependency_locks.py check",
            "applies": python,
            "why": "Lock files remain synchronized with pyproject.toml.",
            "owner": "scripts/classify_ci_changes.py python patterns",
        },
        {
            "command": "python -m build",
            "applies": package,
            "why": "Packaging metadata and build reproducibility.",
            "owner": "scripts/classify_ci_changes.py package patterns",
        },
        {
            "command": "docker build --tag polysia:ci .",
            "applies": container,
            "why": "Image and CLI entry remain buildable.",
            "owner": "scripts/classify_ci_changes.py container patterns",
        },
        {
            "command": "python -m pip_audit --strict --vulnerability-service osv",
            "applies": dependencies,
            "why": "Supply-chain audit applies only when dependency inputs change.",
            "owner": "AGENTS.md supply-chain gates / CI dependencies job",
        },
        {
            "command": (
                "cyclonedx-py environment --output-format JSON "
                "--output-file artifacts/sbom.json"
            ),
            "applies": dependencies,
            "why": "SBOM generation applies only when dependency inputs change.",
            "owner": "AGENTS.md supply-chain gates / CI dependencies job",
        },
    ]
    return tuple(gates)
