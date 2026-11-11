"""T118 공급망 — SBOM 재현성, 잠금 정책, 취약점 게이트(예외 승인·만료) 시험. 네트워크를 쓰지 않는다."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("t118_sbom", ROOT / "scripts" / "supply_chain" / "t118_sbom.py")
sb = importlib.util.module_from_spec(_spec)
sys.modules["t118_sbom"] = sb
_spec.loader.exec_module(sb)

TODAY = date(2026, 11, 11)
ROW = {"package": "starlette", "version": "0.46.2", "id": "PYSEC-TEST-1", "severity": "HIGH"}


# ------------------------------------------------------------------ SBOM
def test_sbom_is_reproducible_and_sorted():
    first, second = sb.build_sbom(), sb.build_sbom()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    purls = [c["purl"] for c in first["components"]]
    assert purls == sorted(purls) and len(purls) == len(set(purls))
    assert first["bomFormat"] == "CycloneDX" and first["specVersion"] == "1.5"
    assert "timestamp" not in first["metadata"]


def test_sbom_covers_every_pinned_python_dependency_npm_lock_entry_and_base_image():
    purls = {c["purl"] for c in sb.build_sbom()["components"]}
    for req in sb.python_requirements():
        assert f"pkg:pypi/{req['name']}@{req['version']}" in purls, req
    npm = {(p["name"], p["version"]) for p in sb.npm_packages() if not p["link"]}
    npm_components = [c for c in sb.build_sbom()["components"] if c["purl"].startswith("pkg:npm/")]
    assert npm and {(c["name"], c["version"]) for c in npm_components} == npm
    assert all(c.get("hashes") for c in npm_components), "npm 구성요소는 lockfile integrity 해시를 가진다"
    images = [c for c in sb.build_sbom()["components"] if c["type"] == "container"]
    assert {c["name"] for c in images} == {"python", "nginx"}
    assert all(p["value"] == "UNPINNED" for c in images for p in c["properties"] if p["name"] == "t118:digest")


def test_committed_sbom_matches_current_direct_dependencies():
    """의존성을 바꾸고 SBOM 을 다시 만들지 않으면 실패(드리프트 방지)."""
    committed = json.loads((ROOT / "docs" / "security" / "sbom" / "ai-career-platform.cdx.json").read_text(encoding="utf-8"))
    committed_purls = {c["purl"] for c in committed["components"]}
    fresh_direct = {c["purl"] for c in sb.build_sbom()["components"]}
    assert fresh_direct <= committed_purls, sorted(fresh_direct - committed_purls)[:10]


def test_resolved_scan_adds_transitive_components_marked_as_scan_time():
    resolved = {"dependencies": [{"name": "Typing_Extensions", "version": "4.12.2"}]}
    comps = {c["purl"]: c for c in sb.build_sbom(resolved)["components"]}
    comp = comps["pkg:pypi/typing-extensions@4.12.2"]
    assert {"name": "t118:scope", "value": "transitive-resolved-at-scan"} in comp["properties"]


# ------------------------------------------------------------------ 잠금 정책
def test_repository_policy_has_no_failures_and_reports_known_warnings():
    findings = sb.policy_findings()
    assert [f for f in findings if f["level"] == "FAIL"] == []
    rules = {f["rule"] for f in findings}
    assert "python transitive dependencies not locked (no hashes)" in rules
    assert "base image tag not pinned by digest" in rules


def _fake_repo(tmp_path, req="fastapi==0.115.12\n", lock=None, docker="FROM python:3.12.10-slim\n"):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text(req, encoding="utf-8")
    for rel in sb.NPM_LOCKS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(lock or {"lockfileVersion": 3, "packages": {
            "": {"name": "x"}, "node_modules/a": {"version": "1.0.0", "integrity": "sha512-AAAA"}}}), encoding="utf-8")
    (tmp_path / "poc/staging/backend").mkdir(parents=True)
    (tmp_path / "poc/staging/backend/Dockerfile").write_text(docker, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("kwargs", "rule"), [
    ({"req": "fastapi>=0.100\n"}, "python direct dependency not pinned with =="),
    ({"req": "fastapi\n"}, "python direct dependency not pinned with =="),
    ({"lock": {"lockfileVersion": 1, "packages": {"node_modules/a": {"version": "1", "integrity": "sha1-x"}}}},
     "npm lockfileVersion < 2"),
    ({"lock": {"lockfileVersion": 3, "packages": {"node_modules/a": {"version": "1"}}}},
     "npm package without integrity hash"),
    ({"docker": "FROM python:latest\n"}, "base image without fixed tag"),
    ({"docker": "FROM python\n"}, "base image without fixed tag"),
])
def test_policy_failures_on_synthetic_repos(tmp_path, kwargs, rule):
    findings = sb.policy_findings(_fake_repo(tmp_path, **kwargs))
    assert {"FAIL"} & {f["level"] for f in findings if f["rule"] == rule}


def test_digest_pinned_image_passes(tmp_path):
    repo = _fake_repo(tmp_path, docker="FROM python:3.12.10-slim@sha256:" + "a" * 64 + "\n")
    assert not [f for f in sb.policy_findings(repo) if "base image" in f["rule"]]


# ------------------------------------------------------------------ 취약점 게이트
def exc(**over):
    entry = {"package": "starlette", "id": "PYSEC-TEST-1", "approved_by": "PM", "reason": "not reachable",
             "expires": "2026-12-11"}
    entry.update(over)
    return entry


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL", None])
def test_high_critical_and_unknown_block_without_exception(severity):
    assert sb.gate([{**ROW, "severity": severity}], [], TODAY)["verdict"] == "FAIL"


@pytest.mark.parametrize("severity", ["LOW", "MODERATE", "MEDIUM"])
def test_low_and_moderate_are_reported_not_blocking(severity):
    result = sb.gate([{**ROW, "severity": severity}], [], TODAY)
    assert result["verdict"] == "PASS" and len(result["reported"]) == 1


def test_valid_exception_lets_the_gate_pass():
    result = sb.gate([ROW], [exc()], TODAY)
    assert result["verdict"] == "PASS" and len(result["excepted"]) == 1


@pytest.mark.parametrize("bad", [
    {"approved_by": ""}, {"approved_by": "  "}, {"reason": ""}, {"expires": "2026-11-10"}, {"expires": None},
    {"id": "PYSEC-OTHER"}, {"package": "fastapi"},
])
def test_invalid_or_expired_or_mismatched_exception_does_not_count(bad):
    assert sb.gate([ROW], [exc(**bad)], TODAY)["verdict"] == "FAIL"


def test_exception_expiring_today_is_still_valid():
    assert sb.gate([ROW], [exc(expires="2026-11-11")], TODAY)["verdict"] == "PASS"


def test_current_repository_state_is_no_go_until_exceptions_are_approved():
    """수정 후 남은 starlette HIGH 3건은 승인 대기 예외뿐 → 게이트 FAIL(사실 그대로)."""
    rows = json.loads((ROOT / "docs" / "security" / "t118_scan_after.json").read_text(encoding="utf-8"))["rows"]
    exceptions = sb.load_exceptions()
    assert exceptions and all(not str(e["approved_by"]).strip() for e in exceptions)
    result = sb.gate(rows, exceptions, TODAY)
    assert result["verdict"] == "FAIL" and {r["package"] for r in result["blocking"]} == {"starlette"}
    assert len(result["blocking"]) == 3


def test_remediated_packages_are_pinned_at_fixed_versions():
    reqs = {r["name"]: r["version"] for r in sb.python_requirements() if r["file"] == "backend/requirements.txt"}
    assert reqs["pyjwt"] == "2.15.0" and reqs["python-multipart"] == "0.0.31"
    before = json.loads((ROOT / "docs" / "security" / "t118_scan_before.json").read_text(encoding="utf-8"))["rows"]
    after = json.loads((ROOT / "docs" / "security" / "t118_scan_after.json").read_text(encoding="utf-8"))["rows"]
    assert {r["package"] for r in before} >= {"pyjwt", "python-multipart", "starlette"}
    assert {r["package"] for r in after} == {"starlette"}
