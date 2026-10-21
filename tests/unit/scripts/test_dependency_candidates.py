from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts import dependency_candidates as candidates
from scripts import dependency_lifecycle as lifecycle
from scripts import dependency_locks as locks
from scripts.dependency_policy import DEV_LOCK, RUNTIME_LOCK


def file(*, python=">=3.14", yanked=False):
    return dict(requires_python=python, yanked=yanked, packagetype="bdist_wheel")


def release(version, *, advisories=(), python=">=3.14"):
    return dict(info=dict(version=version, requires_python=python), urls=[file()],
                vulnerabilities=[{"id": name} for name in advisories])


def inspect(monkeypatch, releases):
    def fetch(name, version=None):
        if version:
            return dict(release(version), info=dict(version=version, requires_dist=[]))
        return dict(releases=releases)

    monkeypatch.setattr(lifecycle, "metadata", fetch)
    return lifecycle.inspect_package("example", "1.0.0", False)


def test_newest_major_does_not_hide_real_eligible_patch(monkeypatch):
    item = inspect(monkeypatch, {"1.0.0": [file()], "1.0.1": [file()], "2.0.0": [file()]})
    result = candidates.assess_candidates(
        item, ["example>=1,<2"], ["parent: example<2"], lambda _, v: release(v),
    )
    assert result["latest_published_stable"] == "2.0.0"
    assert result["highest_eligible_version"] == "1.0.1"
    assert result["candidate_versions"] == ["1.0.1"]
    assert "version_policy" in result["latest_eligibility_exclusions"]
    assert result["eligibility_provisional"] is True
    assert result["eligibility_observed_at"] == result["observed_at"]


def test_yanked_python_and_active_parent_bounds_leave_only_allowed_patch(monkeypatch):
    item = inspect(monkeypatch, {
        "1.0.0": [file()], "1.0.1": [file()], "1.0.2": [file()],
        "1.0.3": [file(yanked=True)], "1.0.4": [file(python=">=3.15")],
        "1.0.5rc1": [file()], "1!1.0.6": [file()],
    })
    parents = lifecycle.parent_edges([
        dict(package="parent", parent_requirements=[
            "example<1.0.2; sys_platform == 'win32'",
            "example<1.0.1; sys_platform == 'freebsd'",
        ]),
    ], [])
    result = candidates.assess_candidates(item, [], parents["example"], lambda _, v: release(v))
    assert result["candidate_versions"] == ["1.0.1"]
    reasons = {row["version"]: row["exclusions"] for row in result["release_assessments"]}
    assert "supported_python" in reasons["1.0.4"]
    assert "yanked_or_no_files" in reasons["1.0.3"]
    assert any(reason.startswith("constraint:") for reason in reasons["1.0.2"])


@pytest.mark.parametrize("declaration", ["example==1.0.0", "example<1.0.1"])
def test_existing_declaration_is_not_silently_widened(monkeypatch, declaration):
    item = inspect(monkeypatch, {"1.0.0": [file()], "1.0.1": [file()]})
    result = candidates.assess_candidates(item, [declaration], [], lambda *_: pytest.fail("held"))
    assert result["highest_eligible_version"] is None
    assert result["eligibility_outcome"] == "NO_ELIGIBLE_UPDATE"


@pytest.mark.parametrize("scope,name", [("runtime", "example"), ("development/build", "pip")])
def test_sensitive_and_runtime_candidates_are_separate_review_work(scope, name):
    item = dict(package=name, resolved="1.0.0", scope=scope, observed_at="2026-10-21T00:00:00Z",
                latest_published_stable="1.0.1", supports_python314=True,
                release_catalog=candidates.release_catalog({"1.0.1": [file()]}, "1.0.0"))
    result = candidates.assess_candidates(item, [], [], lambda *_: pytest.fail("held"))
    assert result["eligibility_outcome"] == "REVIEW_REQUIRED"
    assert result["highest_eligible_version"] is None


def test_candidate_advisory_and_metadata_identity_are_checked(monkeypatch):
    item = inspect(monkeypatch, {"1.0.1": [file()], "1.0.2": [file()], "2.0.0": [file()]})
    result = candidates.assess_candidates(item, [], [], lambda _, v: release(
        v, advisories=["GHSA-fixture"] if v == "1.0.2" else [],
    ))
    assert result["highest_eligible_version"] == "1.0.1"
    assert "candidate_advisory" in result["release_assessments"][0]["exclusions"]
    result = candidates.assess_candidates(item, [], [], lambda *_: release("9.0.0"))
    assert result["eligibility_outcome"] == "UNKNOWN"
    assert result["highest_eligible_version"] is None


def test_metadata_attempt_bound_is_unknown_not_false_absence(monkeypatch):
    item = inspect(monkeypatch, {f"1.0.{n}": [file()] for n in range(1, 5)})
    calls = []

    def fetch(_, version):
        calls.append(version)
        return release(version, advisories=["GHSA-fixture"])

    result = candidates.assess_candidates(item, [], [], fetch)
    assert len(calls) == candidates.MAX_METADATA_ATTEMPTS
    assert result["eligibility_outcome"] == "UNKNOWN"
    assert "metadata_attempt_bound" in result["release_assessments"][-1]["exclusions"]


@pytest.mark.parametrize("data", [None, [], {"info": None}, {"info": {"version": "1.0.1"},
                                                          "urls": [None]}])
def test_malformed_candidate_metadata_remains_unknown(monkeypatch, data):
    item = inspect(monkeypatch, {"1.0.1": [file()]})
    result = candidates.assess_candidates(item, [], [], lambda *_: data)
    assert result["eligibility_outcome"] == "UNKNOWN"
    assert result["highest_eligible_version"] is None


def test_excluded_newer_majors_do_not_consume_patch_catalog_bound():
    versions = {f"{n}.0.0": [file()] for n in range(2, 150)}
    catalog = candidates.release_catalog(dict(versions, **{"1.0.1": [file()]}), "1.0.0")
    assert catalog["releases"][0]["version"] == "1.0.1"
    assert not catalog["truncated"]


@pytest.fixture
def slice_root(tmp_path, monkeypatch):
    root, work = tmp_path / "root", tmp_path / "work"
    manifest = '''[build-system]
requires = ["hatchling==1.32.4"]
build-backend = "hatchling.build"
[project]
name = "polysia"
dependencies = ["rich>=15,<16"]
[project.optional-dependencies]
dev = ["example>=1,<2", "hatchling==1.32.4", "pip-tools==7.6.2"]
'''
    for path in (root, work):
        (path / "locks").mkdir(parents=True)
        (path / "pyproject.toml").write_text(manifest)
        (path / RUNTIME_LOCK).write_text("rich==15.0.0\n")
        (path / DEV_LOCK).write_text(
            "rich==15.0.0\nexample==1.0.0\nhatchling==1.32.4\npip-tools==7.6.2\n"
        )
    monkeypatch.setattr(lifecycle, "ROOT", root)
    return root, work


def report():
    return dict(outcome="complete", last_complete_scan="2026-10-21T00:00:00Z", packages=[
        dict(package="example", eligibility_outcome="PROVISIONAL_CANDIDATE",
             candidate_versions=["1.0.1"]),
        dict(package="rich", eligibility_outcome="REVIEW_REQUIRED", candidate_versions=[]),
    ])


def test_scheduled_dev_patch_coexists_with_deferred_runtime_update(slice_root, monkeypatch):
    root, work = slice_root
    before = (root / DEV_LOCK).read_bytes()

    def resolve(path, *, upgrade, upgrade_packages, extra_constraints):
        assert upgrade is False and upgrade_packages == ("example",)
        constraints = extra_constraints[0].read_text()
        assert all(pin in constraints for pin in (
            "rich==15.0.0", "hatchling==1.32.4", "pip-tools==7.6.2", "example==1.0.1",
        ))
        dev = path / DEV_LOCK
        dev.write_text(dev.read_text().replace("example==1.0.0", "example==1.0.1"))

    monkeypatch.setattr(locks, "generate_pip_locks", resolve)
    result = lifecycle.scheduled_slice(work, report())
    assert result["outcome"] == "proposal"
    assert result["scope"] == "development-only"
    assert (work / RUNTIME_LOCK).read_bytes() == (root / RUNTIME_LOCK).read_bytes()
    assert (root / DEV_LOCK).read_bytes() == before


@pytest.mark.parametrize("drift", ["rich", "hatchling", "new-transitive"])
def test_complete_resolved_slice_holds_runtime_sensitive_and_unknown_drift(
    slice_root, monkeypatch, drift,
):
    _, work = slice_root

    def resolve(path, **_):
        dev = path / DEV_LOCK
        text = dev.read_text().replace("example==1.0.0", "example==1.0.1")
        if drift == "hatchling":
            text = text.replace("hatchling==1.32.4", "hatchling==1.32.5")
        elif drift == "rich":
            (path / RUNTIME_LOCK).write_text("rich==15.0.1\n")
            text = text.replace("rich==15.0.0", "rich==15.0.1")
        else:
            text += "new-transitive==1.0.0\n"
        dev.write_text(text)

    monkeypatch.setattr(locks, "generate_pip_locks", resolve)
    result = lifecycle.scheduled_slice(work, report())
    assert result["outcome"] == "HELD"
    assert result["attempts"][0]["reason"]


def test_no_eligible_does_not_invoke_global_upgrade(slice_root, monkeypatch):
    _, work = slice_root
    monkeypatch.setattr(locks, "generate_pip_locks", lambda *_a, **_k: pytest.fail("no candidate"))
    result = lifecycle.scheduled_slice(work, dict(report(), packages=[]))
    assert result["outcome"] == "NO_ELIGIBLE_UPDATE"
    assert result["attempts"] == []


def test_conflicting_target_does_not_consume_peer_attempts(slice_root, monkeypatch):
    root, work = slice_root
    calls = []

    def resolve(path, *, upgrade_packages, **_):
        calls.append(upgrade_packages[0])
        if upgrade_packages == ("blocked",):
            raise RuntimeError("conflicting fixed pins")
        dev = path / DEV_LOCK
        assert dev.read_bytes() == (root / DEV_LOCK).read_bytes()
        dev.write_text(dev.read_text().replace("example==1.0.0", "example==1.0.1"))

    monkeypatch.setattr(locks, "generate_pip_locks", resolve)
    observation = report()
    observation["packages"].insert(0, dict(
        package="blocked", eligibility_outcome="PROVISIONAL_CANDIDATE",
        candidate_versions=["1.0.3", "1.0.2", "1.0.1"],
    ))
    result = lifecycle.scheduled_slice(work, observation)
    assert result["outcome"] == "proposal"
    assert calls == ["blocked", "example"]
    monkeypatch.setattr(locks, "generate_pip_locks", lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("conflict")
    ))
    result = lifecycle.scheduled_slice(work, observation)
    assert result["outcome"] == "HELD"
    assert len(result["attempts"]) == lifecycle.MAX_RESOLVER_ATTEMPTS
    assert result["unattempted"] == 1


def test_canonical_targeted_resolver_freezes_runtime_and_bootstrap_offline(tmp_path, monkeypatch):
    """Exercise real pip-compile against inert test wheels; never access a registry."""
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    for name, versions in {
        "runtime_fixture": ["1.0.0", "2.0.0"],
        "dev_fixture": ["1.0.0", "1.0.1", "2.0.0"],
        "pip_tools": ["7.6.2", "7.7.0"],
    }.items():
        for version in versions:
            stem = f"{name}-{version}"
            with zipfile.ZipFile(wheelhouse / f"{stem}-py3-none-any.whl", "w") as wheel:
                wheel.writestr(f"{stem}.dist-info/METADATA",
                               f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
                wheel.writestr(f"{stem}.dist-info/WHEEL",
                               "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
                wheel.writestr(f"{stem}.dist-info/RECORD", "")
    # Static PEP 621 metadata avoids executing a build backend during this test.
    (tmp_path / "pyproject.toml").write_text('''[project]
name = "offline-resolver-fixture"
version = "1.0.0"
dependencies = ["runtime-fixture>=1,<3"]
[project.optional-dependencies]
dev = ["dev-fixture>=1,<3", "pip-tools>=7,<8"]
''')
    (tmp_path / "locks").mkdir()
    (tmp_path / RUNTIME_LOCK).write_text("runtime-fixture==1.0.0\n")
    (tmp_path / DEV_LOCK).write_text(
        "runtime-fixture==1.0.0\ndev-fixture==1.0.0\npip-tools==7.6.2\n"
    )
    constraints = tmp_path / "fixed.txt"
    constraints.write_text("runtime-fixture==1.0.0\npip-tools==7.6.2\ndev-fixture==1.0.1\n")
    run = locks._run

    def offline(command, **kwargs):
        return run([*command, "--no-index", "--find-links", str(wheelhouse)], **kwargs)

    monkeypatch.setattr(locks, "_run", offline)
    locks.generate_pip_locks(tmp_path, upgrade=False, upgrade_packages=("dev-fixture",),
                             extra_constraints=(constraints,))
    assert locks.parse_lock_pins((tmp_path / RUNTIME_LOCK).read_text()) == {
        "runtime-fixture": "1.0.0",
    }
    assert locks.parse_lock_pins((tmp_path / DEV_LOCK).read_text()) == {
        "runtime-fixture": "1.0.0", "dev-fixture": "1.0.1", "pip-tools": "7.6.2",
    }


def test_generation_workflow_only_uploads_a_real_proposal():
    text = Path(".github/workflows/dependency-automation.yml").read_text()
    assert "r['outcome']=='proposal'" in text
    assert 'echo "prepared=true"' not in text


def test_generation_no_candidate_is_successful_without_proposal(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lifecycle, "generate", lambda *_: dict(outcome="NO_ELIGIBLE_UPDATE"))
    monkeypatch.setattr("sys.argv", ["generate", "generate", "--output", str(tmp_path / "out"),
                                    "--result", str(tmp_path / "result.json")])
    assert lifecycle.main() == 0
    assert json.loads((tmp_path / "result.json").read_text())["outcome"] == "NO_ELIGIBLE_UPDATE"
    assert not (tmp_path / "out" / "provenance.json").exists()
    assert "NO_ELIGIBLE_UPDATE" in capsys.readouterr().out
