#!/usr/bin/env python3
"""T114 DB 백업·복원 검증 도구 — 정기 백업 manifest, 격리 복원 검증, 보존 계획, 신선도 경보.

명령
    backup          pg_dump -Fc → <out-dir>/<label>_<db>_<UTC>.dump + .manifest.json (sha256·목차·지문)
    verify          manifest 의 sha256·목차 확인 → loopback 일회용 DB(t114_verify_*)에 복원 → 지문 비교 → DB 삭제
    retention-plan  보존 규칙(일·주·월)으로 남길 것/만료할 것을 **계산만** 한다(삭제하지 않음)
    freshness       가장 최근 검증 통과 백업이 RPO 보다 오래됐으면 경보(exit 2)

안전 장치
- 접속 대상은 loopback(127.0.0.1/localhost/::1)만. 원격 호스트는 거부한다.
- 이름이 `t114_` 로 시작하지 않는 DB 를 백업하려면 `--approval <승인 기록>` 이 필요하고, manifest 에 남는다.
  (Staging 실제 백업은 이 PR 범위 밖 — HOLD)
- 복원은 항상 새로 만든 `t114_verify_*` DB 에만 한다. 기존 DB·볼륨에 덮어쓰지 않는다.
- 이 도구는 파일을 지우지 않는다. 보존 만료는 계획만 출력한다. 업로드 기능 없음.
- 암호화: 저장소에 암호화 라이브러리가 없어 **미구현(PROPOSED: age/gpg 로 manifest 와 함께 암호화)**.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FORMAT = "t114-backup-manifest/1"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
VERIFY_PREFIX = "t114_verify_"

_drill_spec = importlib.util.spec_from_file_location("t90_drill", ROOT / "database" / "tests" / "t90_backup_restore_drill.py")
t90 = importlib.util.module_from_spec(_drill_spec)
_drill_spec.loader.exec_module(t90)  # fingerprint(), seed_source() 재사용


class Refused(Exception):
    """안전 규칙 위반 — 아무것도 하지 않고 중단."""


class VerifyFailed(Exception):
    pass


def conn_options(url: str) -> dict:
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(url)
    if options.get("host") not in LOOPBACK:
        raise Refused("loopback disposable/approved cluster only")
    return options


def tool(name: str) -> str:
    pg_bin = os.environ.get("PG_BIN", "")
    return str(Path(pg_bin) / name) if pg_bin else name


def pg_env(options: dict) -> dict:
    env = {**os.environ, "PGHOST": options["host"], "PGPORT": str(options.get("port", 5432))}
    if options.get("user"):
        env["PGUSER"] = options["user"]
    return env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def toc_entries(dump: Path) -> int:
    listing = subprocess.run([tool("pg_restore"), "--list", str(dump)], capture_output=True, text=True)
    if listing.returncode != 0:
        raise VerifyFailed("archive table of contents unreadable")
    return sum(1 for line in listing.stdout.splitlines() if line and not line.startswith(";"))


def applied_migrations(conn) -> list[str]:
    exists = conn.execute("SELECT to_regclass('career_migration.schema_migrations') IS NOT NULL").fetchone()[0]
    if not exists:
        return []
    return [r[0] for r in conn.execute("SELECT version FROM career_migration.schema_migrations ORDER BY version")]


# ---------------------------------------------------------------- backup
def backup(admin_url: str, db: str, out_dir: Path, label: str, approval: str | None = None,
           now: datetime | None = None) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    options = conn_options(admin_url)
    if not db.startswith("t114_") and not (approval or "").strip():
        raise Refused("backing up a non-drill database requires --approval")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = out_dir / f"{label}_{db}_{stamp}.dump"
    with psycopg.connect(make_conninfo(admin_url, dbname=db), autocommit=True) as conn:
        before = t90.fingerprint(conn)
        migrations = applied_migrations(conn)
        server_version = conn.execute("SHOW server_version").fetchone()[0]
    started = time.perf_counter()
    subprocess.run([tool("pg_dump"), "-Fc", "--no-owner", "--no-privileges", "-d", db, "-f", str(dump)],
                   check=True, env=pg_env(options), capture_output=True)
    manifest = {
        "format": MANIFEST_FORMAT,
        "label": label,
        "database": db,
        "created_at": (now or datetime.now(UTC)).isoformat(),
        "server_version": server_version,
        "pg_dump_version": subprocess.run([tool("pg_dump"), "--version"], capture_output=True, text=True).stdout.strip(),
        "file": dump.name,
        "bytes": dump.stat().st_size,
        "sha256": sha256_file(dump),
        "dump_seconds": round(time.perf_counter() - started, 3),
        "toc_entries": toc_entries(dump),
        "migrations": migrations,
        "fingerprint": before,
        "approval": (approval or "").strip() or None,
        "encrypted": False,
    }
    manifest_path(dump).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def manifest_path(dump: Path) -> Path:
    return dump.with_suffix(".manifest.json")


# ---------------------------------------------------------------- verify
def verify(admin_url: str, manifest_file: Path) -> dict:
    import psycopg
    from psycopg.conninfo import make_conninfo

    options = conn_options(admin_url)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise VerifyFailed("unknown manifest format")
    dump = manifest_file.parent / manifest["file"]
    if not dump.exists():
        raise VerifyFailed("dump file missing")
    if sha256_file(dump) != manifest["sha256"]:
        raise VerifyFailed("sha256 mismatch")
    if toc_entries(dump) != manifest["toc_entries"]:
        raise VerifyFailed("table of contents differs from manifest")
    target = VERIFY_PREFIX + secrets.token_hex(4)
    result: dict = {"manifest": manifest_file.name, "target": target, "verdict": "FAIL"}
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{target}"')
    try:
        started = time.perf_counter()
        restored = subprocess.run([tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error",
                                   "-d", target, str(dump)], env=pg_env(options), capture_output=True, text=True)
        result["restore_seconds"] = round(time.perf_counter() - started, 3)
        if restored.returncode != 0:
            raise VerifyFailed("pg_restore failed")
        with psycopg.connect(make_conninfo(admin_url, dbname=target), autocommit=True) as conn:
            after = t90.fingerprint(conn)
            result["migrations"] = applied_migrations(conn)
        expected = manifest["fingerprint"]
        mismatched = sorted(t for t in expected["tables"] if expected["tables"][t] != after["tables"].get(t))
        extra = sorted(set(after["tables"]) - set(expected["tables"]))
        result.update({
            "tables": len(after["tables"]),
            "rows": sum(v["rows"] for v in after["tables"].values()),
            "table_mismatches": mismatched,
            "unexpected_tables": extra,
            "objects_equal": after["objects"] == expected["objects"],
            "migrations_equal": result["migrations"] == manifest["migrations"],
        })
        ok = not mismatched and not extra and result["objects_equal"] and result["migrations_equal"]
        result["verdict"] = "PASS" if ok else "FAIL"
        if not ok:
            raise VerifyFailed("restored content differs from manifest fingerprint")
        return result
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')


# ---------------------------------------------------------------- retention / freshness (계산만)
@dataclass(frozen=True)
class BackupRef:
    name: str
    created_at: datetime


def load_refs(directory: Path) -> list[BackupRef]:
    refs = []
    for path in sorted(directory.glob("*.manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") == MANIFEST_FORMAT:
            refs.append(BackupRef(data["file"], datetime.fromisoformat(data["created_at"])))
    return refs


def retention_plan(refs: list[BackupRef], now: datetime, daily: int = 7, weekly: int = 4,
                   monthly: int = 3) -> dict[str, list[str]]:
    """일 단위 최근 N일, 주 단위 최근 N주, 월 단위 최근 N개월의 '그 구간 가장 최근 백업'을 남긴다."""
    keep: set[str] = set()
    newest_first = sorted(refs, key=lambda r: r.created_at, reverse=True)

    def pick(key, limit):
        seen: list = []
        for ref in newest_first:
            k = key(ref.created_at)
            if k not in seen:
                seen.append(k)
                if len(seen) > limit:
                    break
                keep.add(ref.name)

    future = [r.name for r in refs if r.created_at > now + timedelta(minutes=5)]
    pick(lambda t: t.date(), daily)
    pick(lambda t: tuple(t.isocalendar())[:2], weekly)
    pick(lambda t: (t.year, t.month), monthly)
    keep.update(future)  # 시계가 어긋난 백업은 지우지 않는다(보수적)
    return {"keep": sorted(keep), "expire": sorted(r.name for r in refs if r.name not in keep),
            "clock_skew": sorted(future)}


def freshness(refs: list[BackupRef], now: datetime, rpo_hours: float) -> dict:
    if not refs:
        return {"alert": True, "reason": "no backup", "age_hours": None}
    newest = max(refs, key=lambda r: r.created_at)
    age = (now - newest.created_at).total_seconds() / 3600
    return {"alert": age > rpo_hours, "reason": "older than RPO" if age > rpo_hours else "ok",
            "age_hours": round(age, 2), "newest": newest.name}


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T114 backup/restore verification (loopback only)")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--db", required=True)
    b.add_argument("--out-dir", required=True)
    b.add_argument("--label", default="local")
    b.add_argument("--approval")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    r = sub.add_parser("retention-plan")
    r.add_argument("--dir", required=True)
    r.add_argument("--now")
    f = sub.add_parser("freshness")
    f.add_argument("--dir", required=True)
    f.add_argument("--rpo-hours", type=float, default=24)
    f.add_argument("--now")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.fromisoformat(args.now) if getattr(args, "now", None) else datetime.now(UTC)
    try:
        if args.command == "backup":
            out = backup(os.environ["T114_ADMIN_URL"], args.db, Path(args.out_dir), args.label, args.approval)
            out = {k: v for k, v in out.items() if k != "fingerprint"}
        elif args.command == "verify":
            out = verify(os.environ["T114_ADMIN_URL"], Path(args.manifest))
        elif args.command == "retention-plan":
            out = retention_plan(load_refs(Path(args.dir)), now)
        else:
            out = freshness(load_refs(Path(args.dir)), now, args.rpo_hours)
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    except VerifyFailed as exc:
        print(json.dumps({"verdict": "FAIL", "reason": str(exc)}))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 2 if args.command == "freshness" and out["alert"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
