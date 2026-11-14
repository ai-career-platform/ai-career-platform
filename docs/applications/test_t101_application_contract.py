"""T101 지원 추적 계약 시험 (문서·제안). 서버 코드 없음.

1) 계약 §4 이동 표를 읽어 참조 상태 기계(T102 가 구현할 규칙)와 49개 단계 쌍을 비교합니다.
2) 제안 OpenAPI 를 docs/api/openapi.yaml 에 메모리로 합쳐 프로젝트 검사기를 통과하는지 확인합니다
   (제안 요구사항 FR-JOB-008·화면 UI-N05·표 job_applications 만 이 실행에서 주입).
3) 제안 DDL 을 **일회용 PostgreSQL** 에 적용해 제약을 확인합니다. T16 가드 환경(T16_ISOLATED_DB_TEST=YES,
   루프백, t16_profile_test)이 없으면 건너뜁니다. 공유 Staging DB 에는 연결하지 않습니다.

    python -B -m unittest docs/applications/test_t101_application_contract.py -v
"""
from __future__ import annotations

import copy
import importlib.util
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "docs/applications"
CONTRACT = (HERE / "T101_APPLICATION_TRACKING_CONTRACT.md").read_text(encoding="utf-8")
DDL = (ROOT / "database/migrations/0004_job_applications.sql").read_text(encoding="utf-8")

STAGES = ("interested", "preparing", "applied", "interviewing", "offered", "rejected", "withdrawn")
# T102 가 구현할 규칙(문서 표와 같아야 함)
TRANSITIONS = {
    "interested": {"preparing", "applied", "withdrawn"},
    "preparing": {"interested", "applied", "withdrawn"},
    "applied": {"preparing", "interviewing", "offered", "rejected", "withdrawn"},
    "interviewing": {"applied", "offered", "rejected", "withdrawn"},
    "offered": {"interviewing", "withdrawn"},
    "rejected": {"interviewing"},
    "withdrawn": {"interested"},
}
NEEDS_DATE = {"applied", "interviewing", "offered", "rejected"}
NO_DATE = {"interested", "preparing"}

try:
    import yaml  # noqa: F401
    import openapi_spec_validator  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False


def table_from_doc() -> dict[str, set[str]]:
    section = CONTRACT.split("## 4.", 1)[1].split("\n## ", 1)[0]
    moves = section.split("허용 이동", 1)[1]
    out = {}
    for row in moves.splitlines():
        m = re.match(r"^\| `([a-z]+)` \| (.+) \|$", row)
        if m:
            out[m.group(1)] = set(re.findall(r"`([a-z]+)`", m.group(2)))
    return out


def allowed(current: str, target: str) -> bool:
    return current == target or target in TRANSITIONS[current]


class StateMachineTest(unittest.TestCase):
    def test_document_table_equals_reference_machine(self):
        self.assertEqual(table_from_doc(), TRANSITIONS)
        self.assertEqual(set(TRANSITIONS), set(STAGES))

    def test_all_49_pairs(self):
        allowed_pairs = sum(allowed(a, b) for a in STAGES for b in STAGES)
        self.assertEqual(allowed_pairs, 7 + sum(len(v) for v in TRANSITIONS.values()))
        self.assertTrue(allowed("interested", "applied"))          # 건너뛰기 허용
        self.assertFalse(allowed("interested", "offered"))
        self.assertFalse(allowed("rejected", "offered"))
        self.assertFalse(allowed("withdrawn", "applied"))           # 다시 관심부터
        self.assertTrue(allowed("rejected", "rejected"))            # 같은 단계(메모 수정)

    def test_every_stage_is_reachable_from_interested_and_can_leave_except_by_rule(self):
        seen, frontier = {"interested"}, ["interested"]
        while frontier:
            for nxt in TRANSITIONS[frontier.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        self.assertEqual(seen, set(STAGES))

    def test_stage_names_and_date_rules_are_documented(self):
        for stage in STAGES:
            self.assertIn(f"| `{stage}` |", CONTRACT)
        self.assertIn("기업의 공식 결과가 아닙니다", CONTRACT)
        self.assertIn("**PROPOSED / 미승인**", CONTRACT)
        for stage in NEEDS_DATE | NO_DATE:
            self.assertIn(f"'{stage}'", DDL)


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
        self.proposal = yaml.safe_load((HERE / "t101_openapi_proposal.yaml").read_text(encoding="utf-8"))
        self.merged = copy.deepcopy(self.base)
        self.merged["paths"].update(self.proposal["paths"])
        self.merged["components"]["schemas"].update(self.proposal["components"]["schemas"])

    def check(self, inject: bool):
        checker = load_checker()
        ids, tables = checker.load_ids, checker.load_tables
        if inject:
            def new_ids(root):
                fr, all_ids, screens = ids(root)
                return fr | {"FR-JOB-008"}, all_ids | {"FR-JOB-008"}, screens | {"UI-N05"}
            checker.load_ids = new_ids
            checker.load_tables = lambda: tables() | {"job_applications"}
        return checker.check(self.merged, ROOT / "docs/requirements")[0]

    def test_proposal_is_new_valid_and_passes_the_checker_with_the_proposed_ids(self):
        from openapi_spec_validator import validate as validate_spec
        for path in self.proposal["paths"]:
            self.assertNotIn(path, self.base["paths"])
        validate_spec(self.merged)
        self.assertEqual(self.check(inject=True), [])

    def test_without_the_proposed_ids_the_checker_rejects_it(self):
        errors = " ".join(self.check(inject=False))
        for word in ("FR-JOB-008", "UI-N05", "job_applications"):
            self.assertIn(word, errors)

    def test_stage_enum_and_memo_limit_match_the_contract(self):
        schemas = self.proposal["components"]["schemas"]
        self.assertEqual(tuple(schemas["ApplicationStage"]["enum"]), STAGES)
        self.assertEqual(schemas["JobApplication"]["properties"]["memo"]["maxLength"], 2000)
        self.assertIn("version", schemas["JobApplicationUpdate"]["required"])


PG = os.environ.get("T16_ISOLATED_DB_TEST") == "YES" and "T16_TEST_ADMIN_URL" in os.environ


@unittest.skipUnless(PG, "disposable PostgreSQL (T16 guard) not configured")
class ProposedDdlOnDisposablePostgresTest(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        url = os.environ["T16_TEST_ADMIN_URL"]
        opts = conninfo_to_dict(url)
        if opts.get("host") not in {"127.0.0.1", "localhost"} or opts.get("dbname") != "t16_profile_test":
            self.fail("Only loopback disposable t16_profile_test is allowed")
        self.db = psycopg.connect(url, autocommit=True)
        self.db.execute("DROP SCHEMA IF EXISTS career CASCADE")
        self.db.execute("CREATE SCHEMA career")
        self.db.execute((ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8"))
        self.db.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        self.db.execute(DDL)
        self.user = self.db.execute("INSERT INTO career.users(email, email_canonical, display_name) VALUES "
                                    "('t101@example.invalid','t101@example.invalid','합성') RETURNING user_id").fetchone()[0]
        self.posting = self.db.execute("SELECT job_posting_id FROM career.job_postings WHERE status='published' "
                                       "ORDER BY job_posting_id LIMIT 1").fetchone()[0]

    def tearDown(self):
        self.db.execute("DROP SCHEMA career CASCADE")
        self.db.close()

    def insert(self, **cols):
        values = {"user_id": self.user, "job_posting_id": self.posting, "posting_title": "합성 공고",
                  "company_name": "합성 기업", **cols}
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        return self.db.execute(f"INSERT INTO career.job_applications ({names}) VALUES ({marks}) RETURNING application_id",
                               list(values.values())).fetchone()[0]

    def test_constraints(self):
        import psycopg
        self.insert()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.insert()
        bad = [dict(stage="hired"), dict(stage="applied"), dict(stage="preparing", applied_on="2026-11-01"),
               dict(applied_on="1999-12-31", stage="applied"), dict(memo="가" * 2001), dict(posting_title="  "),
               dict(version=0)]
        for cols in bad:
            with self.subTest(cols=str(cols)[:40]), self.assertRaises(psycopg.errors.CheckViolation):
                self.insert(job_posting_id=None, **cols)
        self.insert(job_posting_id=None, stage="withdrawn")                 # 지원 전 취소 — 날짜 없어도 됨
        self.insert(job_posting_id=None, stage="withdrawn", applied_on="2026-11-01")
        self.insert(job_posting_id=None, stage="rejected", applied_on="2026-11-01", memo="가" * 2000)

    def test_posting_delete_keeps_snapshot_and_user_delete_cascades(self):
        app = self.insert()
        self.db.execute("DELETE FROM career.user_job_bookmarks WHERE job_posting_id = %s", (self.posting,))
        self.db.execute("DELETE FROM career.job_posting_skills WHERE job_posting_id = %s", (self.posting,))
        self.db.execute("DELETE FROM career.job_postings WHERE job_posting_id = %s", (self.posting,))
        row = self.db.execute("SELECT job_posting_id, posting_title FROM career.job_applications WHERE application_id=%s",
                              (app,)).fetchone()
        self.assertEqual(row, (None, "합성 공고"))
        self.db.execute("DELETE FROM career.users WHERE user_id = %s", (self.user,))
        self.assertEqual(self.db.execute("SELECT count(*) FROM career.job_applications").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
