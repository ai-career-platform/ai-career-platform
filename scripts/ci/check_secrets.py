#!/usr/bin/env python3
"""비밀정보 패턴 검사기 (T28 PR 게이트, 표준 라이브러리만, 네트워크 없음).

git 추적/미추적(무시 제외) 텍스트 파일에서 고신뢰 토큰 패턴과
`password=...` 형태의 하드코딩 값을 찾습니다. 발견 값은 출력 시 마스킹합니다.

한계: 정규식 기반이므로 알려진 형식만 탐지합니다(엔트로피 분석·git 이력 검사 없음).
허용: CHANGE_ME/<...>/xxxx 표기, test·dummy·example 등 자리표시자 단어(단어 단위 일치), `${VAR}` 참조,
      줄 끝의 `secret-scan: allow` 주석(리뷰어 승인 필요).
종료 코드: 0 = 발견 없음, 1 = 발견 있음.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import repo_files  # noqa: E402

MAX_BYTES = 2_000_000
ALLOW_MARKER = "secret-scan: allow"

# (규칙 이름, 정규식, 값 그룹 번호). 값 그룹은 마스킹/자리표시자 판단에 사용합니다.
TOKEN_RULES: list[tuple[str, re.Pattern[str], int]] = [
    (
        "aws-access-key-id",
        re.compile(r"\b((?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16})\b"),
        1,
    ),
    (
        "private-key",
        re.compile(r"(-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)"),
        1,
    ),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"), 1),
    ("github-fine-grained-pat", re.compile(r"\b(github_pat_[A-Za-z0-9_]{50,})\b"), 1),
    ("slack-token", re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})\b"), 1),
    ("google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b"), 1),
    ("openai-style-key", re.compile(r"\b(sk-(?:proj-)?[A-Za-z0-9_-]{32,})\b"), 1),
]

KEY_WORDS = (
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
)
ASSIGN_RULES: list[tuple[str, re.Pattern[str], int]] = [
    # password = "value" / "password": "value" / password: 'value'
    (
        "hardcoded-credential",
        re.compile(
            r"(?i)[\w.-]*"
            + KEY_WORDS
            + r"[\w-]*[\"']?\s*[:=]\s*([\"'])([^\"'\s]{8,})\1"
        ),
        2,
    ),
    # .env / shell: DB_PASSWORD=value, export TOKEN=value, -e POSTGRES_PASSWORD=value
    (
        "hardcoded-credential-env",
        re.compile(
            r"(?:^|[\s;])(?:export\s+|-e\s+)?[A-Z0-9_]*"
            r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|ACCESS_KEY)[A-Z0-9_]*"
            r"=([^\s\"'$#;]{8,})"
        ),
        1,
    ),
    # 접속 문자열 안의 자격증명: postgresql://user:pass@host/db
    (
        "credential-in-url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s:/@]{6,})@"),
        1,
    ),
]

# 설정 파일에서만 쓰는 규칙: 따옴표 없는 값 (password: value, db_password=value).
# 코드(password=os.environ[...])는 오탐이 많아 YAML/.env/INI/TOML 등 설정 파일에만 적용합니다.
CONFIG_SUFFIXES = frozenset(
    {".yml", ".yaml", ".env", ".ini", ".cfg", ".conf", ".toml", ".properties"}
)
CONFIG_RULES: list[tuple[str, re.Pattern[str], int]] = [
    (
        "hardcoded-credential-unquoted",
        re.compile(
            r"(?i)^\s*-?\s*[\w.-]*"
            + KEY_WORDS
            + r"[\w-]*\s*[:=]\s*([^\s\"'#|>&*!\[\]][^\s#]{7,})\s*$"
        ),
        1,
    ),
]


# 문서(docs/) 아래 설정 형식 파일은 API 명세 예시값(OpenAPI example 등)이 많아
# 따옴표 없는 값 규칙을 적용하지 않습니다. 토큰 형식·따옴표 값·URL 규칙은 계속 적용됩니다.
DOC_DIRS = ("docs/",)


def is_config_file(name: str) -> bool:
    low = name.lower().replace("\\", "/")
    if low.startswith(DOC_DIRS):
        return False
    base = low.rsplit("/", 1)[-1]
    return Path(base).suffix in CONFIG_SUFFIXES or base.startswith(".env")


# 자리표시자 판단.
# - MARKERS: 값 안에 부분 문자열로 있으면 허용 (명시적 자리표시자 표기).
# - WORDS: 값을 영숫자 단어로 나눴을 때 단어가 정확히 일치하면 허용.
#   ("MyLatestPw2026"처럼 단어 안에 test가 섞인 실제 값은 허용하지 않습니다.)
# "{" 포함 값은 템플릿·f-string·${VAR} 참조로 보고 허용합니다.
PLACEHOLDER_MARKERS = (
    "change_me",
    "changeme",
    "change-me",
    "your_",
    "your-",
    "xxxx",
    "${",
    "{{",
    "<",
    "...",
    "***",
)
PLACEHOLDER_WORDS = frozenset(
    {
        "placeholder",
        "example",
        "sample",
        "dummy",
        "fake",
        "fixture",
        "mock",
        "test",
        "disposable",
        "redacted",
        "changeme",
    }
)
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def is_placeholder(value: str) -> bool:
    low = value.lower()
    if any(m in low for m in PLACEHOLDER_MARKERS):
        return True
    if value.startswith("{") and value.endswith("}"):
        return True  # f-string / 템플릿 전체 치환
    if any(w in PLACEHOLDER_WORDS for w in _WORD_SPLIT.split(low) if w):
        return True
    return len(set(low)) <= 2  # aaaaaaaa, 00000000 등


def mask(value: str) -> str:
    return value[:4] + "*" * max(4, len(value) - 4) if len(value) > 4 else "****"


def scan_text(text: str, name: str = "") -> list[tuple[int, str, str]]:
    """(줄 번호, 규칙, 마스킹된 값) 목록. name은 저장소 기준 상대 경로(설정 파일 규칙 판단용)."""
    assign_rules = ASSIGN_RULES + (CONFIG_RULES if is_config_file(name) else [])
    findings: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        for rule, rx, grp in TOKEN_RULES:
            for m in rx.finditer(line):
                findings.append((lineno, rule, mask(m.group(grp))))
        for rule, rx, grp in assign_rules:
            for m in rx.finditer(line):
                value = m.group(grp)
                if not is_placeholder(value):
                    findings.append((lineno, rule, mask(value)))
    return findings


def scan_files(root: Path, files: list[Path]) -> tuple[int, list[str]]:
    root = root.resolve()
    results: list[str] = []
    scanned = 0
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if len(data) > MAX_BYTES or b"\0" in data[:8192]:
            continue  # 대용량/바이너리 제외
        scanned += 1
        text = data.decode("utf-8", errors="replace")
        rel = f.resolve().relative_to(root).as_posix()
        for lineno, rule, masked in scan_text(text, rel):
            results.append(f"{rel}:{lineno}: {rule} {masked}")
    return scanned, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="저장소 루트 (기본: 현재 폴더)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    scanned, results = scan_files(root, repo_files(root.resolve()))
    for item in results:
        print(f"SECRET_FINDING {item}")
    print(f"scanned_files={scanned} findings={len(results)}")
    if results:
        print(
            "SECRET_PATTERN_SCAN=FAIL (값을 제거하고, 이미 push했다면 즉시 폐기·교체)"
        )
        return 1
    print("SECRET_PATTERN_SCAN=PASS (known patterns only; not a full secret scanner)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
