#!/usr/bin/env python3
"""T06 OpenAPI contract checker.

Checks docs/api/openapi.yaml for:
  1. OpenAPI 3.1 syntax and $ref resolution (openapi-spec-validator)
  2. every example matches its schema (JSON Schema 2020-12)
  3. contract rules: errors use application/json + ErrorResponse, 401 on protected operations, no user_id under /me
  4. traceability 100%: requirement <-> operation, screen <-> operation, table <-> operation,
     with every exemption listed below and explained

Requires: pip install openapi-spec-validator jsonschema pyyaml
Usage:   python3 docs/api/check_openapi.py [--requirements-root DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import jsonschema
import yaml
from openapi_spec_validator import validate as validate_spec

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "api" / "openapi.yaml"
DICTIONARY = ROOT / "database" / "DATA_DICTIONARY.md"
METHODS = ("get", "post", "put", "patch", "delete")
ERROR_SCHEMA = {"$ref": "#/components/schemas/ErrorResponse"}

# Requirements with no API in this contract, and why. Keep this list short and reviewed.
REQUIREMENT_EXEMPT = {
    "FR-CMN-004": "공통 상태 화면: 별도 API 없음. 모든 operation의 공통 오류 응답(ErrorResponse)으로 충족",
}
SCREEN_EXEMPT: dict[str, str] = {}
TABLE_EXEMPT = {
    "job_posting_external_refs": "외부 공고 수집 배치 전용 (T62). 사용자 API 없음",
    "ingestion_runs": "외부 공고 수집 배치 전용 (T64). 사용자 API 없음",
}


def load_ids(req_root: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (functional requirement IDs, all requirement IDs, screen IDs)."""
    all_ids: set[str] = set()
    for md in sorted((req_root).glob("*/*.md")):
        all_ids |= set(re.findall(r"^### ((?:N?FR)-[A-Z]+-\d{3}) ", md.read_text(encoding="utf-8"), re.M))
    trace = (req_root / "traceability" / "TRACEABILITY.md").read_text(encoding="utf-8")
    screens_section = trace.split("## 2. 화면 목록", 1)[1].split("\n## ", 1)[0]
    screens = set(re.findall(r"^\| (UI-[A-Z0-9]+) \|", screens_section, re.M))
    return {i for i in all_ids if i.startswith("FR-")}, all_ids, screens


def load_tables() -> set[str]:
    return set(re.findall(r"^### [A-F]\d{2} `([a-z_]+)`", DICTIONARY.read_text(encoding="utf-8"), re.M))


def resolve(node, spec, seen=()):
    """Inline local $refs so jsonschema can validate examples without a registry."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                raise ValueError(f"recursive $ref {ref}")
            target = spec
            for part in ref.lstrip("#/").split("/"):
                target = target[part]
            merged = {k: v for k, v in node.items() if k != "$ref"}
            return {**resolve(target, spec, seen + (ref,)), **resolve(merged, spec, seen)}
        return {k: resolve(v, spec, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v, spec, seen) for v in node]
    return node


def operations(spec):
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method in item:
                yield path, method, item[method], item.get("parameters", [])


def check(spec: dict, req_root: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    fr_ids, all_req_ids, screen_ids = load_ids(req_root)
    tables = load_tables()
    used_req, used_screens, used_tables = set(), set(), set()
    op_ids: list[str] = []
    examples = 0

    for path, method, op, path_params in operations(spec):
        where = f"{method.upper()} {path}"
        op_id = op.get("operationId")
        if not op_id:
            errors.append(f"{where}: missing operationId")
        op_ids.append(op_id)
        for key in ("x-requirements", "x-screens", "x-tables"):
            if key not in op:
                errors.append(f"{where}: missing {key}")
        reqs, scr, tbl = set(op.get("x-requirements", [])), set(op.get("x-screens", [])), set(op.get("x-tables", []))
        if not reqs:
            errors.append(f"{where}: x-requirements is empty")
        for unknown, label in ((reqs - all_req_ids, "requirement"), (scr - screen_ids, "screen"), (tbl - tables, "table")):
            if unknown:
                errors.append(f"{where}: unknown {label} {sorted(unknown)}")
        is_ops = "ops" in op.get("tags", [])
        if not is_ops and (not scr or not tbl):
            errors.append(f"{where}: business operation needs screens and tables")
        used_req |= reqs
        used_screens |= scr
        used_tables |= tbl

        params = [resolve(p, spec) for p in path_params + op.get("parameters", [])]
        if path.startswith("/me") and any(p["name"] == "user_id" for p in params):
            errors.append(f"{where}: /me operations must not take user_id")
        for name in re.findall(r"{(\w+)}", path):
            if not any(p["name"] == name and p["in"] == "path" for p in params):
                errors.append(f"{where}: path parameter {name} not declared")

        security = op.get("security", spec.get("security"))
        protected = security and not any(s == {} for s in security)
        responses = op["responses"]
        if protected and "401" not in responses:
            errors.append(f"{where}: protected operation without 401")
        if path.startswith("/admin") and "403" not in responses:
            errors.append(f"{where}: admin operation without 403")
        # 브라우저 리디렉트 전용 operation(#328 Google start·callback)은 302 가 정상 응답이다.
        if not any(code.startswith(("2", "3")) for code in responses):
            errors.append(f"{where}: no success response")

        bodies = []
        if "requestBody" in op:
            bodies += [("request", mt, c) for mt, c in op["requestBody"]["content"].items()]
        for code, resp in responses.items():
            resp = resolve(resp, spec)
            error_schema = resolve(ERROR_SCHEMA, spec)
            for mt, c in resp.get("content", {}).items():
                bodies.append((code, mt, c))
                if code[0] in "45" and (mt != "application/json" or resolve(c.get("schema"), spec) != error_schema):
                    errors.append(f"{where} {code}: errors must use application/json + ErrorResponse")
        for label, mt, content in bodies:
            if "example" in content and "schema" in content:
                examples += 1
                schema = resolve(content["schema"], spec)
                try:
                    jsonschema.Draft202012Validator(schema).validate(content["example"])
                except jsonschema.ValidationError as exc:
                    errors.append(f"{where} {label} {mt}: example invalid: {exc.message} at {list(exc.absolute_path)}")

    dupes = {o for o in op_ids if op_ids.count(o) > 1}
    if dupes:
        errors.append(f"duplicate operationId {sorted(dupes)}")
    for missing, exempt, label in (
        (fr_ids - used_req, REQUIREMENT_EXEMPT, "requirements"),
        (screen_ids - used_screens, SCREEN_EXEMPT, "screens"),
        (tables - used_tables, TABLE_EXEMPT, "tables"),
    ):
        if missing - set(exempt):
            errors.append(f"{label} without any operation: {sorted(missing - set(exempt))}")
        stale = set(exempt) - missing
        if stale:
            errors.append(f"{label} exemption no longer needed: {sorted(stale)}")
    stats = {
        "operations": len(op_ids),
        "schemas": len(spec["components"]["schemas"]),
        "examples": examples,
        "requirements": f"{len(fr_ids & used_req)}/{len(fr_ids)} (+{len(REQUIREMENT_EXEMPT)} exempt)",
        "screens": f"{len(screen_ids & used_screens)}/{len(screen_ids)} (+{len(SCREEN_EXEMPT)} exempt)",
        "tables": f"{len(tables & used_tables)}/{len(tables)} (+{len(TABLE_EXEMPT)} exempt)",
    }
    return errors, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements-root", type=Path, default=ROOT / "docs" / "requirements")
    args = ap.parse_args()
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    validate_spec(spec)
    if not (args.requirements_root / "traceability" / "TRACEABILITY.md").exists():
        print(f"FAIL {args.requirements_root} not found (T04 요구사항 문서 필요). --requirements-root로 지정하세요", file=sys.stderr)
        return 2
    errors, stats = check(spec, args.requirements_root)
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    if errors:
        return 1
    print("PASS openapi=3.1 " + " ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
