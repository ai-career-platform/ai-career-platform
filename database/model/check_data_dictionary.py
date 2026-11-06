#!/usr/bin/env python3
"""T05 data dictionary checker.

Reads database/DATA_DICTIONARY.md (the source of truth), validates it, and can
render the full ERD (database/ERD.md) or a *validation-only* DDL script.

The DDL is for disposable databases only (CI / local throwaway PostgreSQL).
It is NOT a migration and must never be applied to Staging (see T08/T09/T12).

Usage:
    python3 database/model/check_data_dictionary.py            # validate only
    python3 database/model/check_data_dictionary.py --ddl      # print DDL to stdout
    python3 database/model/check_data_dictionary.py --write-erd  # regenerate database/ERD.md
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = ROOT / "database" / "DATA_DICTIONARY.md"
ERD_FILE = ROOT / "database" / "ERD.md"

REQUIREMENTS_DIR = ROOT / "docs" / "requirements"
# Requirements that store no data of their own. Every other functional requirement
# in docs/requirements must map to at least one table. Requirements change over time:
# coverage is re-checked against whatever is in docs/requirements on each run.
NO_DATA_REQUIREMENTS = {
    "FR-CMN-004": "공통 상태 화면 (로딩·오류·권한 없음). 저장할 데이터 없음",
}
DELETE_ACTIONS = {"RESTRICT", "CASCADE", "SET NULL"}
SOFT_DELETE_CATALOGS = {"skills", "job_roles", "model_versions"}
GRADES = {"PUBLIC", "INTERNAL", "PERSONAL", "SENSITIVE"}

HEADER_RE = re.compile(r"^### ([A-F]\d{2}) `([a-z_]+)`")
FK_RE = re.compile(r"FK → ([a-z_]+)\.([a-z_]+) \((RESTRICT|CASCADE|SET NULL)\)")
REQ_RE = re.compile(r"\bN?FR-[A-Z]+-\d{3}\b")


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: str
    keys: str
    fk: tuple[str, str, str] | None = None


@dataclass
class Table:
    code: str
    name: str
    features: set[str] = field(default_factory=set)
    grade: str = ""
    columns: list[Column] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)

    @property
    def pk(self) -> list[str]:
        return [c.name for c in self.columns if re.search(r"(^|;\s*)PK\b", c.keys)]


def parse(text: str) -> list[Table]:
    tables: list[Table] = []
    current: Table | None = None
    section = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = HEADER_RE.match(line)
        if m:
            current = Table(code=m.group(1), name=m.group(2))
            tables.append(current)
            section = None
            continue
        if current is None:
            continue
        if line.startswith("## "):
            current = None
            continue
        if line.startswith("- 요구사항:"):
            current.features = set(REQ_RE.findall(line))
        elif line.startswith("- 데이터 등급:"):
            current.grade = line.split(":", 1)[1].strip().split()[0]
        elif line in ("제약:", "인덱스:"):
            section = line[:-1]
        elif line.startswith("- `") and section:
            sql = line[3 : line.rindex("`")]
            (current.constraints if section == "제약" else current.indexes).append(sql)
        elif line.startswith("| ") and not line.startswith("| 컬럼") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 6:
                raise ValueError(f"{current.name}: column row needs 6 cells: {line}")
            name, ctype, null, default, keys, _desc = cells
            fk = FK_RE.search(keys)
            current.columns.append(
                Column(name, ctype, null == "Y", default, keys, fk.groups() if fk else None)
            )
    return tables


def load_requirement_ids(req_dir: Path = REQUIREMENTS_DIR) -> set[str] | None:
    """All FR/NFR IDs defined in docs/requirements, or None if the folder is absent."""
    files = sorted(req_dir.glob("*/*.md")) if req_dir.is_dir() else []
    if not files:
        return None
    ids: set[str] = set()
    for md in files:
        ids |= set(re.findall(r"^### (N?FR-[A-Z]+-\d{3}) ", md.read_text(encoding="utf-8"), re.M))
    return ids


def validate(tables: list[Table], requirement_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    by_name = {t.name: t for t in tables}
    if len(by_name) != len(tables):
        errors.append("duplicate table names")
    codes = [t.code for t in tables]
    if len(set(codes)) != len(codes):
        errors.append("duplicate table codes")
    for t in tables:
        cols = {c.name: c for c in t.columns}
        if not t.columns:
            errors.append(f"{t.name}: no columns")
        if len(cols) != len(t.columns):
            errors.append(f"{t.name}: duplicate column names")
        if not t.pk:
            errors.append(f"{t.name}: no primary key")
        if t.grade not in GRADES:
            errors.append(f"{t.name}: unknown data grade {t.grade!r}")
        if not t.features:
            errors.append(f"{t.name}: no requirement mapping")
        if requirement_ids is not None and t.features - requirement_ids:
            errors.append(f"{t.name}: unknown requirement {sorted(t.features - requirement_ids)}")
        for c in t.columns:
            if c.name in t.pk and c.nullable:
                errors.append(f"{t.name}.{c.name}: PK column is nullable")
            if "FK" in c.keys and not c.fk:
                errors.append(f"{t.name}.{c.name}: malformed FK {c.keys!r}")
            if c.fk:
                ref_t, ref_c, action = c.fk
                if ref_t not in by_name:
                    errors.append(f"{t.name}.{c.name}: FK to unknown table {ref_t}")
                    continue
                ref = {x.name: x for x in by_name[ref_t].columns}.get(ref_c)
                if ref is None:
                    errors.append(f"{t.name}.{c.name}: FK to unknown column {ref_t}.{ref_c}")
                elif ref.type != c.type:
                    errors.append(f"{t.name}.{c.name}: type {c.type} != {ref_t}.{ref_c} {ref.type}")
                elif by_name[ref_t].pk != [ref_c] and "UQ" not in ref.keys:
                    errors.append(f"{t.name}.{c.name}: FK target {ref_t}.{ref_c} is not PK/UQ")
                if action == "SET NULL" and not c.nullable:
                    errors.append(f"{t.name}.{c.name}: SET NULL on NOT NULL column")
                if action == "CASCADE" and ref_t in SOFT_DELETE_CATALOGS and t.grade in {"PERSONAL", "SENSITIVE"}:
                    # catalogs are retired with is_active=false; a hard delete must not wipe user history
                    errors.append(f"{t.name}.{c.name}: CASCADE from catalog {ref_t} into personal data")
    if requirement_ids is not None:
        mapped = set().union(*(t.features for t in tables))
        functional = {r for r in requirement_ids if r.startswith("FR-")}
        missing = sorted(functional - mapped - set(NO_DATA_REQUIREMENTS))
        if missing:
            errors.append(f"requirements without any table: {missing}")
        stale = sorted(set(NO_DATA_REQUIREMENTS) & mapped)
        if stale:
            errors.append(f"NO_DATA_REQUIREMENTS entry now has tables: {stale}")
    return errors


def _order(tables: list[Table]) -> list[Table]:
    """Topological order so referenced tables are created first."""
    by_name = {t.name: t for t in tables}
    deps = {
        t.name: {c.fk[0] for c in t.columns if c.fk and c.fk[0] != t.name}
        | {m for s in t.constraints for m in re.findall(r"REFERENCES ([a-z_]+)", s)}
        for t in tables
    }
    done: list[str] = []
    while len(done) < len(tables):
        ready = [n for n in by_name if n not in done and deps[n] <= set(done)]
        if not ready:
            raise ValueError(f"FK cycle among {set(by_name) - set(done)}")
        done.extend(sorted(ready, key=lambda n: by_name[n].code))
    return [by_name[n] for n in done]


def ddl(tables: list[Table], schema: str = "career") -> str:
    out = [
        "-- GENERATED by database/model/check_data_dictionary.py from DATA_DICTIONARY.md",
        "-- VALIDATION ONLY: disposable database. NOT a migration. NEVER run on Staging.",
        "BEGIN;",
        f"SET search_path TO {schema};",
    ]
    for t in _order(tables):
        lines = []
        for c in t.columns:
            s = f"    {c.name} {c.type}"
            if not c.nullable:
                s += " NOT NULL"
            if c.default:
                s += f" DEFAULT {c.default}"
            if re.search(r"(^|;\s*)UQ\b", c.keys):
                s += " UNIQUE"
            if c.fk:
                s += f" REFERENCES {c.fk[0]} ({c.fk[1]}) ON DELETE {c.fk[2]}"
            lines.append(s)
        lines.append(f"    PRIMARY KEY ({', '.join(t.pk)})")
        lines += [f"    {s}" for s in t.constraints]
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(lines) + "\n);")
        for i, idx in enumerate(t.indexes, 1):
            unique = idx.startswith("UNIQUE ")
            body = idx[len("UNIQUE "):] if unique else idx
            cols, _, where = body.partition(" WHERE ")
            stmt = f"CREATE {'UNIQUE ' if unique else ''}INDEX ix_{t.name}_{i} ON {t.name} {cols}"
            out.append(stmt + (f" WHERE {where}" if where else "") + ";")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


def erd(tables: list[Table]) -> str:
    groups = {
        "A": "계정·인증·권한", "B": "동의·경력·역량·직무", "C": "기업·공고·데이터 출처",
        "D": "매칭·Skill Gap·추천·모델", "E": "문서·RAG", "F": "Agent·시장·행동 분석·운영",
    }
    parts = [
        "# AI Career Platform — 전체 ERD v0.2",
        "",
        "> **자동 생성 파일 — 직접 수정하지 마세요.** 원본: [DATA_DICTIONARY.md](DATA_DICTIONARY.md) · "
        "재생성: `python3 database/model/check_data_dictionary.py --write-erd`",
        f"> 테이블 {len(tables)}개, FK {sum(1 for t in tables for c in t.columns if c.fk) + sum(len(re.findall('REFERENCES', s)) for t in tables for s in t.constraints)}개. "
        "영역별 그림은 영역 안의 테이블과, 다른 영역 테이블로 향하는 FK를 함께 보여줍니다.",
        "",
    ]

    def rels(subset: list[Table]) -> list[str]:
        r = []
        for t in subset:
            for c in t.columns:
                if c.fk:
                    card = "o|" if c.nullable else "||"
                    one_to_one = t.pk == [c.name]
                    r.append(f"    {c.fk[0].upper()} {card}--{'o|' if one_to_one else 'o{'} {t.name.upper()} : {c.name}")
            for s in t.constraints:
                m = re.search(r"FOREIGN KEY \(([^)]*)\) REFERENCES ([a-z_]+)", s)
                if m:
                    r.append(f"    {m.group(2).upper()} ||--o{{ {t.name.upper()} : \"{m.group(1)}\"")
        return r

    def entity(t: Table) -> list[str]:
        lines = [f"    {t.name.upper()} {{"]
        for c in t.columns:
            mark = " PK" if c.name in t.pk else (" FK" if c.fk else (" UK" if "UQ" in c.keys else ""))
            typ = c.type.split("(")[0].replace(" ", "_")
            lines.append(f"        {typ} {c.name}{mark}")
        lines.append("    }")
        return lines

    for g, title in groups.items():
        subset = [t for t in tables if t.code.startswith(g) and not (g == "F" and t.code == "F04")]
        if g == "D":
            subset += [t for t in tables if t.code == "F04"]
        parts += [f"## {g}. {title}", "", "```mermaid", "erDiagram"]
        for t in subset:
            parts += entity(t)
        parts += rels(subset)
        parts += ["```", ""]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ddl", action="store_true")
    ap.add_argument("--write-erd", action="store_true")
    ap.add_argument("--requirements-dir", type=Path, default=REQUIREMENTS_DIR)
    args = ap.parse_args()
    tables = parse(DICTIONARY.read_text(encoding="utf-8"))
    requirement_ids = load_requirement_ids(args.requirements_dir)
    if requirement_ids is None:
        print(f"WARN {args.requirements_dir} not found: requirement coverage skipped", file=sys.stderr)
    errors = validate(tables, requirement_ids)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    fk = sum(1 for t in tables for c in t.columns if c.fk) + sum(
        len(re.findall("REFERENCES", s)) for t in tables for s in t.constraints
    )
    print(f"PASS tables={len(tables)} columns={sum(len(t.columns) for t in tables)} fks={fk}", file=sys.stderr)
    if args.ddl:
        sys.stdout.write(ddl(tables))
    if args.write_erd:
        ERD_FILE.write_text(erd(tables), encoding="utf-8")
        print(f"WROTE {ERD_FILE.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
