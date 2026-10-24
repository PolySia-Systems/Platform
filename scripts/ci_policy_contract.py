"""Dependency-free policy/Gate contracts, mandatory even for editorial PRs."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.classify_ci_changes import (  # noqa: E402
    JOB_FLAGS,
    actual_diff,
    classify_paths,
    project_policy,
    validate_projection,
    verify_gate,
)


class PolicyContracts(unittest.TestCase):
    def test_dependency_free_runner_python_compatibility(self):
        root = Path(__file__).resolve().parents[1]
        for path in ("classify_ci_changes.py", "ci_policy_contract.py", "windows_health.py"):
            ast.parse((root / "scripts" / path).read_text(encoding="utf-8"),
                      filename=path, feature_version=(3, 12))

    def test_routing_corpus(self):
        # Expectations derive from actual workflow consumers, including Docker's dev lock.
        corpus = (
            (("README.md",), {"standards", "secrets", "hygiene"}, {"behavior", "windows"}),
            (
                ("standards/adoption.toml", "standards/conformance.toml"),
                {"standards", "policy-contract"},
                {"windows", "image", "behavior"},
            ),
            (
                ("src/polysia/domain/orders/models.py",),
                {"behavior", "package", "wheel-install"},
                {"windows", "browser", "image"},
            ),
            (("scripts/report_fixture.py",), {"behavior", "lint"}, {"windows", "image"}),
            (
                ("locks/requirements-dev-py314.txt",),
                {"windows", "image", "install-recovery", "audit", "package", "browser"},
                set(),
            ),
            (("scripts/release_manifest.py",), {"image", "install-recovery", "behavior"}, set()),
            (("src/polysia/monitoring/assets/theme.css",), {"browser", "behavior"}, set()),
            (
                ("src/polysia/storage/console_commands.py",),
                {"browser", "windows", "behavior"},
                set(),
            ),
            (("src/polysia/application/services/shadow_reporting.py",), {"browser"}, set()),
            (("tests/conftest.py",), {"browser"}, set()),
            (("deploy/platform_bootstrap.py",), {"image", "install-recovery", "windows"}, set()),
            ((".github/workflows/ci.yml",), {"windows", "image", "browser", "audit"}, set()),
            (("AGENTS.md",), {"windows", "image", "audit"}, set()),
            (("new/unknown.xyz",), {"windows", "image", "behavior"}, set()),
        )
        for paths, required, omitted in corpus:
            with self.subTest(paths=paths):
                policy = project_policy(paths)
                selected = {c["id"] for c in policy["checks"] if c["required"]}
                self.assertTrue(required <= selected, required - selected)
                self.assertFalse(omitted & selected, omitted & selected)
                validate_projection(policy)
        mixed = classify_paths(("README.md", "scripts/release_manifest.py"))
        self.assertTrue(mixed.container)

    def test_complete_historical_p2(self):
        # PR #221, merge a52fcb2; do not manufacture a record-only version of this diff.
        paths = (
            "AGENTS.md",
            "README.md",
            "docs/00-governance/PROJECT_STATUS.md",
            "docs/00-governance/standards-conformance-v1.0.0.md",
            "docs/05-security/supply-chain.md",
            "docs/README.md",
            "scripts/release_manifest.py",
            "scripts/validate_standards.py",
            "standards/adoption.toml",
            "standards/conformance.toml",
            "tests/unit/scripts/test_release_manifest.py",
            "tests/unit/standards/test_validator.py",
        )
        selected = classify_paths(paths)
        self.assertTrue(selected.container and selected.windows and selected.comprehensive)

    def test_ambiguity_and_version_rejection(self):
        self.assertIn("unknown path; full validation",
                      project_policy(["new/unknown.xyz"])["diagnostics"])
        for paths in (
            (),
            ("",),
            ("Src/a.py",),
            ("../README.md",),
            ("a\nb",),
            ("./README.md",),
            ("readme.md",),
            ("a\\b",),
        ):
            with self.subTest(paths=paths):
                self.assertTrue(project_policy(paths)["flags"]["comprehensive"])
        for event in ("schedule", "unexpected"):
            self.assertTrue(project_policy(["README.md"], event=event)["flags"]["windows"])
        policy = project_policy(["README.md"])
        for key, bad in (("version", 999), ("flags", {}), ("checks", []), ("source", {})):
            broken = copy.deepcopy(policy)
            broken[key] = bad
            with self.assertRaises(ValueError):
                validate_projection(broken)
        with self.assertRaises(ValueError):
            project_policy(["README.md"], validation_scope="typo")

    def test_gate_acceptance_and_rejection(self):
        for paths in (("README.md",), (".github/workflows/ci.yml",)):
            policy = project_policy(paths)
            needs = {
                "changes": {
                    "result": "success",
                    "outputs": {k: str(v).lower() for k, v in policy["flags"].items()},
                }
            }
            for job, flag in JOB_FLAGS.items():
                needs[job] = {"result": "success" if policy["flags"][flag] else "skipped"}
            verify_gate(policy, needs, policy)
            for status in (None, "failure", "cancelled", "timed_out", "skipped"):
                broken = copy.deepcopy(needs)
                broken["quality"]["result"] = status
                with self.assertRaises(ValueError):
                    verify_gate(policy, broken)
            for bad in ("false", "TRUE", "", None):
                broken = copy.deepcopy(needs)
                broken["changes"]["outputs"]["quality"] = bad
                with self.assertRaises(ValueError):
                    verify_gate(policy, broken)
            with self.assertRaises(ValueError):
                verify_gate(policy, needs, project_policy(["other.md"]))
            broken = copy.deepcopy(policy)
            broken["checks"][0]["id"] = "unknown"
            with self.assertRaises(ValueError):
                verify_gate(broken, needs)
            self.assertEqual(json.loads(json.dumps(policy)), policy)

    def test_real_diff_rename_deletion_and_dirty_union(self):
        with tempfile.TemporaryDirectory(prefix="polysia-policy-") as directory:
            root = Path(directory).resolve()

            def git(*args):
                return (
                    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)
                    .stdout.decode()
                    .strip()
                )

            git("init", "-q")
            (root / "old.py").write_text("original")
            (root / "remove.py").write_text("removed")
            git("add", ".")
            git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            )
            base = git("rev-parse", "HEAD")
            git("mv", "old.py", "README.md")
            (root / "remove.py").unlink()
            (root / "untracked.py").write_text("new")
            policy = actual_diff(root, base=base, local=True, event="local")
            self.assertEqual(
                set(policy["paths"]), {"old.py", "README.md", "remove.py", "untracked.py"}
            )
            fallback = actual_diff(root, base="missing-ref", local=True, event="local")
            self.assertTrue(fallback["flags"]["comprehensive"])
            self.assertTrue(fallback["diagnostics"])


if __name__ == "__main__":
    unittest.main()
