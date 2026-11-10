"""T95 알림 계약 시험 (문서·제안만 — 발송 코드 없음, 외부 호출 없음).

1) 수신 설정 매트릭스(T95_PREFERENCE_MATRIX.md)를 읽어 **표 일관성**과 계약 문서 §9 시나리오 S1~S10 을
   작은 참조 판정 함수로 재현합니다(구현이 아니라 계약의 모순 검사).
2) 제안 OpenAPI 조각을 실제 docs/api/openapi.yaml 에 메모리로 합쳐 프로젝트 검사기를 통과하는지 확인합니다
   (제안 요구사항 FR-ACC-008 만 이 실행에서 추가).

    python -B -m unittest docs/notifications/test_t95_notification_contract.py -v
"""
from __future__ import annotations

import copy
import importlib.util
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "docs/notifications"
MATRIX = (HERE / "T95_PREFERENCE_MATRIX.md").read_text(encoding="utf-8")
CONTRACT = (HERE / "T95_NOTIFICATION_CONTRACT.md").read_text(encoding="utf-8")
KST = timezone(timedelta(hours=9))

try:
    import yaml  # noqa: F401
    import jsonschema  # noqa: F401
    import openapi_spec_validator  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False


def parse_types() -> dict[str, dict]:
    section = MATRIX.split("## 알림 유형", 1)[1].split("\n## ", 1)[0]
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| type") and "---" not in r]
    keys = ["type", "group", "required", "consent", "default", "user_off", "channels", "quiet", "dedupe", "retries",
            "retention", "template"]
    out = {}
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        item = dict(zip(keys, cells))
        out[item["type"]] = item
    return out


TYPES = parse_types()


def window(text: str) -> timedelta:
    number, unit = re.fullmatch(r"(\d+)(분|시간|일)", text).groups()
    return {"분": timedelta(minutes=1), "시간": timedelta(hours=1), "일": timedelta(days=1)}[unit] * int(number)


def decide(type_: str, *, consents: dict[str, bool], active: bool, now: datetime, sent: dict, subject: str = "",
           attempts: int = 0) -> str:
    """계약 §3~§5 를 그대로 옮긴 참조 판정: send / block / defer / failed."""
    spec = TYPES[type_]
    if not active and type_ != "account.deletion_receipt":
        return "block"
    if spec["required"] == "아니오":
        granted = consents.get(spec["consent"])
        if granted is None:
            granted = spec["default"] == "켬"
        if not granted:
            return "block"
    if attempts >= int(spec["retries"]):
        return "failed"
    key = (type_, subject)
    if key in sent and now - sent[key] < window(spec["dedupe"]):
        return "block"
    local = now.astimezone(KST)
    if spec["quiet"] == "적용" and (local.hour >= 21 or local.hour < 8):
        return "defer"
    return "send"


DAY = datetime(2026, 11, 11, 14, 0, tzinfo=KST)
NIGHT = datetime(2026, 11, 11, 23, 0, tzinfo=KST)


class MatrixConsistencyTest(unittest.TestCase):
    def test_all_types_parsed_and_match_the_proposal_enum(self):
        self.assertEqual(len(TYPES), 10)
        if DEPS:
            import yaml
            proposal = yaml.safe_load((HERE / "t95_openapi_proposal.yaml").read_text(encoding="utf-8"))
            self.assertEqual(set(proposal["components"]["schemas"]["NotificationType"]["enum"]), set(TYPES))

    def test_required_types_have_no_consent_and_cannot_be_turned_off(self):
        for spec in TYPES.values():
            if spec["required"] == "예":
                self.assertEqual((spec["consent"], spec["user_off"], spec["default"]), ("-", "불가", "켬"), spec["type"])
            else:
                self.assertNotEqual(spec["consent"], "-", spec["type"])
                self.assertEqual(spec["user_off"], "가능", spec["type"])

    def test_security_auth_recovery_ignore_quiet_hours_and_never_use_marketing_consent(self):
        for name, spec in TYPES.items():
            if spec["group"] in {"계정 보안", "이메일 인증", "계정 복구"}:
                self.assertEqual(spec["quiet"], "무시", name)
                self.assertEqual(spec["required"], "예", name)
            if spec["consent"] == "marketing_notification":
                self.assertEqual((spec["group"], spec["default"], spec["quiet"]), ("선택적 마케팅", "끔", "적용"), name)

    def test_every_row_has_channel_window_retries_retention_and_unapproved_template(self):
        for name, spec in TYPES.items():
            self.assertIn(spec["channels"], {"email", "in_app", "email, in_app"}, name)
            window(spec["dedupe"])
            self.assertTrue(1 <= int(spec["retries"]) <= 5, name)
            self.assertIn(spec["retention"], {"90일", "1년"}, name)
            self.assertEqual(spec["template"], "미승인", name)

    def test_proposed_consent_codes_are_listed_and_not_yet_in_the_seed(self):
        codes = {s["consent"] for s in TYPES.values()} - {"-"}
        self.assertEqual(codes, {"service_updates", "recommendation_alerts", "marketing_notification"})
        seed = (ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8")
        privacy = (ROOT / "backend/app/schemas/privacy.py").read_text(encoding="utf-8")
        for code in codes:
            self.assertIn(f"| {code} |", MATRIX)
            self.assertNotIn(code, seed + privacy, "still a proposal — not implemented")


class ScenarioTest(unittest.TestCase):
    """계약 §9 S1~S9."""

    def test_s1_marketing_blocked_after_withdrawal(self):
        self.assertEqual(decide("marketing.newsletter", consents={"marketing_notification": False}, active=True, now=DAY, sent={}), "block")

    def test_s2_password_reset_still_sent_after_marketing_withdrawal(self):
        self.assertEqual(decide("security.password_reset", consents={"marketing_notification": False}, active=True, now=DAY, sent={}), "send")

    def test_s3_recommendation_default_off(self):
        self.assertEqual(decide("recommendation.new_results", consents={}, active=True, now=DAY, sent={}), "block")
        self.assertEqual(decide("recommendation.new_results", consents={"recommendation_alerts": True}, active=True, now=DAY, sent={}), "send")

    def test_s4_s5_quiet_hours_defer_optional_but_not_security(self):
        self.assertEqual(decide("marketing.newsletter", consents={"marketing_notification": True}, active=True, now=NIGHT, sent={}), "defer")
        self.assertEqual(decide("security.password_reset", consents={}, active=True, now=NIGHT, sent={}), "send")
        self.assertEqual(decide("marketing.newsletter", consents={"marketing_notification": True}, active=True,
                                now=datetime(2026, 11, 11, 7, 59, tzinfo=KST), sent={}), "defer")

    def test_s6_inactive_account_gets_only_the_deletion_receipt(self):
        for name in TYPES:
            expected = "send" if name == "account.deletion_receipt" else "block"
            self.assertEqual(decide(name, consents={c: True for c in ("service_updates", "recommendation_alerts", "marketing_notification")},
                                    active=False, now=DAY, sent={}), expected, name)

    def test_s7_duplicates_inside_the_window_are_blocked(self):
        sent = {("security.password_reset", "u1"): DAY}
        self.assertEqual(decide("security.password_reset", consents={}, active=True, now=DAY + timedelta(minutes=4), sent=sent, subject="u1"), "block")
        self.assertEqual(decide("security.password_reset", consents={}, active=True, now=DAY + timedelta(minutes=6), sent=sent, subject="u1"), "send")

    def test_s9_retries_stop_at_the_maximum(self):
        self.assertEqual(decide("marketing.newsletter", consents={"marketing_notification": True}, active=True, now=DAY, sent={}, attempts=2), "failed")
        self.assertEqual(decide("security.new_login", consents={}, active=True, now=DAY, sent={}, attempts=4), "send")

    def test_contract_lists_the_same_scenarios_and_marks_status(self):
        self.assertEqual(re.findall(r"^\| (S\d+) \|", CONTRACT, re.M), [f"S{i}" for i in range(1, 11)])
        self.assertIn("**PROPOSED / 미승인 / 1차 범위 제외**", CONTRACT)
        self.assertIn("외부 이메일·SMS를 구현하거나 호출하지 않았습니다", CONTRACT)


def load_checker():
    spec = importlib.util.spec_from_file_location("check_openapi", ROOT / "docs/api/check_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DEPS, "needs pyyaml, jsonschema, openapi-spec-validator")
class OpenApiProposalTest(unittest.TestCase):
    def setUp(self):
        import yaml
        self.base = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
        self.proposal = yaml.safe_load((HERE / "t95_openapi_proposal.yaml").read_text(encoding="utf-8"))
        self.merged = copy.deepcopy(self.base)
        self.merged["paths"].update(self.proposal["paths"])
        self.merged["components"]["schemas"].update(self.proposal["components"]["schemas"])

    def test_proposal_is_new_and_passes_the_project_checker_with_the_proposed_requirement(self):
        from openapi_spec_validator import validate as validate_spec
        for path in self.proposal["paths"]:
            self.assertNotIn(path, self.base["paths"])
        validate_spec(self.merged)
        checker = load_checker()
        original = checker.load_ids

        def ids(root):
            fr, all_ids, screens = original(root)
            return fr | {"FR-ACC-008"}, all_ids | {"FR-ACC-008"}, screens
        checker.load_ids = ids
        try:
            errors, _ = checker.check(self.merged, ROOT / "docs/requirements")
        finally:
            checker.load_ids = original
        self.assertEqual(errors, [])

    def test_without_the_requirement_change_the_proposal_is_rejected(self):
        errors, _ = load_checker().check(self.merged, ROOT / "docs/requirements")
        self.assertTrue(any("FR-ACC-008" in e for e in errors))

    def test_required_types_cannot_be_disabled_in_the_dto_description(self):
        pref = self.proposal["components"]["schemas"]["NotificationPreference"]
        self.assertIn("끌 수 없음", pref["properties"]["required"]["description"])
        self.assertIn("422", self.proposal["paths"]["/me/notification-preferences"]["put"]["responses"])


if __name__ == "__main__":
    unittest.main()
