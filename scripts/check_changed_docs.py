from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ZERO_SHA = re.compile(r"^0+$")
MARKDOWN_LINK = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?P<target><[^>\n]+>|[^)\s]+)",
)
REFERENCE_LINK = re.compile(
    r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?P<target><[^>\n]+>|[^\s]+)",
)
FENCED_CODE = re.compile(
    r"(?ms)^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=fence)[ \t]*$",
)
INLINE_CODE = re.compile(r"`+[^`\n]*`+")
EXTERNAL_SCHEMES = frozenset({"data", "http", "https", "mailto", "tel"})
ARCHITECTURE_ROOT = Path("docs/04-architecture/visual-system")
ALLOWED_ARCHITECTURE_STATUSES = frozenset(
    {"CURRENT", "TARGET", "FUTURE", "EXTERNAL", "MIXED"}
)
BASELINE_COMMIT = re.compile(r"Baseline Git commit: `(?P<value>[0-9a-f]{40})`")
INDEX_BASELINE_COMMIT = re.compile(r"(?m)^Baseline: `(?P<value>[0-9a-f]{40})`$")
REVIEW_DATE = re.compile(r"Review date: (?P<value>\d{4}-\d{2}-\d{2})")
INDEX_REVIEW_DATE = re.compile(r"(?m)^Reviewed: (?P<value>\d{4}-\d{2}-\d{2})$")
VIEW_DIAGRAM_ID = re.compile(r"(?m)^- \*\*Diagram ID:\*\* (?P<value>PSA-ARCH-\d{2})$")
VIEW_STATUS = re.compile(r"(?m)^- \*\*Architecture status:\*\* (?P<value>[A-Z]+)$")
VIEW_SOURCE_COMMIT = re.compile(
    r"(?m)^- \*\*Source commit:\*\* `(?P<value>[0-9a-f]{40})`$"
)
MERMAID_FENCE = re.compile(
    r"(?ms)^```mermaid[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t]*$"
)
ARCHITECTURE_STATUS_MARKER = re.compile(
    r"\[(?:CURRENT|TARGET|FUTURE|EXTERNAL)(?:[^\]]*)\]"
)
BACKTICK_PATH = re.compile(r"`(?P<value>[^`]+)`")
README_PHASE_HISTORY = re.compile(r"\bPhase\s+\d+(?:\.\d+)?\b", re.IGNORECASE)
OBSOLETE_TRACKED_PATHS = frozenset(
    {
        Path("README_SECRETS.md"),
        Path("plans/active/first-evidence-sprint.md"),
        Path("plans/active/tiny-live-round-trip-v1.md"),
        Path("plans/active/tiny-live-round-trip-v2.md"),
        Path("prompts/POLYSIA_CODEX_MASTER_PROMPT_FINAL_v1.1.md"),
        Path("prompts/POLYSIA_CODEX_START_FINAL.txt"),
    }
)
CURRENT_DOCUMENTS = (
    Path("README.md"),
    Path("docs/00-governance/PROJECT_STATUS.md"),
    Path("docs/18-ai-handoffs/README.md"),
    Path("docs/22-roadmap/roadmap.md"),
)
REQUIRED_README_LINKS = (
    "docs/00-governance/PROJECT_STATUS.md",
    "docs/04-architecture/README.md",
    "docs/10-operations/server-deployment.md",
    "docs/18-ai-handoffs/README.md",
    "docs/22-roadmap/roadmap.md",
)
TEMPORARY_DIRECTORY_NAMES = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
TEMPORARY_ROOT_DIRECTORIES = frozenset(
    {"artifacts", "build", "dist", "release-artifacts"}
)
TEMPORARY_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})
TEMPORARY_SUFFIXES = frozenset({".bak", ".orig", ".rej", ".tmp"})


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    )


def _resolve_base(repository: Path, requested_base: str, head: str) -> str:
    if requested_base and not ZERO_SHA.fullmatch(requested_base):
        _git(repository, "cat-file", "-e", f"{requested_base}^{{commit}}")
        return requested_base
    return _git(repository, "rev-parse", f"{head}^").stdout.decode().strip()


def _changed_paths(repository: Path, base: str, head: str) -> list[Path]:
    result = _git(
        repository,
        "diff",
        "--name-only",
        "--diff-filter=ACMRTUXB",
        "-z",
        base,
        head,
        "--",
    )
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def _tracked_paths(repository: Path) -> set[Path]:
    result = _git(repository, "ls-files", "-z")
    return {Path(item.decode()) for item in result.stdout.split(b"\0") if item}


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


def _validate_links(repository: Path, markdown: Path) -> list[str]:
    errors: list[str] = []
    text = markdown.read_text(encoding="utf-8")
    link_text = INLINE_CODE.sub("", FENCED_CODE.sub("", text))
    for pattern in (MARKDOWN_LINK, REFERENCE_LINK):
        for match in pattern.finditer(link_text):
            raw_target = match.group("target")
            target = _local_link_target(repository, markdown, raw_target)
            if target is None:
                continue
            try:
                target.relative_to(repository)
            except ValueError:
                errors.append(
                    f"{markdown.relative_to(repository)}: link escapes repository: {raw_target}"
                )
                continue
            if not target.exists():
                errors.append(
                    f"{markdown.relative_to(repository)}: missing link target: {raw_target}"
                )
            elif not _has_exact_case(repository, target):
                errors.append(
                    f"{markdown.relative_to(repository)}: link target has wrong case: {raw_target}"
                )
    return errors


def _is_temporary_tracked_path(path: Path) -> bool:
    if not path.parts:
        return False
    if path.parts[0] in TEMPORARY_ROOT_DIRECTORIES:
        return True
    if any(part in TEMPORARY_DIRECTORY_NAMES for part in path.parts):
        return True
    return (
        path.name in TEMPORARY_FILE_NAMES
        or path.name.endswith("~")
        or path.suffix.lower() in TEMPORARY_SUFFIXES
    )


def _validate_repository_hygiene(
    repository: Path,
    *,
    tracked_paths: set[Path] | None = None,
) -> list[str]:
    errors: list[str] = []
    tracked = _tracked_paths(repository) if tracked_paths is None else tracked_paths
    present_tracked = {
        path for path in tracked if (repository / path).exists()
    }

    for path in sorted(OBSOLETE_TRACKED_PATHS & present_tracked):
        errors.append(f"obsolete repository instruction is tracked: {path.as_posix()}")
    for path in sorted(present_tracked):
        if _is_temporary_tracked_path(path):
            errors.append(f"temporary or generated path is tracked: {path.as_posix()}")

    readme = repository / "README.md"
    if not readme.exists():
        errors.append("README.md is missing")
    else:
        readme_text = readme.read_text(encoding="utf-8")
        if README_PHASE_HISTORY.search(readme_text):
            errors.append("README.md contains numeric Phase-history language")
        link_text = INLINE_CODE.sub("", FENCED_CODE.sub("", readme_text))
        for target in REQUIRED_README_LINKS:
            if f"]({target})" not in link_text:
                errors.append(f"README.md lacks required current-document link: {target}")

    for relative in CURRENT_DOCUMENTS:
        markdown = repository / relative
        if not markdown.exists():
            errors.append(f"current documentation path is missing: {relative.as_posix()}")
        else:
            errors.extend(_validate_links(repository, markdown))
    return errors


def _match_value(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return None if match is None else match.group("value")


def _architecture_table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
            rows.append(cells)
    return rows


def _validate_repository_path(
    repository: Path,
    raw_path: str,
    *,
    context: str,
) -> list[str]:
    target = (repository / Path(raw_path.replace("\\", "/"))).resolve()
    try:
        target.relative_to(repository)
    except ValueError:
        return [f"{context}: path escapes repository: {raw_path}"]
    if not target.exists():
        return [f"{context}: missing repository path: {raw_path}"]
    if not _has_exact_case(repository, target):
        return [f"{context}: repository path has wrong case: {raw_path}"]
    return []


def _validate_traceability(repository: Path, register: Path) -> list[str]:
    errors: list[str] = []
    rows = _architecture_table_rows(register.read_text(encoding="utf-8"))
    if not rows:
        return [f"{register.relative_to(repository)}: traceability table is missing"]

    header = rows[0]
    required_columns = ("Diagram element", "Status", "Repository path", "Test / evidence")
    if any(column not in header for column in required_columns):
        return [
            f"{register.relative_to(repository)}: traceability table is missing required columns"
        ]

    indexes = {column: header.index(column) for column in required_columns}
    for cells in rows[1:]:
        if len(cells) != len(header):
            errors.append(
                f"{register.relative_to(repository)}: malformed traceability row: "
                f"{' | '.join(cells)}"
            )
            continue
        status = cells[indexes["Status"]]
        if status not in ALLOWED_ARCHITECTURE_STATUSES:
            errors.append(
                f"{register.relative_to(repository)}: invalid traceability status {status!r}"
            )
            continue
        if status != "CURRENT":
            continue

        element = cells[indexes["Diagram element"]]
        context = f"{register.relative_to(repository)} ({element})"
        for column in ("Repository path", "Test / evidence"):
            values = [
                match.group("value")
                for match in BACKTICK_PATH.finditer(cells[indexes[column]])
            ]
            if not values:
                errors.append(f"{context}: CURRENT row has no verified {column.lower()}")
                continue
            for value in values:
                errors.extend(_validate_repository_path(repository, value, context=context))
    return errors


def _validate_architecture_docs(repository: Path) -> list[str]:
    errors: list[str] = []
    root = repository / ARCHITECTURE_ROOT
    sources = root / "sources"
    views = root / "views"
    rendered = root / "rendered"
    readme = root / "README.md"
    index = root / "architecture-visualization-index.md"
    register = root / "traceability-register.md"

    required = (sources, views, rendered, readme, index, register)
    missing = [path.relative_to(repository).as_posix() for path in required if not path.exists()]
    if missing:
        return [f"architecture documentation path is missing: {path}" for path in missing]

    readme_text = readme.read_text(encoding="utf-8")
    index_text = index.read_text(encoding="utf-8")
    baseline = _match_value(BASELINE_COMMIT, readme_text)
    index_baseline = _match_value(INDEX_BASELINE_COMMIT, index_text)
    review_date = _match_value(REVIEW_DATE, readme_text)
    index_review_date = _match_value(INDEX_REVIEW_DATE, index_text)
    if baseline is None:
        errors.append(f"{readme.relative_to(repository)}: baseline commit metadata is missing")
    if index_baseline is None:
        errors.append(f"{index.relative_to(repository)}: baseline commit metadata is missing")
    if baseline is not None and index_baseline is not None and baseline != index_baseline:
        errors.append("architecture README and index baseline commits do not match")
    if review_date is None:
        errors.append(f"{readme.relative_to(repository)}: review date metadata is missing")
    if index_review_date is None:
        errors.append(f"{index.relative_to(repository)}: review date metadata is missing")
    if (
        review_date is not None
        and index_review_date is not None
        and review_date != index_review_date
    ):
        errors.append("architecture README and index review dates do not match")
    for vocabulary in ("CURRENT", "TARGET", "FUTURE", "EXTERNAL"):
        if f"`{vocabulary}`" not in readme_text:
            errors.append(
                f"{readme.relative_to(repository)}: required status {vocabulary} is missing"
            )

    source_paths = {path.stem: path for path in sources.glob("*.mmd")}
    view_paths = {path.stem: path for path in views.glob("*.md")}
    rendered_paths = {path.stem: path for path in rendered.glob("*.svg")}
    all_stems = set(source_paths) | set(view_paths) | set(rendered_paths)
    if not all_stems:
        errors.append(f"{ARCHITECTURE_ROOT}: no diagram triples were found")

    index_rows = {
        cells[0]: cells
        for cells in _architecture_table_rows(index_text)
        if cells and re.fullmatch(r"PSA-ARCH-\d{2}", cells[0])
    }
    seen_ids: set[str] = set()
    for stem in sorted(all_stems):
        expected_id = f"PSA-ARCH-{stem[:2]}"
        source = source_paths.get(stem)
        view = view_paths.get(stem)
        svg = rendered_paths.get(stem)
        for label, path in (("source", source), ("view", view), ("rendered SVG", svg)):
            if path is None:
                errors.append(f"{expected_id}: {label} is missing for {stem}")
        if source is None or view is None:
            continue

        if svg is not None:
            svg_text = svg.read_text(encoding="utf-8")
            if "<svg" not in svg_text or "</svg>" not in svg_text:
                errors.append(f"{svg.relative_to(repository)}: rendered SVG is malformed")

        source_text = source.read_text(encoding="utf-8").rstrip("\r\n")
        view_text = view.read_text(encoding="utf-8")
        diagram_id = _match_value(VIEW_DIAGRAM_ID, view_text)
        status = _match_value(VIEW_STATUS, view_text)
        source_commit = _match_value(VIEW_SOURCE_COMMIT, view_text)
        if diagram_id != expected_id:
            errors.append(f"{view.relative_to(repository)}: expected diagram ID {expected_id}")
        elif diagram_id in seen_ids:
            errors.append(f"{view.relative_to(repository)}: duplicate diagram ID {diagram_id}")
        else:
            seen_ids.add(diagram_id)
        if status not in ALLOWED_ARCHITECTURE_STATUSES:
            errors.append(f"{view.relative_to(repository)}: invalid architecture status {status!r}")
        if baseline is not None and source_commit != baseline:
            errors.append(
                f"{view.relative_to(repository)}: source commit does not match baseline {baseline}"
            )
        mermaid = MERMAID_FENCE.search(view_text)
        if mermaid is None:
            errors.append(f"{view.relative_to(repository)}: Mermaid diagram fence is missing")
        elif mermaid.group("body").rstrip("\r\n") != source_text:
            errors.append(f"{view.relative_to(repository)}: Mermaid view is not synchronized")
        if ARCHITECTURE_STATUS_MARKER.search(source_text) is None:
            errors.append(
                f"{source.relative_to(repository)}: architecture status marker is missing"
            )

        row = index_rows.get(expected_id)
        if row is None:
            errors.append(f"{index.relative_to(repository)}: {expected_id} is missing")
            continue
        expected_targets = (
            f"sources/{stem}.mmd",
            f"views/{stem}.md",
            f"rendered/{stem}.svg",
        )
        for target in expected_targets:
            if f"]({target})" not in " | ".join(row):
                errors.append(f"{index.relative_to(repository)}: {expected_id} lacks {target}")
        if status is not None and len(row) > 2 and row[2] != status:
            errors.append(
                f"{index.relative_to(repository)}: {expected_id} status {row[2]!r} "
                f"does not match view status {status!r}"
            )

    expected_ids = {f"PSA-ARCH-{stem[:2]}" for stem in all_stems}
    for unexpected in sorted(set(index_rows) - expected_ids):
        errors.append(f"{index.relative_to(repository)}: unexpected diagram row {unexpected}")

    for markdown in sorted((repository / "docs/04-architecture").rglob("*.md")):
        errors.extend(_validate_links(repository, markdown))
    errors.extend(_validate_traceability(repository, register))
    return errors


def validate(repository: Path, requested_base: str, head: str) -> list[str]:
    base = _resolve_base(repository, requested_base, head)
    _git(repository, "diff", "--check", base, head, "--")

    errors: list[str] = []
    changed_paths = _changed_paths(repository, base, head)
    for relative in changed_paths:
        target = (repository / relative).resolve()
        try:
            target.relative_to(repository)
        except ValueError:
            errors.append(f"changed path escapes repository: {relative.as_posix()}")
            continue
        if not target.exists():
            errors.append(f"changed path does not exist: {relative.as_posix()}")
            continue
        if not _has_exact_case(repository, target):
            errors.append(f"changed path has wrong case: {relative.as_posix()}")
            continue
        if target.suffix.lower() == ".md":
            errors.extend(_validate_links(repository, target))

    errors.extend(_validate_repository_hygiene(repository))
    errors.extend(_validate_architecture_docs(repository))

    print(f"checked {len(changed_paths)} changed path(s) from {base} to {head}")
    print("checked repository documentation hygiene")
    print("checked architecture documentation consistency")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a CI diff and local Markdown links.")
    parser.add_argument("--base", default="", help="Base commit, or empty/zero for HEAD parent.")
    parser.add_argument("--head", default="HEAD", help="Head commit to validate.")
    parser.add_argument(
        "--architecture-only",
        action="store_true",
        help="Validate the current architecture corpus without resolving a Git diff.",
    )
    arguments = parser.parse_args()

    repository = Path.cwd().resolve()
    try:
        if arguments.architecture_only:
            errors = _validate_architecture_docs(repository)
            print("checked architecture documentation consistency")
        else:
            errors = validate(repository, arguments.base, arguments.head)
    except subprocess.CalledProcessError as error:
        details = b"\n".join(part for part in (error.stdout, error.stderr) if part)
        if details:
            print(details.decode(errors="replace").strip())
        print(f"changed-file validation failed: {error}")
        return 1
    except (OSError, UnicodeError) as error:
        print(f"changed-file validation failed: {error}")
        return 1

    for error in errors:
        print(error)
    if errors:
        print(f"changed-file validation failed with {len(errors)} finding(s)")
        return 1
    if arguments.architecture_only:
        print("architecture documentation validation passed")
    else:
        print("changed-file validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
