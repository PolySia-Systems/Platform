from __future__ import annotations

from pathlib import Path

from scripts.check_changed_docs import _validate_architecture_docs

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
        text.replace(BASELINE, "b" * 40).replace("Example [CURRENT]", "Stale [CURRENT]"),
        encoding="utf-8",
    )
    svg = repository / "docs/04-architecture/visual-system/rendered/01-example.svg"
    svg.write_text("not an SVG\n", encoding="utf-8")

    errors = _validate_architecture_docs(repository)

    assert any("source commit does not match baseline" in error for error in errors)
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
