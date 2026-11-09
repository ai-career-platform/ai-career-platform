#!/usr/bin/env python3
"""T147 synthetic data factory for development / QA / CI databases.

Generates deterministic, fully synthetic rows for the T05 data dictionary
(database/DATA_DICTIONARY.md) and writes:
  * an idempotent SQL file (INSERT ... ON CONFLICT DO NOTHING) for a disposable database
  * an optional JSONL file of AI/ML feature rows (no personal data)

Same --seed and sizes  ->  byte-identical output.  Standard library only.

Environment isolation (refuses to produce anything otherwise):
  * --target-env must be one of local / ci / test
  * the CAREER_ENV environment variable must not say staging / production
  * the SQL starts with a guard that aborts unless current_database() looks disposable
    (name contains test, ci, local, tmp or dev) and is not a staging/production name

Usage:
  python3 database/fixtures/synth_factory.py --target-env local --seed 147 \
      --users 200 --companies 30 --postings 300 --out-sql /tmp/synth.sql --out-features /tmp/features.jsonl

This is NOT a migration and must never be applied to Staging (T12 gate).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import uuid
from dataclasses import dataclass, field

FACTORY_VERSION = "t147.2"
NAMESPACE = uuid.UUID("6f1d3c3e-1470-4b47-9a1d-000000000147")
ALLOWED_ENVS = ("local", "ci", "test")
BLOCKED_ENV_WORDS = ("staging", "stage", "prod", "production", "live")
EMAIL_DOMAIN = "example.test"          # RFC 2606 reserved TLD
URL_DOMAIN = "example.test"
SOURCE_CODE = "synthetic_seed"         # T05 C05 (shared with the T10 seed, inserted if missing)
FIXED_TS = "2026-11-06 00:00:00+00"

LIMITS = {"users": (1, 5000), "companies": (1, 1000), "postings": (0, 20000)}

# small synthetic catalog, prefixed SYN_ so it never collides with T10 reference codes
ROLE_NAMES = [
    "백엔드", "프론트엔드", "데이터 엔지니어", "데이터 분석", "머신러닝", "DevOps",
    "보안", "QA", "모바일", "프로덕트 매니저", "디자인", "클라우드",
]
SKILL_NAMES = [
    "Python", "Java", "Kotlin", "TypeScript", "React", "Vue", "Spring", "FastAPI",
    "PostgreSQL", "MySQL", "Redis", "Kafka", "Spark", "Airflow", "Docker", "Kubernetes",
    "AWS", "GCP", "Terraform", "Linux", "Git", "pytest", "Playwright", "Figma",
    "SQL", "pandas", "PyTorch", "scikit-learn", "LLM", "RAG",
]
EMPLOYMENT = ["full_time", "full_time", "full_time", "contract", "intern", "part_time"]
LOCATIONS = ["서울", "경기", "인천", "부산", "대구", "대전", "광주", "원격"]

# patterns that must never appear in generated data (real-looking personal data)
SENSITIVE_PATTERNS = {
    "foreign_email": re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.test\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone_kr": re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"),
    "resident_id": re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
    "card_number": re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
}


class FactoryError(Exception):
    """Raised for refused environments, bad sizes or invalid generated data."""


def sid(seed: int, kind: str, n: int | str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{seed}:{kind}:{n}"))


@dataclass
class Dataset:
    seed: int
    tables: dict[str, list[dict]] = field(default_factory=dict)
    features: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------ guards
def check_environment(target_env: str, environ: dict | None = None) -> None:
    environ = os.environ if environ is None else environ
    if target_env not in ALLOWED_ENVS:
        raise FactoryError(f"target env '{target_env}' refused; allowed: {', '.join(ALLOWED_ENVS)}")
    career_env = environ.get("CAREER_ENV", "").lower()
    if any(word in career_env for word in BLOCKED_ENV_WORDS):
        raise FactoryError(f"CAREER_ENV='{career_env}' looks like a shared environment; refused")


def check_sizes(users: int, companies: int, postings: int) -> None:
    for name, value in (("users", users), ("companies", companies), ("postings", postings)):
        low, high = LIMITS[name]
        if not low <= value <= high:
            raise FactoryError(f"{name}={value} out of range {low}..{high}")


# ------------------------------------------------------------------ generation
def generate(seed: int, users: int, companies: int, postings: int) -> Dataset:
    check_sizes(users, companies, postings)
    rng = random.Random(seed)
    ds = Dataset(seed=seed)
    t = ds.tables

    # Codes are shared across datasets, so their IDs and relationships must also
    # be shared. Keep the original seed-147 catalog for existing test databases.
    catalog_rng = random.Random(147)
    roles = [{"job_role_id": sid(147, "role", i), "code": f"SYN_ROLE_{i:02d}",
              "name": f"합성 직무 {i:02d} ({ROLE_NAMES[i - 1]})"} for i in range(1, len(ROLE_NAMES) + 1)]
    skills = [{"skill_id": sid(147, "skill", i), "code": f"SYN_SKILL_{i:03d}",
               "name": f"합성 기술 {i:03d} ({SKILL_NAMES[i - 1]})"} for i in range(1, len(SKILL_NAMES) + 1)]
    t["job_roles"], t["skills"] = roles, skills

    role_skills = []
    for r in roles:
        for level, s in zip((5, 4, 3, 2, 1), catalog_rng.sample(skills, 5)):
            role_skills.append({"job_role_id": r["job_role_id"], "skill_id": s["skill_id"], "required_level": level})
    t["job_role_skills"] = role_skills

    t["companies"] = [{"company_id": sid(seed, "company", i),
                       "name": f"합성기업 {seed}-{i:04d}",
                       "website_url": f"https://c{i:04d}.s{seed}.{URL_DOMAIN}",
                       "description": "T147 합성 기업. 실제 기업과 무관합니다."}
                      for i in range(1, companies + 1)]

    t["users"] = []
    t["user_profiles"] = []
    for i in range(1, users + 1):
        email = f"synth-{seed}-{i:05d}@{EMAIL_DOMAIN}"
        status = "disabled" if rng.random() < 0.05 else "active"
        t["users"].append({"user_id": sid(seed, "user", i), "email": email, "email_canonical": email,
                           "display_name": f"합성사용자 {seed}-{i:05d}", "status": status})
        if status == "active":
            t["user_profiles"].append({"user_id": sid(seed, "user", i),
                                       "headline": f"{rng.choice(roles)['name']} 지망 (합성)",
                                       "location_text": rng.choice(LOCATIONS)})

    role_skill_map: dict[str, list[dict]] = {}
    for rs in role_skills:
        role_skill_map.setdefault(rs["job_role_id"], []).append(rs)

    t["user_skills"] = []
    t["user_target_roles_hint"] = []   # not a table: kept for AI features only
    for u in t["users"]:
        target = rng.choice(roles)
        t["user_target_roles_hint"].append({"user_id": u["user_id"], "job_role_id": target["job_role_id"]})
        for rs in rng.sample(role_skill_map[target["job_role_id"]], 3):
            t["user_skills"].append({"user_id": u["user_id"], "skill_id": rs["skill_id"],
                                     "proficiency": rng.randint(1, 5)})

    t["job_postings"] = []
    t["job_posting_skills"] = []
    for i in range(1, postings + 1):
        role = rng.choice(roles)
        status = rng.choices(["published", "draft", "closed"], weights=[8, 1, 1])[0]
        day = rng.randint(0, 60)
        posting_id = sid(seed, "posting", i)
        t["job_postings"].append({
            "job_posting_id": posting_id,
            "company_id": rng.choice(t["companies"])["company_id"],
            "job_role_id": role["job_role_id"],
            "title": f"[합성] {role['name']} 채용 {seed}-{i:05d}",
            "description": "T147 합성 공고. 실제 공고와 무관합니다.",
            "employment_type": rng.choice(EMPLOYMENT),
            "location_text": rng.choice(LOCATIONS),
            "status": status,
            "published_day": None if status == "draft" else day,
        })
        for rs in sorted(role_skill_map[role["job_role_id"]], key=lambda x: -x["required_level"])[:4]:
            t["job_posting_skills"].append({"job_posting_id": posting_id, "skill_id": rs["skill_id"],
                                            "is_required": rs["required_level"] >= 4,
                                            "required_level": rs["required_level"]})

    published_ids = [p["job_posting_id"] for p in t["job_postings"] if p["status"] == "published"]
    t["user_job_bookmarks"] = []
    for u in t["users"]:
        if u["status"] != "active" or not published_ids:
            continue
        for pid in rng.sample(published_ids, min(len(published_ids), rng.randint(0, 3))):
            t["user_job_bookmarks"].append({"user_id": u["user_id"], "job_posting_id": pid})

    skill_code = {s["skill_id"]: s["code"] for s in skills}
    role_code = {r["job_role_id"]: r["code"] for r in roles}
    by_user: dict[str, dict] = {}
    for us in t["user_skills"]:
        by_user.setdefault(us["user_id"], {})[skill_code[us["skill_id"]]] = us["proficiency"]
    for hint in t["user_target_roles_hint"]:
        ds.features.append({"entity_id": hint["user_id"], "target_role": role_code[hint["job_role_id"]],
                            "skills": dict(sorted(by_user.get(hint["user_id"], {}).items())),
                            "dataset_version": f"{FACTORY_VERSION}:seed{seed}", "source": SOURCE_CODE})
    del t["user_target_roles_hint"]
    validate(ds)
    return ds


# ------------------------------------------------------------------ validation (same rules as T05 DDL)
def validate(ds: Dataset) -> None:
    t = ds.tables
    problems: list[str] = []

    def unique(table: str, keys: tuple[str, ...]) -> None:
        seen = set()
        for row in t[table]:
            k = tuple(row[c] for c in keys)
            if k in seen:
                problems.append(f"duplicate {table}{keys}={k}")
            seen.add(k)

    def fk(table: str, col: str, parent: str, pcol: str, nullable: bool = False) -> None:
        ids = {r[pcol] for r in t[parent]}
        for row in t[table]:
            v = row[col]
            if v is None and nullable:
                continue
            if v not in ids:
                problems.append(f"orphan {table}.{col}={v}")

    for table, keys in {"job_roles": ("code",), "skills": ("code",), "users": ("email_canonical",),
                        "companies": ("company_id",), "job_postings": ("job_posting_id",),
                        "job_role_skills": ("job_role_id", "skill_id"), "user_skills": ("user_id", "skill_id"),
                        "job_posting_skills": ("job_posting_id", "skill_id"),
                        "user_job_bookmarks": ("user_id", "job_posting_id")}.items():
        unique(table, keys)
    fk("job_role_skills", "job_role_id", "job_roles", "job_role_id")
    fk("job_role_skills", "skill_id", "skills", "skill_id")
    fk("user_profiles", "user_id", "users", "user_id")
    fk("user_skills", "user_id", "users", "user_id")
    fk("user_skills", "skill_id", "skills", "skill_id")
    fk("job_postings", "company_id", "companies", "company_id")
    fk("job_postings", "job_role_id", "job_roles", "job_role_id", nullable=True)
    fk("job_posting_skills", "job_posting_id", "job_postings", "job_posting_id")
    fk("job_posting_skills", "skill_id", "skills", "skill_id")
    fk("user_job_bookmarks", "user_id", "users", "user_id")
    fk("user_job_bookmarks", "job_posting_id", "job_postings", "job_posting_id")

    for u in t["users"]:
        if u["status"] not in ("active", "disabled"):
            problems.append(f"bad users.status {u['status']}")
        if u["email_canonical"] != u["email"].lower() or "+" in u["email_canonical"].split("@")[0]:
            problems.append(f"non-canonical email {u['email_canonical']}")
    for rs in t["job_role_skills"]:
        if not 1 <= rs["required_level"] <= 5:
            problems.append("required_level out of range")
    for us in t["user_skills"]:
        if not 1 <= us["proficiency"] <= 5:
            problems.append("proficiency out of range")
    for p in t["job_postings"]:
        if p["status"] not in ("draft", "published", "closed"):
            problems.append(f"bad posting status {p['status']}")
        if p["status"] == "published" and p["published_day"] is None:
            problems.append("published posting without published_at")
        if p["employment_type"] not in ("full_time", "contract", "intern", "part_time"):
            problems.append("bad employment_type")

    problems.extend(scan_sensitive(ds))
    if problems:
        raise FactoryError("invalid synthetic data: " + "; ".join(problems[:10]))


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def scan_sensitive(ds: Dataset) -> list[str]:
    found = []
    blob = json.dumps(ds.tables, ensure_ascii=False) + json.dumps(ds.features, ensure_ascii=False)
    blob = UUID_RE.sub("<uuid>", blob)   # digit runs inside ids are not card / phone numbers
    for name, pattern in SENSITIVE_PATTERNS.items():
        m = pattern.search(blob)
        if m:
            found.append(f"sensitive pattern {name}: {m.group(0)[:40]}")
    return found


# ------------------------------------------------------------------ rendering
def q(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(ds: Dataset) -> str:
    t = ds.tables
    ts = f"timestamptz '{FIXED_TS}'"
    src = f"(SELECT source_id FROM career.data_sources WHERE code = {q(SOURCE_CODE)})"
    out = [
        f"-- T147 synthetic data factory {FACTORY_VERSION}, seed={ds.seed}. DISPOSABLE DATABASES ONLY.",
        "-- Generated file: do not edit. Re-running is safe (ON CONFLICT DO NOTHING).",
        "SET client_encoding = 'UTF8';",
        "DO $$",
        "BEGIN",
        "    IF current_database() !~* '(test|ci|local|tmp|dev)' OR current_database() ~* '(staging|stage|prod|live)' THEN",
        "        RAISE EXCEPTION 'T147 factory refused: database % is not a disposable dev/test database', current_database();",
        "    END IF;",
        "END $$;",
        "BEGIN;",
        # same deterministic id as the T10 seed, so either can be applied first; rows refer to it by code
        f"INSERT INTO career.data_sources (source_id, code, name) VALUES (md5('seed:data_source:{SOURCE_CODE}')::uuid, "
        f"{q(SOURCE_CODE)}, '합성 Seed 데이터') ON CONFLICT (code) DO NOTHING;",
    ]

    def block(table: str, cols: list[str], rows: list[list[str]], conflict: str) -> None:
        if not rows:
            return
        out.append(f"INSERT INTO career.{table} ({', '.join(cols)}) VALUES")
        out.append(",\n".join("    (" + ", ".join(r) + ")" for r in rows))
        out.append(f"ON CONFLICT {conflict} DO NOTHING;")

    block("job_roles", ["job_role_id", "code", "name", "created_at", "updated_at"],
          [[q(r["job_role_id"]), q(r["code"]), q(r["name"]), ts, ts] for r in t["job_roles"]], "(code)")
    block("skills", ["skill_id", "code", "name", "created_at", "updated_at"],
          [[q(s["skill_id"]), q(s["code"]), q(s["name"]), ts, ts] for s in t["skills"]], "(code)")
    block("companies", ["company_id", "name", "website_url", "description", "source_id", "created_at", "updated_at"],
          [[q(c["company_id"]), q(c["name"]), q(c["website_url"]), q(c["description"]), src, ts, ts]
           for c in t["companies"]], "(company_id)")
    block("users", ["user_id", "email", "email_canonical", "display_name", "status", "created_at", "updated_at"],
          [[q(u["user_id"]), q(u["email"]), q(u["email_canonical"]), q(u["display_name"]), q(u["status"]), ts, ts]
           for u in t["users"]], "(email_canonical)")
    block("job_role_skills", ["job_role_id", "skill_id", "required_level", "created_at"],
          [[q(r["job_role_id"]), q(r["skill_id"]), q(r["required_level"]), ts] for r in t["job_role_skills"]],
          "(job_role_id, skill_id)")
    block("user_profiles", ["user_id", "headline", "location_text", "created_at", "updated_at"],
          [[q(p["user_id"]), q(p["headline"]), q(p["location_text"]), ts, ts] for p in t["user_profiles"]],
          "(user_id)")
    posting_rows = []
    for p in t["job_postings"]:
        pub = "NULL" if p["published_day"] is None else f"{ts} - interval '66 days' + interval '{p['published_day']} days'"
        exp = "NULL" if p["published_day"] is None else f"{ts} - interval '66 days' + interval '{p['published_day'] + 45} days'"
        posting_rows.append([q(p["job_posting_id"]), q(p["company_id"]), q(p["job_role_id"]), src, q(p["title"]),
                             q(p["description"]), q(p["employment_type"]), q(p["location_text"]), q(p["status"]),
                             pub, exp, ts, ts])
    block("job_postings", ["job_posting_id", "company_id", "job_role_id", "source_id", "title", "description",
                           "employment_type", "location_text", "status", "published_at", "expires_at",
                           "created_at", "updated_at"], posting_rows, "(job_posting_id)")
    block("job_posting_skills", ["job_posting_id", "skill_id", "is_required", "required_level", "created_at"],
          [[q(r["job_posting_id"]), q(r["skill_id"]), q(r["is_required"]), q(r["required_level"]), ts]
           for r in t["job_posting_skills"]], "(job_posting_id, skill_id)")
    block("user_skills", ["user_id", "skill_id", "proficiency", "created_at", "updated_at"],
          [[q(r["user_id"]), q(r["skill_id"]), q(r["proficiency"]), ts, ts] for r in t["user_skills"]],
          "(user_id, skill_id)")
    block("user_job_bookmarks", ["user_id", "job_posting_id", "created_at"],
          [[q(r["user_id"]), q(r["job_posting_id"]), ts] for r in t["user_job_bookmarks"]],
          "(user_id, job_posting_id)")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


def render_features(ds: Dataset) -> str:
    return "".join(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in ds.features)


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def counts(ds: Dataset) -> dict[str, int]:
    return {k: len(v) for k, v in ds.tables.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target-env", required=True, help="local | ci | test")
    ap.add_argument("--seed", type=int, default=147)
    ap.add_argument("--users", type=int, default=200)
    ap.add_argument("--companies", type=int, default=30)
    ap.add_argument("--postings", type=int, default=300)
    ap.add_argument("--out-sql", required=True)
    ap.add_argument("--out-features")
    args = ap.parse_args(argv)
    try:
        check_environment(args.target_env)
        ds = generate(args.seed, args.users, args.companies, args.postings)
    except FactoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    sql = render_sql(ds)
    with open(args.out_sql, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sql)
    if args.out_features:
        with open(args.out_features, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_features(ds))
    print(f"T147_FACTORY seed={args.seed} sha256={fingerprint(sql)[:16]} counts={json.dumps(counts(ds), sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
