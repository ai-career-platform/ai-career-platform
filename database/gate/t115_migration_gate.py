#!/usr/bin/env python3
"""T115 DB Migration 안전 게이트 — PR 검사와 Staging 적용 전 사전점검. **migration 을 적용하지 않는다.**

명령
    pr        --base-ref <git ref>       base 대비 migration 변경 검사(CI). 위반 시 exit 1
    preflight --target staging ...      Staging 수동 적용 전 체크리스트(백업 검증·승인·DB 이름·대기 목록). 적용 안 함

PR 규칙 (기존 runner lint 에 더해)
  G1 이미 base 에 있는 migration 파일의 수정·삭제·이름 변경 금지(적용 후 불변)
  G2 새 migration 번호는 base 최대 번호보다 커야 하고, 번호 사이에 빈칸이 없어야 함(병렬 PR 충돌 감지)
  G3 runner lint(이름·필수 헤더·파괴적 SQL 승인·금지 구문) 통과
  G4 실행 중인 앱을 깨는 DDL(컬럼 삭제·이름 변경·형 변경·NOT NULL 추가·기본값 없는 NOT NULL 컬럼 추가)은
     `-- Compatibility: contract <앱 배포 순서 설명>` 헤더 필요(Expand/Contract)
  G5 데이터 변경 DML(UPDATE/DELETE/INSERT … SELECT)은 `-- Data-Impact: <대상·예상 행 수·되돌리는 법>` 헤더 필요
  G6 앱 코드(backend/app)가 DDL 을 실행하지 않음(스키마 변경은 migration 으로만)
  G7 CI·Auto-CD 설정이 migrate.py apply 를 실행하지 않음(자동 배포와 migration 연결 금지)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = "database/migrations"
_spec = importlib.util.spec_from_file_location("migrate", ROOT / "database" / "migrate.py")
migrate = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("migrate", migrate)
_spec.loader.exec_module(migrate)

NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
COMPAT_HEADER = "-- Compatibility:"
DATA_HEADER = "-- Data-Impact:"
BREAKING_DDL = [
    (re.compile(r"\bALTER\s+TABLE\s+\S+\s+DROP\s+COLUMN\b", re.I), "drop column"),
    (re.compile(r"\bRENAME\s+(COLUMN\s+)?\S+\s+TO\b", re.I), "rename column"),
    (re.compile(r"\bALTER\s+TABLE\s+\S+\s+RENAME\s+TO\b", re.I), "rename table"),
    (re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b", re.I), "change column type"),
    (re.compile(r"\bALTER\s+COLUMN\s+\S+\s+SET\s+NOT\s+NULL\b", re.I), "set not null"),
    (re.compile(r"\bADD\s+COLUMN\s+(IF\s+NOT\s+EXISTS\s+)?\S+\s+[^,;]*\bNOT\s+NULL\b(?![^,;]*\bDEFAULT\b)", re.I),
     "add NOT NULL column without default"),
    (re.compile(r"\bDROP\s+TABLE\b", re.I), "drop table"),
]
DML = re.compile(r"^\s*(UPDATE\s+\S+\s+SET|DELETE\s+FROM|INSERT\s+INTO\s+\S+[^;]*\bSELECT\b)", re.I | re.M)
APP_DDL = re.compile(r"""["'](?:\s*)(CREATE|ALTER|DROP)\s+(TABLE|INDEX|SCHEMA|COLUMN|TYPE)\b""", re.I)
AUTO_APPLY = re.compile(r"migrate\.py[^\n]*\bapply\b")
AUTOMATION_GLOBS = [".github/workflows/*.yml", "poc/staging/automation/*.py", "poc/staging/automation/*.yaml",
                    "poc/staging/automation/*.service", "poc/staging/**/Dockerfile*"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def base_files(ref: str) -> dict[str, str]:
    names = [n for n in git("ls-tree", "--name-only", f"{ref}:{MIGRATIONS}").split() if NAME.match(n)]
    return {n: git("show", f"{ref}:{MIGRATIONS}/{n}") for n in names}


def head_files(root: Path = ROOT) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((root / MIGRATIONS).glob("*.sql")) if NAME.match(p.name)}


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def _head(text: str) -> list[str]:
    return text.splitlines()[: migrate.HEADER_LINES]


def _has_header(text: str, header: str) -> bool:
    return any(line.startswith(header) and line[len(header):].strip() for line in _head(text))


def check_files(base: dict[str, str], head: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for name, text in base.items():                                     # G1
        if name not in head:
            problems.append(f"G1 {name}: applied migration removed or renamed")
        elif _norm(head[name]) != _norm(text):
            problems.append(f"G1 {name}: applied migration modified (add a new migration instead)")
    base_max = max((int(NAME.match(n).group(1)) for n in base), default=0)
    new = sorted(n for n in head if n not in base)
    expected = base_max + 1
    versions = [NAME.match(n).group(1) for n in head]
    for version in sorted({v for v in versions if versions.count(v) > 1}):
        problems.append(f"G2 version {version}: duplicate migration number")
    for name in new:                                                     # G2
        number = int(NAME.match(name).group(1))
        if number <= base_max:
            problems.append(f"G2 {name}: number must be greater than base max {base_max:04d} (rebase/renumber)")
        elif number != expected:
            problems.append(f"G2 {name}: expected {expected:04d} (no gaps)")
        expected = max(expected, number) + 1
    for name in new:
        text = head[name]
        body = migrate._strip_comments(text)
        breaking = sorted({label for pattern, label in BREAKING_DDL if pattern.search(body)})
        if breaking and not _has_header(text, COMPAT_HEADER):          # G4
            problems.append(f"G4 {name}: {', '.join(breaking)} needs '{COMPAT_HEADER} contract <deploy order>'")
        if DML.search(body) and not _has_header(text, DATA_HEADER):    # G5
            problems.append(f"G5 {name}: data change needs '{DATA_HEADER} <target, rows, rollback>'")
    return problems


def lint_new(head_root: Path, new: list[str]) -> list[str]:
    problems = []
    for name in new:                                                     # G3
        for problem in migrate.lint_file(head_root / MIGRATIONS / name):
            problems.append(f"G3 {name}: {problem}")
    return problems


def check_app_ddl(root: Path = ROOT) -> list[str]:                      # G6
    out = []
    for path in sorted((root / "backend" / "app").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if APP_DDL.search(line):
                out.append(f"G6 {path.relative_to(root).as_posix()}:{lineno}: application code issues DDL")
    return out


def check_auto_apply(root: Path = ROOT) -> list[str]:                   # G7
    out = []
    for pattern in AUTOMATION_GLOBS:
        for path in sorted(root.glob(pattern)):
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if AUTO_APPLY.search(line) and not line.lstrip().startswith("#"):
                    out.append(f"G7 {path.relative_to(root).as_posix()}:{lineno}: automation runs 'migrate.py apply'")
    return out


def pr_gate(base_ref: str, root: Path = ROOT) -> list[str]:
    base, head = base_files(base_ref), head_files(root)
    new = sorted(n for n in head if n not in base)
    return check_files(base, head) + lint_new(root, new) + check_app_ddl(root) + check_auto_apply(root)


# ---------------------------------------------------------------- Staging 사전점검(적용 안 함)
def preflight(target: str, approval: str | None, confirm_db: str | None, connected_db: str,
              verify_result: dict | None, backup_manifest: dict | None, pending: list[str],
              now: datetime, max_backup_age: timedelta = timedelta(hours=24)) -> dict:
    checks = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("target is staging", target == "staging", target)
    check("approval reference", bool(approval and migrate.APPROVAL_RE.match(approval)), approval or "missing")
    check("confirm-db equals connected database", confirm_db == connected_db, f"{confirm_db} vs {connected_db}")
    check("pending migrations listed", bool(pending), ",".join(pending) or "none")
    created = datetime.fromisoformat(backup_manifest["created_at"]) if backup_manifest else None
    check("backup taken within 24h", bool(created and now - created <= max_backup_age),
          created.isoformat() if created else "no manifest")
    check("backup restore verified (T114 verify PASS)",
          bool(verify_result and verify_result.get("verdict") == "PASS"
               and backup_manifest and verify_result.get("manifest", "").startswith(backup_manifest["file"].rsplit(".", 1)[0])),
          (verify_result or {}).get("verdict", "missing"))
    check("not running in CI", True, "checked by migrate.py guard_target at apply time")
    return {"ready": all(c["ok"] for c in checks), "checks": checks,
            "next": "사람이 migrate.py apply --target staging --approval … --confirm-db … 실행" if all(
                c["ok"] for c in checks) else "중단: 실패 항목 해결"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T115 migration safety gate (never applies migrations)")
    sub = parser.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("pr")
    pr.add_argument("--base-ref", default="origin/main")
    pf = sub.add_parser("preflight")
    pf.add_argument("--target", required=True)
    pf.add_argument("--approval")
    pf.add_argument("--confirm-db")
    pf.add_argument("--connected-db", required=True)
    pf.add_argument("--verify-result")
    pf.add_argument("--backup-manifest")
    pf.add_argument("--pending", default="")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "pr":
        problems = pr_gate(args.base_ref)
        for p in problems:
            print(f"FAIL {p}")
        print(f"T115_GATE problems={len(problems)}")
        return 1 if problems else 0
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if p else None  # noqa: E731
    result = preflight(args.target, args.approval, args.confirm_db, args.connected_db, load(args.verify_result),
                       load(args.backup_manifest), [v for v in args.pending.split(",") if v], datetime.now(UTC))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
