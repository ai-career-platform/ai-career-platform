"""T80 moderation design checks (documents only, no API/DB code).

Parses docs/admin/MODERATION_STATE_DIAGRAM.md and checks that the state table, transition table and Mermaid
diagram agree, that the model has no dead ends, and that the guards in the table enforce the policy
(self-review ban, different reviewer for appeals, one appeal within 14 days, optimistic version).
It also cross-checks cited facts against the repository (error catalog, roles seed).

    python -B -m unittest docs/admin/test_moderation_state_model.py -v
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAGRAM = (ROOT / "docs/admin/MODERATION_STATE_DIAGRAM.md").read_text(encoding="utf-8")
POLICY = (ROOT / "docs/admin/MODERATION_POLICY.md").read_text(encoding="utf-8")
CONTRACT = (ROOT / "docs/admin/MODERATION_IMPLEMENTATION_CONTRACT.md").read_text(encoding="utf-8")
GRADES = {"FACT", "REVIEW-PROPOSED", "PROPOSED", "OPEN"}
START = "[*]"


def table_rows(text: str, first_cell: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and re.match(first_cell, line.split("|")[1].strip()):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


STATES = {r[0]: {"terminal": r[2], "grade": r[3]} for r in table_rows(
    DIAGRAM.split("## 2. 상태", 1)[1].split("## 3.", 1)[0], r"^[A-Z_]+$")}


@dataclass(frozen=True)
class Transition:
    tid: str
    source: str
    event: str
    target: str
    actor: str
    guard: str
    grade: str


TRANSITIONS = [Transition(*r) for r in table_rows(DIAGRAM, r"^T\d\d$")]
MERMAID = DIAGRAM.split("```mermaid", 1)[1].split("```", 1)[0]
EDGES = {(m[0], m[1], m[2]) for m in re.findall(r"^\s*(\S+)\s*-->\s*(\S+)\s*:\s*([A-Z_]+)\s*$", MERMAID, re.M)}
EXITS = set(re.findall(r"^\s*([A-Z_]+)\s*-->\s*\[\*\]\s*$", MERMAID, re.M))


# --------------------------------------------------------------------------- tiny simulator of the table

@dataclass
class Case:
    owner: str
    status: str = "PENDING"
    assignee: str | None = None
    first_decider: str | None = None
    appeal_count: int = 0
    days_since_decision: int = 0
    version: int = 1
    log: list[str] = field(default_factory=list)


ADMINS = {"A", "B", "C"}


def guard_ok(t: Transition, case: Case, actor: str, *, version: int, reason: str | None = None,
             note: str | None = None, assignee: str | None = None, admins: set[str] = ADMINS) -> bool:
    """Evaluates the guard text of the table (only the clauses the table uses)."""
    g = t.guard
    if "version 일치" in g and version != case.version:
        return False
    role_ok = (
        ("admin" in t.actor and actor in admins)
        or ("assignee" in t.actor and actor == case.assignee)
        or ("owner" in t.actor and actor == case.owner)
        or ("system" in t.actor and actor == "system")
    )
    if not role_ok:
        return False
    if t.event in ("APPROVE", "REJECT") and actor != case.assignee:
        return False
    # REASSIGN: "새 담당자도 admin이고 not self …" → 가드의 대상은 새 담당자다.
    subject = actor
    if "새 담당자" in g:
        if assignee not in admins:
            return False
        subject = assignee
    if "not self" in g and subject == case.owner:
        return False
    if "not first_decider" in g:
        applies = "appeal_count == 1이면" not in g or case.appeal_count == 1
        if applies and subject == case.first_decider:
            return False
    if "appeal_count == 0" in g and case.appeal_count != 0:
        return False
    if re.search(r"appeal_count == 1(?!이면)", g) and case.appeal_count != 1:
        return False
    if "14일 이내" in g and case.days_since_decision > 14:
        return False
    if "reason_code 필수" in g and not reason:
        return False
    if "OTHER면 메모 필수" in g and reason == "OTHER" and not note:
        return False
    return True


def fire(case: Case, event: str, actor: str, *, version: int | None = None, **kw) -> bool:
    candidates = [t for t in TRANSITIONS if t.source == case.status and t.event == event]
    for t in candidates:
        if guard_ok(t, case, actor, version=case.version if version is None else version, **kw):
            if t.event == "ASSIGN" or t.event == "REASSIGN":
                case.assignee = kw.get("assignee") or actor
            if "appeal_count를 1로 올림" in t.guard:
                case.appeal_count = 1
            if t.event in ("RELEASE", "RELEASE_APPEAL"):
                case.assignee = None
            if t.event in ("APPROVE", "REJECT"):
                case.first_decider = case.first_decider or actor
                case.assignee = None
                case.days_since_decision = 0
            case.status, case.version = t.target, case.version + 1
            case.log.append(t.tid)
            return True
    return False


class StateModelDocumentTest(unittest.TestCase):
    def test_tables_parse(self):
        self.assertEqual(set(STATES), {"PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "APPEALED", "CLOSED"})
        self.assertEqual(len(TRANSITIONS), 13)
        self.assertEqual([t.tid for t in TRANSITIONS], [f"T{i:02d}" for i in range(1, 14)])

    def test_mermaid_edges_equal_transition_table(self):
        table = {(t.source, t.target, t.event) for t in TRANSITIONS}
        self.assertEqual(EDGES, table)

    def test_mermaid_terminal_exits_match_terminal_states(self):
        terminal = {s for s, v in STATES.items() if v["terminal"] in ("예", "조건부")}
        self.assertEqual(EXITS, terminal)

    def test_all_states_used_and_declared(self):
        used = {t.source for t in TRANSITIONS} | {t.target for t in TRANSITIONS}
        self.assertEqual(used - {START}, set(STATES))

    def test_grades_are_from_the_legend_and_new_state_is_proposed(self):
        for t in TRANSITIONS:
            self.assertIn(t.grade, GRADES, t.tid)
        for name, v in STATES.items():
            self.assertIn(v["grade"], GRADES, name)
        self.assertEqual(STATES["CLOSED"]["grade"], "PROPOSED")
        for legacy in ("PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "APPEALED"):
            self.assertNotEqual(STATES[legacy]["grade"], "FACT", "PR #145 states are candidates, not facts")

    def test_every_state_reachable_and_can_finish(self):
        graph: dict[str, set[str]] = {}
        for t in TRANSITIONS:
            graph.setdefault(t.source, set()).add(t.target)
        seen, todo = set(), [START]
        while todo:
            for nxt in graph.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        self.assertEqual(seen, set(STATES))
        finals = {s for s, v in STATES.items() if v["terminal"] in ("예", "조건부")}
        for state in STATES:
            reach, todo = {state}, [state]
            while todo:
                for nxt in graph.get(todo.pop(), ()):
                    if nxt not in reach:
                        reach.add(nxt)
                        todo.append(nxt)
            self.assertTrue(reach & finals, state)

    def test_final_states_have_no_outgoing_transitions(self):
        for t in TRANSITIONS:
            self.assertNotIn(t.source, {"APPROVED", "CLOSED"}, t.tid)
        self.assertNotIn(("APPROVED", "IN_REVIEW"), {(t.source, t.target) for t in TRANSITIONS})

    def test_decisions_need_assignee_not_self_and_reason(self):
        decisions = [t for t in TRANSITIONS if t.event in ("APPROVE", "REJECT")]
        self.assertEqual({t.source for t in decisions}, {"IN_REVIEW"})
        for t in decisions:
            self.assertEqual(t.actor, "assignee")
            self.assertIn("not self", t.guard)
            self.assertIn("not first_decider", t.guard)
        reject = next(t for t in decisions if t.event == "REJECT")
        self.assertIn("reason_code 필수", reject.guard)
        self.assertIn("OTHER면 메모 필수", reject.guard)

    def test_appeal_is_owner_only_once_within_14_days(self):
        appeals = [t for t in TRANSITIONS if t.event == "APPEAL"]
        self.assertEqual(len(appeals), 1)
        self.assertEqual((appeals[0].source, appeals[0].actor), ("REJECTED", "owner"))
        self.assertIn("appeal_count == 0", appeals[0].guard)
        self.assertIn("14일 이내", appeals[0].guard)
        self.assertIn("appeal_count를 1로 올림", appeals[0].guard, "appeal is counted when it is submitted")
        review = next(t for t in TRANSITIONS if t.source == "APPEALED" and t.event == "ASSIGN")
        self.assertIn("not first_decider", review.guard)
        self.assertIn("appeal_count 변경 없음", review.guard)
        incrementing = [t.tid for t in TRANSITIONS if "appeal_count를 1로 올림" in t.guard]
        self.assertEqual(incrementing, ["T08"], "exactly one transition increments appeal_count")

    def test_every_mutation_checks_version(self):
        for t in TRANSITIONS:
            if t.actor != "system" and t.event not in ("SUBMIT", "CLOSE"):
                self.assertIn("version 일치", t.guard, t.tid)


class GuardSimulationTest(unittest.TestCase):
    def test_pre_publish_approval(self):
        case = Case(owner="seller")
        self.assertTrue(fire(case, "ASSIGN", "A"))
        self.assertTrue(fire(case, "APPROVE", "A"))
        self.assertEqual(case.status, "APPROVED")
        for event in ("ASSIGN", "REJECT", "APPEAL", "CLOSE"):
            self.assertFalse(fire(case, event, "B"), event)

    def test_admin_cannot_review_own_content(self):
        case = Case(owner="A")
        self.assertFalse(fire(case, "ASSIGN", "A"))
        self.assertTrue(fire(case, "ASSIGN", "B"))
        self.assertFalse(fire(case, "REASSIGN", "B", assignee="A"), "cannot hand the case to its owner")
        self.assertFalse(fire(case, "REASSIGN", "B", assignee="outsider"), "new assignee must be an admin")
        self.assertTrue(fire(case, "REASSIGN", "B", assignee="C"))
        self.assertFalse(fire(case, "APPROVE", "B"), "only the current assignee decides")
        self.assertTrue(fire(case, "APPROVE", "C"))

    def test_single_admin_with_own_content_stays_pending(self):
        case = Case(owner="A")
        self.assertFalse(fire(case, "ASSIGN", "A"))
        self.assertEqual(case.status, "PENDING")

    def test_reject_requires_reason_and_other_requires_note(self):
        case = Case(owner="seller")
        fire(case, "ASSIGN", "A")
        self.assertFalse(fire(case, "REJECT", "A"))
        self.assertFalse(fire(case, "REJECT", "A", reason="OTHER"))
        self.assertTrue(fire(case, "REJECT", "A", reason="OTHER", note="설명"))

    def test_appeal_goes_to_a_different_admin_once_and_is_final(self):
        case = Case(owner="seller")
        fire(case, "ASSIGN", "A")
        fire(case, "REJECT", "A", reason="INACCURATE")
        self.assertFalse(fire(case, "APPEAL", "stranger"))
        self.assertTrue(fire(case, "APPEAL", "seller"))
        self.assertFalse(fire(case, "ASSIGN", "A"), "first decider must not review the appeal")
        self.assertTrue(fire(case, "ASSIGN", "B"))
        self.assertFalse(fire(case, "REASSIGN", "C", assignee="A"), "appeal review cannot move to the first decider")
        self.assertTrue(fire(case, "REJECT", "B", reason="INACCURATE"))
        self.assertFalse(fire(case, "APPEAL", "seller"), "second appeal is blocked")
        self.assertEqual(case.log, ["T02", "T07", "T08", "T09", "T07"])

    def test_appeal_after_14_days_is_blocked(self):
        case = Case(owner="seller")
        fire(case, "ASSIGN", "A")
        fire(case, "REJECT", "A", reason="EXPIRED")
        case.days_since_decision = 15
        self.assertFalse(fire(case, "APPEAL", "seller"))

    def test_release_returns_to_the_right_queue(self):
        case = Case(owner="seller")
        fire(case, "ASSIGN", "A")
        self.assertTrue(fire(case, "RELEASE", "A"))
        self.assertEqual(case.status, "PENDING")
        fire(case, "ASSIGN", "A")
        fire(case, "REJECT", "A", reason="DUPLICATE")
        fire(case, "APPEAL", "seller")
        fire(case, "ASSIGN", "B")
        self.assertFalse(fire(case, "RELEASE", "B"), "appeal review must not fall back to PENDING")
        self.assertTrue(fire(case, "RELEASE_APPEAL", "B"))
        self.assertEqual((case.status, case.appeal_count), ("APPEALED", 1))
        self.assertFalse(fire(case, "ASSIGN", "A"))

    def test_stale_version_conflicts(self):
        case = Case(owner="seller")
        stale = case.version
        self.assertTrue(fire(case, "ASSIGN", "A", version=stale))
        self.assertFalse(fire(case, "REASSIGN", "B", version=stale, assignee="B"))

    def test_decision_without_assignment_is_impossible(self):
        case = Case(owner="seller")
        self.assertFalse(fire(case, "APPROVE", "A"))
        self.assertFalse(fire(case, "REJECT", "A", reason="HARMFUL"))

    def test_withdraw_only_by_owner_before_review(self):
        case = Case(owner="seller")
        self.assertFalse(fire(case, "CLOSE", "stranger"))
        self.assertTrue(fire(case, "CLOSE", "seller"))
        in_review = Case(owner="seller")
        fire(in_review, "ASSIGN", "A")
        self.assertFalse(fire(in_review, "CLOSE", "seller"), "owner cannot withdraw during review")
        self.assertTrue(fire(in_review, "CLOSE", "system"), "target deleted")


class PolicyAndContractConsistencyTest(unittest.TestCase):
    def test_policy_is_not_marked_approved(self):
        for name, text in (("policy", POLICY), ("diagram", DIAGRAM), ("contract", CONTRACT)):
            self.assertRegex(text, r"(정책 승인|PM 승인): 미완료|PROPOSED / 구현 전", name)
            self.assertNotRegex(text, r"정책 승인: (완료|승인)|PM 승인: 완료", name)

    def test_rejection_reason_codes(self):
        section = POLICY.split("### 5.1", 1)[1].split("### 5.2", 1)[0]
        codes = {r[0].strip("`") for r in table_rows(section, r"^`[A-Z_]+`$")}
        self.assertEqual(codes, {"RIGHTS_UNCLEAR", "INACCURATE", "PERSONAL_DATA", "HARMFUL", "DISCRIMINATORY",
                                 "DUPLICATE", "EXPIRED", "MALWARE", "OTHER"})

    def test_sla_values_are_not_facts(self):
        section = POLICY.split("## 6.", 1)[1].split("## 7.", 1)[0]
        self.assertIn("REVIEW-PROPOSED", section)
        self.assertNotIn("FACT", section)
        self.assertIn("자동 승인·반려하지 않는다", section)

    def test_cited_error_codes_exist_in_the_backend_catalog(self):
        catalog = (ROOT / "backend/app/core/errors.py").read_text(encoding="utf-8")
        existing = set(re.findall(r'^\s+([A-Z_]+) = "', catalog, re.M))
        cited = set(re.findall(r"\b(\d{3}) `([A-Z_]+)`", POLICY + CONTRACT))
        self.assertTrue(cited)
        for _, code in cited:
            self.assertIn(code, existing, f"{code} is cited as an existing error code")

    def test_cited_role_exists_and_review_permission_is_only_proposed(self):
        seed = (ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8")
        self.assertIn("('admin', '운영 관리자')", seed)
        self.assertNotIn("admin.content.review", seed, "permission must stay a proposal until a migration adds it")
        self.assertIn("권한 코드 `admin.content.review`를 admin 역할에 부여", POLICY)

    def test_no_moderation_table_or_route_exists_yet(self):
        migration = (ROOT / "database/migrations").glob("*.sql")
        self.assertFalse(any("moderation_cases" in p.read_text(encoding="utf-8") for p in migration))
        openapi = (ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8")
        self.assertNotIn("moderation-cases", openapi)
        self.assertNotIn("/admin/reviews", openapi)


class AppealCountingTest(unittest.TestCase):
    """Review fix: appeal_count is counted when the appeal is submitted (T08), never at assignment."""

    def _rejected(self) -> Case:
        case = Case(owner="seller")
        fire(case, "ASSIGN", "A")
        fire(case, "REJECT", "A", reason="INACCURATE")
        return case

    def test_count_is_one_as_soon_as_the_appeal_is_submitted(self):
        case = self._rejected()
        self.assertTrue(fire(case, "APPEAL", "seller"))
        self.assertEqual((case.status, case.appeal_count, case.assignee), ("APPEALED", 1, None))
        self.assertTrue(fire(case, "ASSIGN", "B"))
        self.assertEqual(case.appeal_count, 1, "assignment does not change the count")

    def test_withdrawn_appeal_keeps_the_rejection_and_cannot_be_resubmitted(self):
        case = self._rejected()
        fire(case, "APPEAL", "seller")
        self.assertFalse(fire(case, "WITHDRAW_APPEAL", "stranger"))
        self.assertTrue(fire(case, "WITHDRAW_APPEAL", "seller"))
        self.assertEqual((case.status, case.appeal_count), ("REJECTED", 1))
        self.assertFalse(fire(case, "APPEAL", "seller"))

    def test_owner_cannot_close_an_appeal_any_more_only_system_on_target_deletion(self):
        close = next(t for t in TRANSITIONS if t.source == "APPEALED" and t.event == "CLOSE")
        self.assertEqual(close.actor, "system")
        withdraw = next(t for t in TRANSITIONS if t.event == "WITHDRAW_APPEAL")
        self.assertEqual((withdraw.source, withdraw.target, withdraw.actor), ("APPEALED", "REJECTED", "owner"))

    def test_contract_and_policy_use_the_same_rule(self):
        self.assertIn("**이의제기 접수(T08)에서 0 → 1**", CONTRACT)
        self.assertIn("재검토 배정(T09)은 횟수를 바꾸지 않는다", CONTRACT)
        self.assertIn("CHECK (status <> 'APPEALED' OR appeal_count = 1)", CONTRACT)
        self.assertIn("접수하는 순간 1회로 센다", POLICY)
        self.assertIn("**`appeal_count`는 이의제기 접수(T08) 시점에 0 → 1**", DIAGRAM)


SKETCH = CONTRACT.split("```sql", 1)[1].split("```", 1)[0]
TARGET_TABLE_ROWS = table_rows(CONTRACT.split("## 1. 검수 대상 유형", 1)[1].split("## 2.", 1)[0], r"^`[a-z_]+`$")
TARGET_COLUMNS = {r[0].strip("`"): r[3].strip("`") for r in TARGET_TABLE_ROWS if r[0] != "`target_type`"}


def migration_primary_keys() -> dict[str, str]:
    sql = (ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8")
    keys = {}
    for table, body in re.findall(r"CREATE TABLE career\.(\w+) \((.*?)\n\);", sql, re.S):
        pk = re.search(r"PRIMARY KEY \((\w+)\)", body)
        if pk:
            keys[table] = pk.group(1)
    return keys


class TargetReferenceSketchTest(unittest.TestCase):
    """Review fixes 1 and 2: deleting a target must not fail, history stays, AI results keep real FKs."""

    def test_eight_target_types_each_map_to_one_real_fk_column(self):
        self.assertEqual(len(TARGET_COLUMNS), 8)
        self.assertEqual(len(set(TARGET_COLUMNS.values())), 8)
        listed = re.search(r"target_type IN \((.*?)\)\),", SKETCH, re.S).group(1)
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", listed)), set(TARGET_COLUMNS))

    def test_fk_columns_reference_existing_primary_keys_and_set_null_on_delete(self):
        keys = migration_primary_keys()
        for target_type, column in TARGET_COLUMNS.items():
            m = re.search(rf"^\s+{column} uuid REFERENCES career\.(\w+) \((\w+)\) ON DELETE SET NULL,$", SKETCH, re.M)
            self.assertIsNotNone(m, f"{column} must be a nullable FK with ON DELETE SET NULL")
            table, pk = m.groups()
            self.assertEqual(keys.get(table), pk, f"{target_type}: {table}.{pk} is not the 0001 primary key")

    def test_snapshot_is_required_and_not_a_foreign_key(self):
        self.assertRegex(SKETCH, r"(?m)^\s+target_type varchar\(32\) NOT NULL,$")
        self.assertRegex(SKETCH, r"(?m)^\s+target_id uuid NOT NULL,$")
        self.assertNotRegex(SKETCH, r"target_id uuid[^,\n]*REFERENCES")
        self.assertIn("target snapshot is immutable", SKETCH)

    def test_check_allows_null_after_delete_instead_of_requiring_exactly_one(self):
        self.assertIn("recommendation_run_id) <= 1", SKETCH)
        self.assertNotRegex(SKETCH, r"num_nonnulls\([^)]*\)\s*=\s*1")
        for target_type, column in TARGET_COLUMNS.items():
            self.assertIn(f"({column} IS NULL OR (target_type = '{target_type}' AND {column} = target_id))", SKETCH)

    def test_insert_requires_the_live_reference_and_live_target_covers_every_type(self):
        self.assertIn("IF TG_OP = 'INSERT' THEN", SKETCH)
        self.assertIn("career.moderation_case_live_target(NEW) IS DISTINCT FROM NEW.target_id", SKETCH)
        for target_type, column in TARGET_COLUMNS.items():
            self.assertIn(f"WHEN '{target_type}' THEN c.{column}", SKETCH)

    def test_open_cases_close_on_delete_and_decided_cases_keep_their_status(self):
        self.assertIn("AND OLD.status IN ('PENDING', 'IN_REVIEW', 'APPEALED') THEN", SKETCH)
        self.assertIn("NEW.close_reason := 'TARGET_DELETED';", SKETCH)
        self.assertIn("INSERT INTO career.moderation_case_events", SKETCH)
        self.assertIn("BEFORE INSERT OR UPDATE ON career.moderation_cases", SKETCH)
        self.assertIn("AFTER UPDATE ON career.moderation_cases", SKETCH)

    def test_open_case_uniqueness_uses_the_snapshot(self):
        self.assertIn("ON career.moderation_cases (target_type, target_id, review_trigger)\n"
                      "    WHERE status IN ('PENDING', 'IN_REVIEW', 'APPEALED');", SKETCH)

    def test_user_references_do_not_block_account_deletion(self):
        for column in ("content_owner_id", "submitted_by", "assignee_id", "first_decider_id", "decided_by"):
            self.assertRegex(SKETCH, rf"{column} uuid REFERENCES career\.users \(user_id\) ON DELETE SET NULL,")

    def test_polymorphic_ai_result_id_is_gone(self):
        self.assertNotIn("ai_result_id", SKETCH)
        self.assertNotIn("content_type", SKETCH)
        self.assertEqual(CONTRACT.count("ai_result_id"), 1, "only the sentence that retires it may mention it")

    def test_delete_order_and_lock_order_are_documented(self):
        self.assertIn("① 대상 행 `SELECT … FOR UPDATE` → ② 그 대상의 열린 건 `SELECT … FOR UPDATE`", CONTRACT)
        self.assertIn("**대상 행 → 검수 건 행** 순서로 잠근다", CONTRACT)


@unittest.skipUnless(os.environ.get("T80_DDL_SKETCH_TEST") == "YES",
                     "opt-in: T80_DDL_SKETCH_TEST=YES and T80_PG_ADMIN_URL=<loopback *_test database>")
class TargetReferenceSketchPostgresTest(unittest.TestCase):
    """Runs the DDL sketch on a disposable PostgreSQL 18 database (drops and recreates schema career there)."""

    SCENARIO_FILE = Path(__file__).with_name("moderation_sketch_scenario.sql")

    def test_sketch_on_disposable_postgres(self):
        from urllib.parse import urlparse
        url = os.environ["T80_PG_ADMIN_URL"]
        parsed = urlparse(url)
        self.assertIn(parsed.hostname, {"127.0.0.1", "localhost"}, "loopback only")
        self.assertTrue(parsed.path.lstrip("/").endswith("_test"), "database name must end with _test")
        psql = os.environ.get("PSQL", "psql")
        migration = (ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8")
        script = "\n".join(["DROP SCHEMA IF EXISTS career CASCADE;", "CREATE SCHEMA career;", migration, SKETCH,
                            self.SCENARIO_FILE.read_text(encoding="utf-8")])
        result = subprocess.run([psql, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", url, "-f", "-"],
                                input=script, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env={**os.environ, "PGCLIENTENCODING": "UTF8", "LC_MESSAGES": "C", "LANG": "C"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("T80_SKETCH_PG=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
