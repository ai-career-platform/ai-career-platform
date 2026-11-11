"""T111 환경 계약 — Local / CI / Staging 에서 Backend 가 읽는 환경변수의 단일 목록.

- 이 모듈은 **값을 출력하지 않습니다.** 검사 결과에는 변수 이름과 문제 종류만 들어갑니다.
- 실제 파싱 규칙(범위·형식)은 `config.py`·`auth_config.py`·`behavior_events.py` 와 같게 유지합니다.
  `tests/test_t111_env_contract.py` 가 코드에서 읽는 이름과 이 목록이 어긋나면 실패합니다.
- 실제 Secret 회전·Staging 반영은 하지 않습니다(운영 승인 필요). 절차는 docs/ops/SECRET_ROTATION_RUNBOOK.md.

CLI (값을 출력하지 않음):
    python -m app.core.env_contract --target staging
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

TARGETS = ("local", "ci", "staging")

# 예제·자리표시자 값이 Staging 에 그대로 들어가는 사고를 막는다(대소문자 무시, 부분 일치).
PLACEHOLDER_MARKERS = ("change-me", "changeme", "example", "placeholder", "dummy", "replace", "xxxx", "your-")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


@dataclass(frozen=True)
class Finding:
    name: str
    problem: str  # missing | invalid | placeholder | weak | forbidden_in_target

    def __str__(self) -> str:  # 값은 절대 포함하지 않는다
        return f"{self.name}: {self.problem}"


def _int(minimum: int, maximum: int) -> Callable[[str], bool]:
    def check(value: str) -> bool:
        try:
            return minimum <= int(value) <= maximum
        except ValueError:
            return False
    return check


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "0", "false", "no"}


def _flag(value: str) -> bool:
    # config.py 는 'true' 외의 값을 모두 꺼짐으로 읽는다. 오타로 켜지지 않는 일을 막기 위해 계약은 두 값만 허용.
    return value.strip().lower() in {"true", "false"}


def _pg_url(value: str) -> bool:
    if not value.startswith(("postgresql://", "postgres://")) or _BAD_PERCENT.search(value):
        return False
    try:
        parsed = make_url(value)
    except (ArgumentError, ValueError):
        return False
    return bool(parsed.host and parsed.username and parsed.database)


def _rate(value: str) -> bool:
    count, _, seconds = value.strip().partition("/")
    return count.isdigit() and seconds.isdigit() and int(count) > 0 and int(seconds) > 0


def _reset_base(value: str) -> bool:
    # 같은 Origin 상대경로('/password-reset') 또는 https 절대 URL 만. 'http://'·'//host' 는 링크 가로채기 위험
    if value.startswith("/"):
        return not value.startswith("//")
    return value.startswith("https://") and len(value) > len("https://")


@dataclass(frozen=True)
class EnvVar:
    name: str
    required: tuple[str, ...]          # 반드시 있어야 하는 대상
    default: str | None                # 코드 기본값(없으면 None). 문서용 — 코드가 진실
    secret: bool
    owner: str                         # 값을 관리하는 역할
    description: str
    check: Callable[[str], bool] | None = None
    min_length: int = 0
    staging_forbidden: tuple[str, ...] = ()   # Staging 에서 쓰면 안 되는 값(소문자 비교)
    staging_expected: str | None = None       # Staging 에서 반드시 이 값


CONTRACT: tuple[EnvVar, ...] = (
    EnvVar("APP_ENV", ("staging",), "local-dev", False, "DevOps",
           "실행 환경 이름. local-dev/test 외에서는 JWT_SECRET 필수", staging_expected="staging"),
    EnvVar("APP_VERSION", ("staging",), "0.1.0", False, "DevOps(Auto-CD)", "배포 SHA. /version 에 노출"),
    EnvVar("DATABASE_URL", ("staging",), None, True, "DBA", "앱 계정 PostgreSQL URL. 없으면 DB 기능 비활성",
           check=_pg_url),
    EnvVar("DB_POOL_SIZE", (), "5", False, "DevOps", "연결 풀 크기 1~100", check=_int(1, 100)),
    EnvVar("DB_TIMEOUT_SECONDS", (), "5", False, "DevOps", "연결 대기 1~60초", check=_int(1, 60)),
    EnvVar("JWT_SECRET", ("staging",), None, True, "보안 담당",
           "HS256 서명·cursor 서명 키(32자 이상). local-dev/test 에서만 생략 가능(프로세스별 임의 키)",
           min_length=32),
    EnvVar("ACCESS_TOKEN_TTL_SECONDS", (), "900", False, "보안 담당", "60~3600", check=_int(60, 3600)),
    EnvVar("REFRESH_TOKEN_TTL_SECONDS", (), "1209600", False, "보안 담당", "3600~2592000",
           check=_int(3600, 2_592_000)),
    EnvVar("AUTH_COOKIE_SECURE", (), "true", False, "보안 담당", "refresh 쿠키 Secure. Staging 에서 false 금지",
           check=_bool, staging_forbidden=("0", "false", "no")),
    EnvVar("LOGIN_MAX_FAILURES", (), "5", False, "보안 담당", "1~100", check=_int(1, 100)),
    EnvVar("LOGIN_LOCK_SECONDS", (), "900", False, "보안 담당", "10~86400", check=_int(10, 86_400)),
    EnvVar("LOGIN_IP_MAX_ATTEMPTS", (), "30", False, "보안 담당", "1~10000", check=_int(1, 10_000)),
    EnvVar("SIGNUP_IP_MAX_ATTEMPTS", (), "10", False, "보안 담당", "1~10000", check=_int(1, 10_000)),
    EnvVar("AUTH_RATE_WINDOW_SECONDS", (), "900", False, "보안 담당", "10~86400", check=_int(10, 86_400)),
    EnvVar("PASSWORD_RESET_LINK_BASE", (), "/password-reset", False, "Backend",
           "재설정 링크 기준 주소. Staging 에서는 같은 Origin 경로 또는 https 만"),
    EnvVar("DOCUMENT_STORAGE_ROOT", (), None, False, "DevOps", "문서 저장 절대경로(0700). 없으면 파일 I/O 비활성"),
    EnvVar("BEHAVIOR_EVENTS_ENABLED", (), "false", False, "PM(승인)", "행동 이벤트 수집. 승인 전 꺼짐",
           check=_bool),
    EnvVar("BEHAVIOR_EVENTS_RATE_LIMIT", (), "", False, "Backend", "<count>/<seconds>", check=_rate),
    EnvVar("JOB_SEARCH_ADVANCED", (), "false", False, "PM(승인)", "T99 고급 검색. 승인 전 꺼짐", check=_flag),
    EnvVar("JOB_APPLICATIONS_API", (), "false", False, "PM(승인)", "T102 지원 기록 API. 승인 전 꺼짐",
           check=_flag),
    EnvVar("COMPANY_ACCOUNTS_API", (), "false", False, "PM(승인)", "T123 기업 계정 API. 승인 전 꺼짐", check=_flag),
)

BY_NAME = {v.name: v for v in CONTRACT}


def _looks_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def check_environment(target: str, environ: Mapping[str, str]) -> list[Finding]:
    """대상 환경 기준으로 문제 목록을 돌려준다. 값은 결과에 넣지 않는다."""
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    findings: list[Finding] = []
    for var in CONTRACT:
        raw = environ.get(var.name)
        value = raw.strip() if raw is not None else ""
        if not value:
            if target in var.required:
                findings.append(Finding(var.name, "missing"))
            continue
        if var.check is not None and not var.check(value):
            findings.append(Finding(var.name, "invalid"))
            continue
        if var.min_length and len(value) < var.min_length:
            findings.append(Finding(var.name, "weak"))
            continue
        if target == "staging":
            if var.secret and _looks_placeholder(value):
                findings.append(Finding(var.name, "placeholder"))
            elif value.lower() in var.staging_forbidden:
                findings.append(Finding(var.name, "forbidden_in_target"))
            elif var.staging_expected is not None and value != var.staging_expected:
                findings.append(Finding(var.name, "forbidden_in_target"))
            elif var.name == "PASSWORD_RESET_LINK_BASE" and not _reset_base(value):
                findings.append(Finding(var.name, "forbidden_in_target"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backend 환경변수 계약 검사(값은 출력하지 않음)")
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args(argv)
    findings = check_environment(args.target, os.environ)
    for finding in findings:
        print(f"FAIL {finding}")
    print(f"T111_ENV_CHECK target={args.target} findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
