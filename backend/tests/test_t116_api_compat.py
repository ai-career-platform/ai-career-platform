"""T116 API 하위호환 검사 — 합성 fixture 로 정상 변경 PASS / 파괴적 변경 FAIL, 실제 계약·오류 코드 기준선."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.core.errors import ERROR_CATALOG

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_compat", ROOT / "docs" / "api" / "check_compat.py")
cc = importlib.util.module_from_spec(_spec)
sys.modules["check_compat"] = cc  # dataclass 가 모듈을 찾을 수 있게
_spec.loader.exec_module(cc)

BASE = {
    "openapi": "3.1.0",
    "paths": {
        "/items": {
            "get": {
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string", "maxLength": 100}},
                    {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["new", "old"]}},
                ],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ItemPage"}}}},
                    "422": {"$ref": "#/components/responses/Invalid"},
                },
            },
            "post": {
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/ItemCreate"}}}},
                "responses": {"201": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Item"}}}}},
            },
        },
        "/items/{item_id}": {
            "parameters": [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "delete": {"responses": {"204": {"description": "deleted"}}},
        },
    },
    "components": {
        "responses": {"Invalid": {"description": "bad", "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Error"}}}}},
        "schemas": {
            "Error": {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}},
            "Item": {
                "type": "object", "required": ["id", "name", "status"],
                "properties": {
                    "id": {"type": "string"}, "name": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "closed"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "owner": {"$ref": "#/components/schemas/Owner"},
                },
            },
            "Owner": {"type": "object", "properties": {"display_name": {"type": "string"}}},
            "ItemPage": {"type": "object", "required": ["items"], "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}},
                "next_cursor": {"type": ["string", "null"]}}},
            "ItemCreate": {"type": "object", "additionalProperties": False, "required": ["name"],
                           "properties": {"name": {"type": "string", "maxLength": 50},
                                          "memo": {"type": "string"}}},
        },
    },
}


def mutate(fn):
    doc = copy.deepcopy(BASE)
    fn(doc)
    return doc


def breaking(new_doc, exceptions=None):
    return [(c.location, c.rule) for c in cc.compare(BASE, new_doc, exceptions) if c.level == "BREAKING"]


S = lambda d: d["components"]["schemas"]  # noqa: E731
GET = lambda d: d["paths"]["/items"]["get"]  # noqa: E731
POST = lambda d: d["paths"]["/items"]["post"]  # noqa: E731


# ------------------------------------------------------------------ 정상(비파괴) 변경은 통과
@pytest.mark.parametrize("change", [
    lambda d: None,
    lambda d: S(d)["Item"]["properties"].update(created_at={"type": "string"}),           # 응답 필드 추가
    lambda d: GET(d)["parameters"].append({"name": "page_size", "in": "query",
                                           "schema": {"type": "integer"}}),                # 선택 파라미터 추가
    lambda d: S(d)["ItemCreate"]["properties"].update(color={"type": "string"}),          # 선택 요청 필드 추가
    lambda d: S(d)["ItemCreate"]["properties"]["name"].update(maxLength=80),              # 요청 제한 완화
    lambda d: GET(d)["parameters"][1]["schema"]["enum"].append("popular"),                # 요청 enum 확장
    lambda d: d["paths"].update({"/tags": {"get": {"responses": {"200": {"description": "ok"}}}}}),  # 새 경로
    lambda d: GET(d).update(deprecated=True),                                             # deprecated 표시만
    lambda d: S(d)["Item"]["required"].append("tags"),                                    # 응답 필드 필수화
])
def test_compatible_changes_pass(change):
    assert breaking(mutate(change)) == []


# ------------------------------------------------------------------ 파괴적 변경은 실패
@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: d["paths"].pop("/items/{item_id}"), ("DELETE /items/{item_id}", "operation removed")),
    (lambda d: d["paths"]["/items"].pop("post"), ("POST /items", "operation removed")),
    (lambda d: GET(d)["parameters"].append({"name": "region", "in": "query", "required": True,
                                            "schema": {"type": "string"}}),
     ("GET /items param query:region", "new required parameter")),
    (lambda d: GET(d)["parameters"][0].update(required=True),
     ("GET /items param query:q", "parameter became required")),
    (lambda d: GET(d)["parameters"][0]["schema"].update(type="integer"),
     ("GET /items param query:q", "request type narrowed ['string'] -> ['integer']")),
    (lambda d: GET(d)["parameters"][1]["schema"]["enum"].remove("old"),
     ("GET /items param query:sort", "request enum values removed ['old']")),
    (lambda d: GET(d)["parameters"][0]["schema"].update(maxLength=20),
     ("GET /items param query:q", "request constraint tightened maxLength 100 -> 20")),
    (lambda d: S(d)["ItemCreate"]["required"].append("memo"),
     ("POST /items body.memo", "new required request field")),
    (lambda d: S(d)["ItemCreate"]["properties"].pop("memo"),
     ("POST /items body.memo", "request field removed (would be rejected)")),
    (lambda d: S(d)["Item"]["properties"].pop("name"),
     ("POST /items response 201.name", "response field removed")),
    (lambda d: S(d)["Item"]["required"].remove("status"),
     ("POST /items response 201.status", "response field no longer required")),
    (lambda d: S(d)["Item"]["properties"]["id"].update(type="integer"),
     ("POST /items response 201.id", "response type widened ['string'] -> ['integer']")),
    (lambda d: S(d)["Item"]["properties"]["name"].update(type=["string", "null"]),
     ("POST /items response 201.name", "response type widened ['string'] -> ['null', 'string']")),
    (lambda d: S(d)["Owner"]["properties"].pop("display_name"),
     ("POST /items response 201.owner.display_name", "response field removed")),
    (lambda d: S(d)["Item"]["properties"].pop("tags"),
     ("GET /items response 200.items[].tags", "response field removed")),
    (lambda d: POST(d)["responses"].update({"200": POST(d)["responses"].pop("201")}),
     ("POST /items response 201", "response status removed")),
])
def test_breaking_changes_fail(change, expected):
    assert expected in breaking(mutate(change))


def test_path_level_parameter_removal_is_breaking():
    doc = mutate(lambda d: d["paths"]["/items/{item_id}"].pop("parameters"))
    assert ("DELETE /items/{item_id} param path:item_id", "parameter removed") in breaking(doc)


def test_optional_query_removal_and_error_doc_removal_only_warn():
    doc = mutate(lambda d: (GET(d)["parameters"].pop(0), GET(d)["responses"].pop("422")))
    changes = cc.compare(BASE, doc)
    assert {c.level for c in changes} == {"WARN"}
    assert {c.rule for c in changes} == {"parameter removed", "response status removed"}


def test_response_enum_addition_warns_but_passes():
    doc = mutate(lambda d: S(d)["Item"]["properties"]["status"]["enum"].append("archived"))
    changes = cc.compare(BASE, doc)
    assert breaking(doc) == [] and any(c.level == "WARN" and "enum values added" in c.rule for c in changes)


# ------------------------------------------------------------------ 예외(승인) 규칙
def test_exception_requires_exact_match_and_approver():
    doc = mutate(lambda d: d["paths"].pop("/items/{item_id}"))
    entry = {"location": "DELETE /items/{item_id}", "rule": "operation removed"}
    assert breaking(doc, [{**entry, "approved_by": ""}])          # 승인자 없는 예외는 무효
    assert breaking(doc, [{**entry, "approved_by": "   "}])
    assert breaking(doc, [{**entry, "approved_by": "PM"}]) == []
    allowed = [c for c in cc.compare(BASE, doc, [{**entry, "approved_by": "PM"}]) if c.level == "ALLOWED"]
    assert len(allowed) == 1
    assert breaking(doc, [{"location": "DELETE /items", "rule": "operation removed", "approved_by": "PM"}])


def test_exceptions_without_approver_are_ignored(tmp_path):
    path = tmp_path / "ex.yaml"
    path.write_text(yaml.safe_dump({"exceptions": [
        {"location": "A", "rule": "r", "approved_by": ""}, {"location": "B", "rule": "r", "approved_by": "PM"}]}),
        encoding="utf-8")
    assert [e["location"] for e in cc.load_exceptions(path)] == ["B"]


def test_repository_exception_list_is_empty_by_default():
    assert cc.load_exceptions() == []


def test_ref_cycles_do_not_loop_forever():
    doc = copy.deepcopy(BASE)
    S(doc)["Owner"]["properties"]["boss"] = {"$ref": "#/components/schemas/Owner"}
    new = copy.deepcopy(doc)
    assert cc.compare(doc, new) == []


# ------------------------------------------------------------------ 실제 계약
def _spec_at(ref: str) -> dict | None:
    try:
        out = subprocess.run(["git", "show", f"{ref}:docs/api/openapi.yaml"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return yaml.safe_load(out)


def test_current_contract_is_compatible_with_itself():
    spec = yaml.safe_load((ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))
    assert cc.compare(spec, copy.deepcopy(spec)) == []


def test_history_replay_detects_the_csrf_header_change():
    """실제 이력(e1e8591, #166)의 X-CSRF-TOKEN 필수 헤더 추가를 파괴적 변경으로 잡는다(당시 예외 기록 없음)."""
    old, new = _spec_at("e1e8591~1"), _spec_at("e1e8591")
    if old is None or new is None:
        pytest.skip("git 이력을 읽을 수 없음(얕은 checkout)")
    found = breaking_between(old, new)
    assert ("POST /auth/login param header:X-CSRF-TOKEN", "new required parameter") in found


def breaking_between(old, new):
    return [(c.location, c.rule) for c in cc.compare(old, new) if c.level == "BREAKING"]


def test_proposed_contracts_are_not_merged_into_the_approved_spec():
    """PROPOSED 계약(docs/**/t*_openapi_proposal.yaml)은 확정 계약 비교 대상이 아니고, 확정 계약에 섞이지 않는다."""
    assert list(ROOT.glob("docs/**/t*_openapi_proposal.yaml")), "PROPOSED 계약 파일이 있어야 의미 있는 시험"
    spec = yaml.safe_load((ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict):
                assert str(op.get("x-status", "")).upper() != "PROPOSED", (method, path)
    assert cc.SPEC_REL == "docs/api/openapi.yaml"


# ------------------------------------------------------------------ 오류 코드 의미
def test_error_codes_match_the_snapshot():
    """코드 삭제·HTTP 상태 변경은 클라이언트 분기를 깨므로 실패. 추가는 스냅샷을 함께 갱신해야 통과(리뷰 노출)."""
    snapshot = json.loads((ROOT / "docs" / "api" / "error_codes.snapshot.json").read_text(encoding="utf-8"))["codes"]
    current = {str(code): spec.status for code, spec in ERROR_CATALOG.items()}
    removed = sorted(set(snapshot) - set(current))
    changed = sorted(c for c in set(snapshot) & set(current) if snapshot[c] != current[c])
    added = sorted(set(current) - set(snapshot))
    assert removed == [], f"오류 코드 삭제(파괴적): {removed}"
    assert changed == [], f"오류 코드 HTTP 상태 변경(파괴적): {changed}"
    assert added == [], f"새 오류 코드 — docs/api/error_codes.snapshot.json 갱신 필요: {added}"


def test_cli_exit_codes(tmp_path, capsys):
    old, new = tmp_path / "old.yaml", tmp_path / "new.yaml"
    old.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    new.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    assert cc.main(["--base-file", str(old), "--head-file", str(new)]) == 0
    new.write_text(yaml.safe_dump(mutate(lambda d: d["paths"].pop("/items/{item_id}"))), encoding="utf-8")
    assert cc.main(["--base-file", str(old), "--head-file", str(new)]) == 1
    assert "BREAKING DELETE /items/{item_id}: operation removed" in capsys.readouterr().out
