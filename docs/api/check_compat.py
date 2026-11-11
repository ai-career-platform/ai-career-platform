#!/usr/bin/env python3
"""T116 — OpenAPI 하위호환 검사기.

기준 계약(기본: origin/main 의 docs/api/openapi.yaml)과 현재 계약을 비교해 **기존 클라이언트를 깨는 변경**을 찾는다.

BREAKING (exit 1)                                  WARN (exit 0, 보고만)
- 경로·메서드 삭제                                  - 선택 query 파라미터 삭제(FastAPI 는 모르는 query 를 무시)
- 새 필수 파라미터·필수 요청 필드·필수 본문         - 응답 enum 값 추가(클라이언트가 모르는 값)
- 선택 → 필수 전환                                  - 4xx·5xx 응답 문서 삭제
- 요청 자료형 축소·enum 값 삭제·길이/범위 축소        - 성공 응답 코드 추가
- 응답 필드 삭제·필수 → 선택·자료형 변경(null 추가 포함)
- 성공(2xx) 응답 코드 삭제·변경
- 요청 본문에서 필드 삭제(additionalProperties:false 이면 422 가 됨)

예외: docs/api/compat_exceptions.yaml 에 `location`·`rule`·`approved_by`(비어 있으면 무효)가 있는 항목만 ALLOWED.
PROPOSED 계약(docs/**/t*_openapi_proposal.yaml)은 비교 대상이 아니다 — 확정 계약에 자동 병합하지 않는다.

사용:
    python docs/api/check_compat.py                         # origin/main 대비
    python docs/api/check_compat.py --base-ref <git-ref>
    python docs/api/check_compat.py --base-file old.yaml --head-file new.yaml
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC_REL = "docs/api/openapi.yaml"
EXCEPTIONS = ROOT / "docs" / "api" / "compat_exceptions.yaml"
METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
CONSTRAINT_TIGHTER = {"maxLength": "lt", "maxItems": "lt", "maximum": "lt",
                      "minLength": "gt", "minItems": "gt", "minimum": "gt"}


@dataclass(frozen=True)
class Change:
    level: str      # BREAKING | WARN | ALLOWED
    location: str
    rule: str

    def __str__(self) -> str:
        return f"{self.level} {self.location}: {self.rule}"


class Spec:
    def __init__(self, doc: dict):
        self.doc = doc or {}

    def resolve(self, node: Any, seen: tuple[str, ...] = ()) -> tuple[Any, tuple[str, ...]]:
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if ref in seen or not ref.startswith("#/"):
                return {}, seen
            seen = (*seen, ref)
            target: Any = self.doc
            for part in ref[2:].split("/"):
                target = (target or {}).get(part.replace("~1", "/").replace("~0", "~"), {})
            node = target
        return node, seen

    def operations(self) -> dict[tuple[str, str], dict]:
        ops = {}
        for path, item in (self.doc.get("paths") or {}).items():
            item, _ = self.resolve(item)
            for method in METHODS:
                if method in (item or {}):
                    ops[(path, method)] = {"op": item[method], "shared": item.get("parameters") or []}
        return ops


def _types(schema: dict) -> set[str]:
    t = schema.get("type")
    if t is None:
        return set()
    types = set(t) if isinstance(t, list) else {t}
    if schema.get("nullable"):
        types.add("null")
    return types


class Comparator:
    def __init__(self, old: Spec, new: Spec):
        self.old, self.new = old, new
        self.changes: list[Change] = []

    def add(self, level: str, location: str, rule: str) -> None:
        self.changes.append(Change(level, location, rule))

    # -------------------------------------------------------------- schema
    def schema(self, old_s: Any, new_s: Any, loc: str, direction: str, seen=(), depth=0) -> None:
        old_s, seen_o = self.old.resolve(old_s, seen)
        new_s, _ = self.new.resolve(new_s, seen)
        if depth > 12 or not isinstance(old_s, dict) or not isinstance(new_s, dict):
            return
        ot, nt = _types(old_s), _types(new_s)
        if ot and nt:
            if direction == "response" and not nt <= ot:
                self.add("BREAKING", loc, f"response type widened {sorted(ot)} -> {sorted(nt)}")
            elif direction == "request" and not ot <= nt:
                self.add("BREAKING", loc, f"request type narrowed {sorted(ot)} -> {sorted(nt)}")
        oe, ne = old_s.get("enum"), new_s.get("enum")
        if oe is not None and ne is not None:
            if direction == "request" and set(oe) - set(ne):
                self.add("BREAKING", loc, f"request enum values removed {sorted(map(str, set(oe) - set(ne)))}")
            if direction == "response" and set(ne) - set(oe):
                self.add("WARN", loc, f"response enum values added {sorted(map(str, set(ne) - set(oe)))}")
        elif oe is None and ne is not None and direction == "request":
            self.add("BREAKING", loc, "request enum introduced")
        if direction == "request":
            for key, how in CONSTRAINT_TIGHTER.items():
                ov, nv = old_s.get(key), new_s.get(key)
                if nv is not None and (ov is None or (nv < ov if how == "lt" else nv > ov)):
                    self.add("BREAKING", loc, f"request constraint tightened {key} {ov} -> {nv}")
            if old_s.get("pattern") != new_s.get("pattern") and new_s.get("pattern") is not None:
                self.add("BREAKING", loc, "request pattern changed")
        o_props, n_props = old_s.get("properties") or {}, new_s.get("properties") or {}
        o_req, n_req = set(old_s.get("required") or []), set(new_s.get("required") or [])
        if direction == "response":
            for name in o_props:
                if name not in n_props:
                    self.add("BREAKING", f"{loc}.{name}", "response field removed")
            for name in o_req - n_req:
                if name in n_props:
                    self.add("BREAKING", f"{loc}.{name}", "response field no longer required")
        else:
            for name in n_req - o_req:
                self.add("BREAKING", f"{loc}.{name}", "new required request field")
            if new_s.get("additionalProperties") is False:
                for name in o_props:
                    if name not in n_props:
                        self.add("BREAKING", f"{loc}.{name}", "request field removed (would be rejected)")
        for name in o_props.keys() & n_props.keys():
            self.schema(o_props[name], n_props[name], f"{loc}.{name}", direction, seen_o, depth + 1)
        if "items" in old_s and "items" in new_s:
            self.schema(old_s["items"], new_s["items"], f"{loc}[]", direction, seen_o, depth + 1)

    # -------------------------------------------------------------- operation
    def params(self, spec: Spec, entry: dict) -> dict[tuple[str, str], dict]:
        out = {}
        for raw in [*entry["shared"], *(entry["op"].get("parameters") or [])]:
            param, _ = spec.resolve(raw)
            if isinstance(param, dict) and "name" in param:
                out[(param.get("in"), param["name"])] = param
        return out

    @staticmethod
    def _json(content: dict | None) -> Any:
        content = content or {}
        return (content.get("application/json") or next(iter(content.values()), {}) or {}).get("schema")

    def operation(self, key: tuple[str, str], old_e: dict, new_e: dict) -> None:
        loc = f"{key[1].upper()} {key[0]}"
        op_old, op_new = self.params(self.old, old_e), self.params(self.new, new_e)
        for pkey, newp in op_new.items():
            oldp = op_old.get(pkey)
            where = f"{loc} param {pkey[0]}:{pkey[1]}"
            if oldp is None:
                if newp.get("required"):
                    self.add("BREAKING", where, "new required parameter")
                continue
            if newp.get("required") and not oldp.get("required"):
                self.add("BREAKING", where, "parameter became required")
            self.schema(oldp.get("schema"), newp.get("schema"), where, "request")
        for pkey, oldp in op_old.items():
            if pkey not in op_new:
                level = "BREAKING" if pkey[0] in ("path", "header") or oldp.get("required") else "WARN"
                self.add(level, f"{loc} param {pkey[0]}:{pkey[1]}", "parameter removed")
        ob, _ = self.old.resolve(old_e["op"].get("requestBody"))
        nb, _ = self.new.resolve(new_e["op"].get("requestBody"))
        if nb and nb.get("required") and not (ob or {}).get("required"):
            self.add("BREAKING", f"{loc} body", "request body became required")
        if ob and nb:
            self.schema(self._json(ob.get("content")), self._json(nb.get("content")), f"{loc} body", "request")
        o_res, n_res = old_e["op"].get("responses") or {}, new_e["op"].get("responses") or {}
        for code, o_resp in o_res.items():
            where = f"{loc} response {code}"
            if code not in n_res:
                level = "BREAKING" if str(code).startswith("2") else "WARN"
                self.add(level, where, "response status removed")
                continue
            o_resp, _ = self.old.resolve(o_resp)
            n_resp, _ = self.new.resolve(n_res[code])
            self.schema(self._json(o_resp.get("content")), self._json(n_resp.get("content")), where, "response")
        for code in n_res.keys() - o_res.keys():
            if str(code).startswith("2"):
                self.add("WARN", f"{loc} response {code}", "success status added")

    def run(self) -> list[Change]:
        old_ops, new_ops = self.old.operations(), self.new.operations()
        for key in sorted(old_ops):
            if key not in new_ops:
                self.add("BREAKING", f"{key[1].upper()} {key[0]}", "operation removed")
            else:
                self.operation(key, old_ops[key], new_ops[key])
        return self.changes


def load_exceptions(path: Path = EXCEPTIONS) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [e for e in (data.get("exceptions") or []) if str(e.get("approved_by") or "").strip()]


def apply_exceptions(changes: list[Change], exceptions: list[dict]) -> list[Change]:
    approved = {(e.get("location"), e.get("rule")) for e in exceptions if str(e.get("approved_by") or "").strip()}
    return [Change("ALLOWED", c.location, c.rule) if c.level == "BREAKING" and (c.location, c.rule) in approved else c
            for c in changes]


def compare(old_doc: dict, new_doc: dict, exceptions: list[dict] | None = None) -> list[Change]:
    changes = Comparator(Spec(old_doc), Spec(new_doc)).run()
    return apply_exceptions(changes, exceptions or [])


def read_ref(ref: str) -> dict:
    text = subprocess.run(["git", "show", f"{ref}:{SPEC_REL}"], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout
    return yaml.safe_load(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--base-file")
    parser.add_argument("--head-file", default=str(ROOT / SPEC_REL))
    args = parser.parse_args(argv)
    old = yaml.safe_load(Path(args.base_file).read_text(encoding="utf-8")) if args.base_file else read_ref(args.base_ref)
    new = yaml.safe_load(Path(args.head_file).read_text(encoding="utf-8"))
    changes = compare(old, new, load_exceptions())
    for change in changes:
        print(change)
    breaking = sum(c.level == "BREAKING" for c in changes)
    print(f"T116_COMPAT breaking={breaking} warn={sum(c.level == 'WARN' for c in changes)} "
          f"allowed={sum(c.level == 'ALLOWED' for c in changes)}")
    return 1 if breaking else 0


if __name__ == "__main__":
    sys.exit(main())
