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

    print(f"checked {len(changed_paths)} changed path(s) from {base} to {head}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a CI diff and local Markdown links.")
    parser.add_argument("--base", default="", help="Base commit, or empty/zero for HEAD parent.")
    parser.add_argument("--head", default="HEAD", help="Head commit to validate.")
    arguments = parser.parse_args()

    repository = Path.cwd().resolve()
    try:
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
    print("changed-file validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
