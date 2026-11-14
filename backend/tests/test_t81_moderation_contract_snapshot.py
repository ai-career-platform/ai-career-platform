"""T81 검수 API 계약 스냅샷(docs/admin/t81_moderation_api.snapshot.json) = 실제 라우터(ADMIN_MODERATION_API=true)의 OpenAPI.

프런트 계약 시험(frontend/src/api/moderationHttp.contract.test.ts)은 백엔드 소스가 없는 이미지 빌드에서도 돌도록
이 스냅샷을 읽는다. 라우터·스키마를 바꾸면 이 시험이 실패한다 → 스냅샷을 다시 만든다:
    T81_UPDATE_SNAPSHOT=1 python -m pytest tests/test_t81_moderation_contract_snapshot.py
"""
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.main import create_app
from tests.conftest import TEST_SECRET

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs/admin/t81_moderation_api.snapshot.json"
PREFIX = "/api/v1/admin/moderation-cases"


def _resolve(spec, schema):
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def _enums(spec, schema) -> list | None:
    schema = _resolve(spec, schema)
    for option in schema.get("anyOf", []):
        found = _enums(spec, option)
        if found:
            return found
    return schema.get("enum")


def _model(spec, schema) -> dict:
    schema = _resolve(spec, schema)
    out = {}
    for name, prop in schema.get("properties", {}).items():
        enum = _enums(spec, prop)
        out[name] = {"required": name in schema.get("required", []), **({"enum": enum} if enum else {})}
    return out


def build_snapshot() -> dict:
    get_settings.cache_clear()
    try:
        spec = create_app().openapi()
    finally:
        get_settings.cache_clear()
    paths = {}
    for path, ops in sorted(spec["paths"].items()):
        if not path.startswith(PREFIX):
            continue
        for method, op in sorted(ops.items()):
            entry = {"operation_id": op["operationId"],
                     "query": {p["name"]: {k: v for k, v in {"enum": _enums(spec, p["schema"])}.items() if v}
                               for p in op.get("parameters", []) if p["in"] == "query"}}
            body = op.get("requestBody")
            if body:
                entry["body"] = _model(spec, body["content"]["application/json"]["schema"])
            response = op["responses"]["200"]["content"]["application/json"]["schema"]
            entry["response"] = _model(spec, response)
            paths[f"{method.upper()} {path[len('/api'):]}"] = entry
    event = _model(spec, spec["components"]["schemas"]["CaseEventOut"])
    summary = _model(spec, spec["components"]["schemas"]["CaseSummaryOut"])
    return {"_note": "generated from backend/app/routers/admin_moderation.py (T81). Do not edit by hand.",
            "paths": paths, "schemas": {"CaseSummaryOut": summary, "CaseEventOut": event}}


def test_snapshot_matches_the_router(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("ADMIN_MODERATION_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    current = build_snapshot()
    if os.environ.get("T81_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == current, "router changed: regenerate the snapshot"
    assert len(current["paths"]) == 5
