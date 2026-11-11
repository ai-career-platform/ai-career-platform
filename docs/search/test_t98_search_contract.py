"""T98 고급 검색 계약 시험 (문서·제안 — 서버 코드 없음, DB 없음).

1) 계약 문서 §3~§6 을 그대로 옮긴 **참조 판정 함수**(`reference_search`)로 수용 사례(t98_acceptance_cases.json)의 기대 결과를
   재현합니다. 기대값은 사람이 손으로 정한 것이고, 참조 함수가 그것과 일치해야 계약 문장이 모순 없다는 뜻입니다.
   같은 JSON 을 T99 가 실제 PostgreSQL·API 에 그대로 돌립니다.
2) 제안 OpenAPI 를 docs/api/openapi.yaml 에 메모리로 합쳐 프로젝트 검사기를 통과하는지 확인합니다.

    python -B -m unittest docs/search/test_t98_search_contract.py -v
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "docs/search"
CASES = json.loads((HERE / "t98_acceptance_cases.json").read_text(encoding="utf-8"))
CONTRACT = (HERE / "T98_ADVANCED_SEARCH_CONTRACT.md").read_text(encoding="utf-8")

try:
    import yaml  # noqa: F401
    import openapi_spec_validator  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False

EMPLOYMENT = {"full_time", "contract", "intern", "part_time"}
WITHIN = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}
LIMITS = {"company_id": 10, "job_role_id": 10, "employment_type": 4, "region": 5}


def region_aliases() -> dict[str, tuple[str, ...]]:
    """계약 문서 §4 표를 읽어 (코드 → 별칭) 을 만듭니다 — 문서가 기준."""
    section = CONTRACT.split("## 4.", 1)[1].split("\n## ", 1)[0]
    out = {}
    for row in section.splitlines():
        m = re.match(r"^\| `([a-z]+)` \| [^|]+ \| ([^|]+) \|", row)
        if m:
            out[m.group(1)] = tuple(a.strip() for a in m.group(2).split(","))
    return out


ALIASES = region_aliases()


class Invalid(Exception):
    pass


def ts(value):
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def expand(params: dict) -> dict:
    q = params.get("q")
    if isinstance(q, dict):
        params = {**params, "q": q["repeat"] * q["times"]}
    return params


def normalize(params: dict) -> dict:
    """§3 검증·정규화. 위반이면 Invalid(→ 422)."""
    params = expand(params)
    out: dict = {}
    if "q" in params:
        q = " ".join(params["q"].split())
        if not 1 <= len(q) <= 100:
            raise Invalid("q")
        out["q"] = q
    for key, limit in LIMITS.items():
        values = params.get(key, [])
        if len(values) > limit:                       # 개수는 중복 제거 전 기준
            raise Invalid(key)
        if key == "employment_type" and not set(values) <= EMPLOYMENT:
            raise Invalid(key)
        if key == "region" and not set(values) <= set(ALIASES):
            raise Invalid(key)
        if key == "job_role_id":
            for v in values:
                if v not in CASES["job_roles"]:
                    try:
                        UUID(v)
                    except ValueError:
                        raise Invalid(key) from None
        if values:
            out[key] = sorted(set(values))
    if "posted_within" in params:
        if params["posted_within"] not in WITHIN:
            raise Invalid("posted_within")
        out["posted_within"] = params["posted_within"]
    if params.get("sort", "-published_at") not in {"-published_at", "expires_at"}:
        raise Invalid("sort")
    out["sort"] = params.get("sort", "-published_at")
    out["include_closed"] = bool(params.get("include_closed", False))
    limit = params.get("limit", 20)
    if not 1 <= limit <= 100:
        raise Invalid("limit")
    out["limit"] = limit
    return out


def region_of(location: str | None) -> str | None:
    if not location or not location.strip():
        return None
    token = location.split()[0]
    for code, aliases in ALIASES.items():
        if any(token.startswith(a) for a in aliases):
            return code
    return None


def reference_search(params: dict) -> list[str]:
    p = normalize(params)
    now = ts(CASES["now"])
    rows = []
    for key, post in CASES["postings"].items():
        if post["status"] == "draft":
            continue
        is_open = post["status"] == "published" and (post["expires_at"] is None or ts(post["expires_at"]) > now)
        if not p["include_closed"] and not is_open:
            continue
        company = CASES["companies"][post["company"]]["name"]
        if "q" in p and p["q"].lower() not in post["title"].lower() and p["q"].lower() not in company.lower():
            continue
        if "company_id" in p and post["company"] not in p["company_id"]:
            continue
        if "job_role_id" in p and post["role"] not in p["job_role_id"]:
            continue
        if "employment_type" in p and post["employment_type"] not in p["employment_type"]:
            continue
        if "region" in p and region_of(post["location_text"]) not in p["region"]:
            continue
        if "posted_within" in p:
            published = ts(post["published_at"])
            if published is None or published < now - timedelta(days=WITHIN[p["posted_within"]]):
                continue
        rows.append((key, post))
    if p["sort"] == "expires_at":
        far = datetime.max.replace(tzinfo=now.tzinfo)
        rows.sort(key=lambda r: (ts(r[1]["expires_at"]) or far, r[0]))
    else:
        near = datetime.min.replace(tzinfo=now.tzinfo)
        rows.sort(key=lambda r: (ts(r[1]["published_at"]) or near, r[0]), reverse=True)
    return [k for k, _ in rows]


class AcceptanceCaseTest(unittest.TestCase):
    def test_every_case_matches_the_hand_written_expectation(self):
        for case in CASES["cases"]:
            with self.subTest(case["id"]):
                self.assertEqual(reference_search(case["params"]), case["expect"], case["why"])

    def test_invalid_requests_are_rejected(self):
        for case in CASES["invalid"]:
            with self.subTest(case["id"]), self.assertRaises(Invalid):
                normalize({k: v for k, v in case["params"].items() if not k.startswith("_")})

    def test_pagination_cases_walk_without_duplicates(self):
        for case in CASES["pagination"]:
            full = reference_search(case["params"])
            pages = [full[i:i + case["page_size"]] for i in range(0, len(full), case["page_size"])]
            self.assertEqual([x for page in pages for x in page], full)
            self.assertEqual(len(set(full)), len(full))

    def test_cases_cover_every_proposed_parameter_and_every_status(self):
        used = {k for c in CASES["cases"] + CASES["invalid"] for k in c["params"]} - {"_note"}
        self.assertEqual(used, {"q", "company_id", "job_role_id", "employment_type", "region", "posted_within",
                                "include_closed", "sort", "limit"})
        statuses = {CASES["postings"][k]["status"] for c in CASES["cases"] for k in c["expect"]}
        self.assertEqual(statuses, {"published", "closed"})
        self.assertNotIn("p08", {k for c in CASES["cases"] for k in c["expect"]}, "draft must never appear")

    def test_normalisation_makes_order_and_duplicates_irrelevant_for_the_cursor(self):
        a = normalize({"employment_type": ["contract", "full_time", "contract"], "q": " 개발자 "})
        b = normalize({"q": "개발자", "employment_type": ["full_time", "contract"]})
        self.assertEqual(a, b)

    def test_region_table_has_all_17_codes_and_no_alias_collisions(self):
        self.assertEqual(len(ALIASES), 17)
        pairs = [(a, code) for code, aliases in ALIASES.items() for a in aliases]
        for a, code_a in pairs:
            for b, code_b in pairs:
                if code_a != code_b:
                    self.assertFalse(b.startswith(a), f"alias {a} ({code_a}) is a prefix of {b} ({code_b})")
        self.assertEqual(region_of("충청북도 청주시"), "chungbuk")
        self.assertEqual(region_of("경기도 광주시"), "gyeonggi")       # 경기 광주시는 경기
        self.assertIsNone(region_of("재택근무"))
        self.assertIsNone(region_of("  "))

    def test_contract_marks_status_and_unavailable_fields(self):
        self.assertIn("**PROPOSED / 미승인**", CONTRACT)
        for field in ("기술", "경력", "연봉", "학력"):
            self.assertRegex(CONTRACT, rf"\| {field}[^|]*\| [^|]*\| \*\*HOLD\*\*")


def load_checker():
    spec = importlib.util.spec_from_file_location("check_openapi", ROOT / "docs/api/check_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DEPS, "needs pyyaml, openapi-spec-validator")
class OpenApiProposalTest(unittest.TestCase):
    def setUp(self):
        import yaml
        self.base = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
        self.proposal = yaml.safe_load((HERE / "t98_openapi_proposal.yaml").read_text(encoding="utf-8"))
        self.merged = copy.deepcopy(self.base)
        self.merged["paths"]["/job-postings"]["get"] = self.proposal["paths"]["/job-postings"]["get"]
        self.merged["components"]["schemas"].update(self.proposal["components"]["schemas"])

    def test_merged_contract_is_valid_and_passes_the_project_checker(self):
        from openapi_spec_validator import validate as validate_spec
        validate_spec(self.merged)
        errors, _ = load_checker().check(self.merged, ROOT / "docs/requirements")
        self.assertEqual(errors, [])

    def test_backward_compatible_with_the_current_parameters(self):
        old = {p.get("name") or p["$ref"].rsplit("/", 1)[-1].lower() for p in self.base["paths"]["/job-postings"]["get"]["parameters"]}
        new = {p.get("name") or p["$ref"].rsplit("/", 1)[-1].lower() for p in self.proposal["paths"]["/job-postings"]["get"]["parameters"]}
        self.assertLessEqual(old, new)
        old_op = self.base["paths"]["/job-postings"]["get"]
        new_op = self.proposal["paths"]["/job-postings"]["get"]
        self.assertEqual(old_op["operationId"], new_op["operationId"])
        self.assertEqual(old_op["responses"]["200"]["content"]["application/json"]["schema"],
                         new_op["responses"]["200"]["content"]["application/json"]["schema"])
        self.assertEqual(set(old_op["responses"]), set(new_op["responses"]))

    def test_region_enum_matches_the_contract_table(self):
        self.assertEqual(set(self.proposal["components"]["schemas"]["RegionCode"]["enum"]), set(ALIASES))


if __name__ == "__main__":
    unittest.main()
