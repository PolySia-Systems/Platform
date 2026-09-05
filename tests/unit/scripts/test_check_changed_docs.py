from __future__ import annotations

from pathlib import Path

from scripts.check_changed_docs import (
    _validate_architecture_docs,
    _validate_current_deployment_topology,
    _validate_project_status,
    _validate_repository_hygiene,
)

BASELINE = "a" * 40
SOURCE = "flowchart LR\n  A[\"Example [CURRENT]\"]"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _architecture_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    visual = root / "docs/04-architecture/visual-system"
    _write(root / "src/example.py", "VALUE = 1\n")
    _write(root / "tests/test_example.py", "def test_example():\n    assert True\n")
    _write(
        visual / "README.md",
        "\n".join(
            (
                "# Visual architecture",
                "",
                f"- Baseline Git commit: `{BASELINE}`",
                "- Review date: 2026-08-18",
                "",
                "`CURRENT`, `TARGET`, `FUTURE`, and `EXTERNAL` are explicit.",
            )
        ),
    )
    _write(
        visual / "architecture-visualization-index.md",
        "\n".join(
            (
                "# Index",
                "",
                f"Baseline: `{BASELINE}`",
                "Reviewed: 2026-08-18",
                "",
                "| ID | View | Status | Canonical Mermaid | Documentation | SVG |",
                "|---|---|---|---|---|---|",
                "| PSA-ARCH-01 | Example | CURRENT | "
                "[source](sources/01-example.mmd) | "
                "[view](views/01-example.md) | "
                "[SVG](rendered/01-example.svg) |",
            )
        ),
    )
    _write(visual / "sources/01-example.mmd", f"{SOURCE}\n")
    _write(
        visual / "views/01-example.md",
        "\n".join(
            (
                "# Example",
                "",
                "- **Diagram ID:** PSA-ARCH-01",
                "- **Architecture status:** CURRENT",
                f"- **Source commit:** `{BASELINE}`",
                "- **Reviewed:** 2026-08-18",
                "",
                "[Canonical source](../sources/01-example.mmd)",
                "",
                "```mermaid",
                SOURCE,
                "```",
                "",
                "[Rendered SVG](../rendered/01-example.svg)",
            )
        ),
    )
    _write(
        visual / "rendered/01-example.svg",
        "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n",
    )
    _write(
        visual / "traceability-register.md",
        "\n".join(
            (
                "# Traceability",
                "",
                "| Diagram element | Status | Repository path | Test / evidence | "
                "Capability | ADR | Notes |",
                "|---|---|---|---|---|---|---|",
                "| Example | CURRENT | `src/example.py` | `tests/test_example.py` | "
                "— | — | Verified |",
            )
        ),
    )
    return root


def _current_docs_repository(tmp_path: Path) -> tuple[Path, set[Path]]:
    root = tmp_path / "repository"
    required_targets = (
        Path("docs/README.md"),
        Path("docs/00-governance/PROJECT_STATUS.md"),
        Path("docs/04-architecture/README.md"),
        Path("docs/10-operations/server-deployment.md"),
        Path("docs/18-ai-handoffs/README.md"),
        Path("docs/22-roadmap/roadmap.md"),
    )
    links = "\n".join(
        f"- [{target.stem}]({target.as_posix()})" for target in required_targets
    )
    _write(root / "README.md", f"# PolySia\n\n{links}\n")
    for target in required_targets:
        if target == Path("docs/00-governance/PROJECT_STATUS.md"):
            _write(
                root / target,
                "\n".join(
                    (
                        "# Project status",
                        "",
                        "## Truth ownership",
                        "",
                        "Runtime SHA, health, and restarts must be queried on the host.",
                        "",
                    )
                ),
            )
        else:
            _write(root / target, f"# {target.stem}\n")
    return root, {Path("README.md"), *required_targets}


def test_architecture_validator_accepts_synchronized_corpus(tmp_path: Path) -> None:
    repository = _architecture_repository(tmp_path)

    assert _validate_architecture_docs(repository) == []


def test_architecture_validator_reports_source_view_and_baseline_drift(
    tmp_path: Path,
) -> None:
    repository = _architecture_repository(tmp_path)
    view = repository / "docs/04-architecture/visual-system/views/01-example.md"
    text = view.read_text(encoding="utf-8")
    view.write_text(
        text.replace(BASELINE, "b" * 40)
        .replace("- **Reviewed:** 2026-08-18", "- **Reviewed:** 2026-08-19")
        .replace("Example [CURRENT]", "Stale [CURRENT]"),
        encoding="utf-8",
    )
    svg = repository / "docs/04-architecture/visual-system/rendered/01-example.svg"
    svg.write_text("not an SVG\n", encoding="utf-8")

    errors = _validate_architecture_docs(repository)

    assert any("source commit does not match baseline" in error for error in errors)
    assert any("review date does not match corpus" in error for error in errors)
    assert any("Mermaid view is not synchronized" in error for error in errors)
    assert any("rendered SVG is malformed" in error for error in errors)


def test_architecture_validator_reports_missing_traceability_evidence(
    tmp_path: Path,
) -> None:
    repository = _architecture_repository(tmp_path)
    register = repository / "docs/04-architecture/visual-system/traceability-register.md"
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            "`tests/test_example.py`",
            "no path",
        ),
        encoding="utf-8",
    )

    errors = _validate_architecture_docs(repository)

    assert any("CURRENT row has no verified test / evidence" in error for error in errors)


def test_repository_hygiene_accepts_current_navigation(tmp_path: Path) -> None:
    repository, tracked_paths = _current_docs_repository(tmp_path)

    assert (
        _validate_repository_hygiene(repository, tracked_paths=tracked_paths) == []
    )


def test_repository_hygiene_reports_obsolete_phase_and_temporary_paths(
    tmp_path: Path,
) -> None:
    repository, tracked_paths = _current_docs_repository(tmp_path)
    readme = repository / "README.md"
    readme.write_text("# PolySia\n\n## Phase 12\n", encoding="utf-8")
    obsolete = Path("prompts/POLYSIA_CODEX_START_FINAL.txt")
    temporary = Path("artifacts/report.json")
    _write(repository / obsolete, "obsolete\n")
    _write(repository / temporary, "{}\n")
    tracked_paths.update({obsolete, temporary})

    errors = _validate_repository_hygiene(
        repository,
        tracked_paths=tracked_paths,
    )

    assert any("obsolete repository instruction is tracked" in error for error in errors)
    assert any("temporary or generated path is tracked" in error for error in errors)
    assert any("numeric Phase-history language" in error for error in errors)
    assert any("lacks required current-document link" in error for error in errors)


def test_repository_hygiene_rejects_proven_current_truth_drift(tmp_path: Path) -> None:
    repository, tracked_paths = _current_docs_repository(tmp_path)
    adoption = Path("docs/00-governance/standards-adoption-v0.4.0.md")
    schema_v5 = Path("docs/18-ai-handoffs/stage4b-data-ownership-cutover.md")
    _write(repository / adoption, "Use `locks/pip-py314.lock`.\n")
    _write(repository / schema_v5, "Status: CURRENT. Schema v5.\n")
    tracked_paths.update({adoption, schema_v5})

    errors = _validate_repository_hygiene(
        repository,
        tracked_paths=tracked_paths,
    )

    assert any("references retired dependency lock" in error for error in errors)
    assert any("schema-v5 evidence must not claim CURRENT" in error for error in errors)


def test_current_deployment_topology_rejects_all_stages_as_ephemeral() -> None:
    source = 'WalletJobs["Ephemeral jobs\\nStages 1-4B; DATA_ONLY"]'

    assert _validate_current_deployment_topology(source) == [
        "Deployment View 13 must not describe Wallet Intelligence "
        "Stages 1-4B as one ephemeral unit"
    ]


def test_project_status_accepts_dated_audited_snapshot(tmp_path: Path) -> None:
    repository, _tracked = _current_docs_repository(tmp_path)
    status = repository / "docs/00-governance/PROJECT_STATUS.md"
    status.write_text(
        "\n".join(
            (
                "# Project status",
                "",
                "## Truth ownership",
                "",
                "Runtime SHA, health, and restarts must be queried on the host.",
                "",
                "## Audited runtime snapshot",
                "",
                "Audited as of 2026-09-02.",
                "",
                f"Audited commit `{BASELINE}`.",
                "",
            )
        ),
        encoding="utf-8",
    )

    assert _validate_project_status(repository) == []


def test_project_status_rejects_missing_audited_as_of(tmp_path: Path) -> None:
    repository, _tracked = _current_docs_repository(tmp_path)
    status = repository / "docs/00-governance/PROJECT_STATUS.md"
    status.write_text(
        "\n".join(
            (
                "# Project status",
                "",
                "## Truth ownership",
                "",
                "Runtime SHA, health, and restarts must be queried on the host.",
                "",
                "## Audited runtime snapshot",
                "",
                f"Release `{BASELINE}`.",
                "",
            )
        ),
        encoding="utf-8",
    )

    errors = _validate_project_status(repository)

    assert any("Audited as of YYYY-MM-DD" in error for error in errors)


def test_project_status_rejects_malformed_audited_as_of(tmp_path: Path) -> None:
    repository, _tracked = _current_docs_repository(tmp_path)
    status = repository / "docs/00-governance/PROJECT_STATUS.md"
    status.write_text(
        "\n".join(
            (
                "# Project status",
                "",
                "## Truth ownership",
                "",
                "Runtime SHA, health, and restarts must be queried on the host.",
                "",
                "## Audited runtime snapshot",
                "",
                "Audited as of 2 September 2026.",
                "",
            )
        ),
        encoding="utf-8",
    )

    errors = _validate_project_status(repository)

    assert any("Audited as of YYYY-MM-DD" in error for error in errors)


def test_project_status_rejects_known_live_style_patterns(tmp_path: Path) -> None:
    repository, _tracked = _current_docs_repository(tmp_path)
    status = repository / "docs/00-governance/PROJECT_STATUS.md"
    status.write_text(
        "\n".join(
            (
                "# Project status",
                "",
                "| Last verified deployed baseline | "
                f"`{BASELINE}` |",
                "",
                "## Current Helsinki DATA_ONLY deployment",
                "",
            )
        ),
        encoding="utf-8",
    )

    errors = _validate_project_status(repository)

    assert any("missing Truth ownership section" in error for error in errors)
    assert any("must be queried" in error for error in errors)
    assert any("known prohibited live-style field" in error for error in errors)
    assert any("known prohibited live-style heading" in error for error in errors)


def test_project_status_allows_unrelated_commit_sha(tmp_path: Path) -> None:
    repository, _tracked = _current_docs_repository(tmp_path)
    status = repository / "docs/00-governance/PROJECT_STATUS.md"
    status.write_text(
        "\n".join(
            (
                "# Project status",
                "",
                "## Truth ownership",
                "",
                "Runtime SHA, health, and restarts must be queried on the host.",
                "",
                "Standards pin "
                f"`{BASELINE}` is not a live runtime claim.",
                "",
            )
        ),
        encoding="utf-8",
    )

    assert _validate_project_status(repository) == []
