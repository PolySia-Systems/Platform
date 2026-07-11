from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class SecretFinding:
    path: str
    rule: str


RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "api-secret-assignment",
        re.compile(
            r"(?im)(?:API_SECRET|API_PASSPHRASE)[ \t]*[:=][ \t]*"
            r"[\"']?(?![ \t]*(?:$|none\b|redacted\b))[^\s\"']{16,}"
        ),
    ),
)

PRIVATE_KEY_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?im)(?:POLYMARKET_)?PRIVATE_KEY[ \t]*[:=][ \t]*"
    r"[\"']?(?P<secret>(?:0x)?[0-9A-Fa-f]{64})(?![0-9A-Fa-f])"
)
HEX_PRIVATE_KEY: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Fa-f])0x(?P<secret>[0-9A-Fa-f]{64})(?![0-9A-Fa-f])"
)

FORBIDDEN_TRACKED_NAMES: Final[frozenset[str]] = frozenset({".env", ".env.local"})
FORBIDDEN_TRACKED_SUFFIXES: Final[tuple[str, ...]] = (".key", ".pem")


def scan_text(text: str, *, path: str) -> list[SecretFinding]:
    findings = [
        SecretFinding(path=path, rule=name) for name, pattern in RULES if pattern.search(text)
    ]
    for name, pattern in (
        ("private-key-assignment", PRIVATE_KEY_ASSIGNMENT),
        ("hex-private-key", HEX_PRIVATE_KEY),
    ):
        matches_secret = any(
            _is_plausible_private_key(match.group("secret"))
            for match in pattern.finditer(text)
        )
        if matches_secret:
            findings.append(SecretFinding(path=path, rule=name))
    return findings


def _is_plausible_private_key(value: str) -> bool:
    payload = value.removeprefix("0x").lower()
    # Repeated single-character keys are invalid fixtures used in legacy tests.
    return len(set(payload)) > 1


def tracked_files(repository: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return [repository / item.decode() for item in result.stdout.split(b"\0") if item]


def scan_repository(repository: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in tracked_files(repository):
        relative = path.relative_to(repository).as_posix()
        lowered_name = path.name.lower()
        if lowered_name in FORBIDDEN_TRACKED_NAMES or lowered_name.endswith(
            FORBIDDEN_TRACKED_SUFFIXES
        ):
            findings.append(SecretFinding(path=relative, rule="forbidden-secret-file"))
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        findings.extend(scan_text(raw.decode("utf-8", errors="replace"), path=relative))
    return findings


def main() -> int:
    repository = Path.cwd().resolve()
    findings = scan_repository(repository)
    for finding in findings:
        print(f"{finding.path}: {finding.rule}")
    if findings:
        print(f"secret scan failed with {len(findings)} finding(s)")
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
