#!/usr/bin/env python3
"""T118 공급망 — 재현 가능한 SBOM(CycloneDX 1.5 JSON)·잠금 정책 검사·취약점 게이트.

명령
    sbom    [--resolved <pip-audit.json>] [--out FILE]  저장소 잠금 파일에서 SBOM 생성(같은 입력 → 같은 바이트)
    policy                                              잠금·고정 정책 검사(exit 1 = 위반)
    gate    --scan <rows.json> [--today YYYY-MM-DD]     HIGH/CRITICAL 이 승인·미만료 예외 없이 남으면 exit 1

입력
- Python: backend/requirements*.txt, poc/staging/backend/requirements.txt (직접 의존성만 고정되어 있음)
  `--resolved` 로 pip-audit JSON 을 주면 그 시점에 해석된 전이 의존성도 넣는다(scan 시점 표시).
- npm: frontend/package-lock.json, frontend/tools/openapi/package-lock.json (전이 포함, integrity 해시)
- 컨테이너: Dockerfile 의 FROM (태그·digest)

이 도구는 네트워크를 쓰지 않는다. 취약점 조회는 pip-audit / npm audit 로 따로 하고 결과를 gate 에 넣는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PY_REQS = ["backend/requirements.txt", "backend/requirements-dev.txt", "poc/staging/backend/requirements.txt"]
NPM_LOCKS = ["frontend/package-lock.json", "frontend/tools/openapi/package-lock.json"]
DOCKERFILES = ["poc/staging/backend/Dockerfile", "poc/staging/backend/Dockerfile.integrated",
               "poc/staging/frontend/Dockerfile"]
EXCEPTIONS = ROOT / "docs" / "security" / "supply_chain_exceptions.yaml"
_REQ = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?(?P<op>==|>=|<=|~=|>|<|!=)?(?P<ver>[^;\s#]*)")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_requirements(root: Path = ROOT) -> list[dict]:
    out = []
    for rel in PY_REQS:
        path = root / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-r", "--")):
                continue
            m = _REQ.match(line)
            if m:
                out.append({"file": rel, "name": norm(m["name"]), "op": m["op"] or "", "version": m["ver"]})
    return out


def npm_packages(root: Path = ROOT) -> list[dict]:
    out = []
    for rel in NPM_LOCKS:
        path = root / rel
        if not path.exists():
            continue
        lock = json.loads(path.read_text(encoding="utf-8"))
        for key, meta in sorted((lock.get("packages") or {}).items()):
            if not key:
                continue
            name = meta.get("name") or key.split("node_modules/")[-1]
            out.append({"file": rel, "lockfileVersion": lock.get("lockfileVersion"), "name": name,
                        "version": meta.get("version", ""), "integrity": meta.get("integrity", ""),
                        "dev": bool(meta.get("dev")), "link": bool(meta.get("link"))})
    return out


def base_images(root: Path = ROOT) -> list[dict]:
    out = []
    for rel in DOCKERFILES:
        path = root / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*FROM\s+(?P<ref>\S+)", line, re.I)
            if m:
                ref = m["ref"]
                image, _, digest = ref.partition("@")
                name, _, tag = image.rpartition(":") if ":" in image.split("/")[-1] else (image, "", "")
                out.append({"file": rel, "image": name or image, "tag": tag, "digest": digest})
    return out


def build_sbom(resolved: dict | None = None, root: Path = ROOT) -> dict:
    components: dict[str, dict] = {}

    def add(purl: str, comp: dict) -> None:
        components.setdefault(purl, comp)

    for req in python_requirements(root):
        if req["op"] == "==":
            purl = f"pkg:pypi/{req['name']}@{req['version']}"
            add(purl, {"type": "library", "name": req["name"], "version": req["version"], "purl": purl,
                       "properties": [{"name": "t118:source", "value": req["file"]},
                                      {"name": "t118:scope", "value": "direct"}]})
    for dep in (resolved or {}).get("dependencies", []):
        purl = f"pkg:pypi/{norm(dep['name'])}@{dep['version']}"
        add(purl, {"type": "library", "name": norm(dep["name"]), "version": dep["version"], "purl": purl,
                   "properties": [{"name": "t118:source", "value": "pip-audit resolution"},
                                  {"name": "t118:scope", "value": "transitive-resolved-at-scan"}]})
    for pkg in npm_packages(root):
        if pkg["link"]:
            continue
        purl = f"pkg:npm/{pkg['name'].replace('@', '%40', 1) if pkg['name'].startswith('@') else pkg['name']}@{pkg['version']}"
        comp = {"type": "library", "name": pkg["name"], "version": pkg["version"], "purl": purl,
                "properties": [{"name": "t118:source", "value": pkg["file"]},
                               {"name": "t118:scope", "value": "dev" if pkg["dev"] else "runtime"}]}
        if pkg["integrity"]:
            algo, _, b64 = pkg["integrity"].partition("-")
            comp["hashes"] = [{"alg": algo.upper().replace("SHA", "SHA-"), "content": b64}]
        add(purl, comp)
    for img in base_images(root):
        purl = f"pkg:docker/{img['image']}@{img['tag'] or 'latest'}"
        add(purl, {"type": "container", "name": img["image"], "version": img["tag"], "purl": purl,
                   "properties": [{"name": "t118:source", "value": img["file"]},
                                  {"name": "t118:digest", "value": img["digest"] or "UNPINNED"}]})
    ordered = [components[k] for k in sorted(components)]
    body = json.dumps(ordered, sort_keys=True, ensure_ascii=False).encode()
    serial = uuid.UUID(hashlib.sha256(body).hexdigest()[:32])
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", "version": 1,
            "metadata": {"component": {"type": "application", "name": "ai-career-platform"},
                         "properties": [{"name": "t118:reproducible", "value": "no timestamp; serial = sha256(components)"}]},
            "components": ordered}


def policy_findings(root: Path = ROOT) -> list[dict]:
    findings = []
    for req in python_requirements(root):
        if req["op"] != "==":
            findings.append({"level": "FAIL", "rule": "python direct dependency not pinned with ==",
                             "where": f"{req['file']}:{req['name']}"})
    if not any((root / p).exists() for p in ("backend/requirements.lock", "backend/requirements.txt.lock")):
        findings.append({"level": "WARN", "rule": "python transitive dependencies not locked (no hashes)",
                         "where": "backend/requirements*.txt"})
    for rel in NPM_LOCKS:
        if not (root / rel).exists():
            findings.append({"level": "FAIL", "rule": "npm lockfile missing", "where": rel})
    for pkg in npm_packages(root):
        if (pkg["lockfileVersion"] or 0) < 2:
            findings.append({"level": "FAIL", "rule": "npm lockfileVersion < 2", "where": pkg["file"]})
            break
    for pkg in npm_packages(root):
        if not pkg["link"] and not pkg["integrity"]:
            findings.append({"level": "FAIL", "rule": "npm package without integrity hash",
                             "where": f"{pkg['file']}:{pkg['name']}"})
    for img in base_images(root):
        if not img["tag"] or img["tag"] == "latest":
            findings.append({"level": "FAIL", "rule": "base image without fixed tag", "where": img["file"]})
        elif not img["digest"]:
            findings.append({"level": "WARN", "rule": "base image tag not pinned by digest",
                             "where": f"{img['file']}:{img['image']}:{img['tag']}"})
    return findings


def load_exceptions(path: Path = EXCEPTIONS) -> list[dict]:
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("exceptions") or []


def gate(rows: list[dict], exceptions: list[dict], today: date) -> dict:
    """HIGH/CRITICAL 은 '승인자·사유·만료일이 있고 만료되지 않은' 예외가 있을 때만 통과."""
    valid = {}
    for e in exceptions:
        expires = e.get("expires")
        if isinstance(expires, str):
            expires = date.fromisoformat(expires)
        if str(e.get("approved_by") or "").strip() and str(e.get("reason") or "").strip() and expires and expires >= today:
            valid[(norm(e["package"]), e["id"])] = e
    blocking, excepted, reported = [], [], []
    for row in rows:
        severity = (row.get("severity") or "UNKNOWN").upper()
        key = (norm(row["package"]), row["id"])
        if severity in {"HIGH", "CRITICAL", "UNKNOWN"}:
            (excepted if key in valid else blocking).append(row)
        else:
            reported.append(row)
    return {"verdict": "FAIL" if blocking else "PASS", "blocking": blocking, "excepted": excepted,
            "reported": reported}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T118 SBOM / supply-chain policy / vulnerability gate")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sbom")
    s.add_argument("--resolved")
    s.add_argument("--out")
    sub.add_parser("policy")
    g = sub.add_parser("gate")
    g.add_argument("--scan", required=True)
    g.add_argument("--today")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "sbom":
        resolved = json.loads(Path(args.resolved).read_text(encoding="utf-8")) if args.resolved else None
        text = json.dumps(build_sbom(resolved), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    if args.command == "policy":
        findings = policy_findings()
        for f in findings:
            print(f"{f['level']} {f['rule']}: {f['where']}")
        print(f"T118_POLICY fail={sum(f['level'] == 'FAIL' for f in findings)} warn={sum(f['level'] == 'WARN' for f in findings)}")
        return 1 if any(f["level"] == "FAIL" for f in findings) else 0
    rows = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    result = gate(rows, load_exceptions(), date.fromisoformat(args.today) if args.today else date.today())
    for row in result["blocking"]:
        print(f"BLOCK {row['package']}=={row['version']} {row['id']} {row.get('severity')}")
    print(f"T118_GATE verdict={result['verdict']} blocking={len(result['blocking'])} "
          f"excepted={len(result['excepted'])} reported={len(result['reported'])}")
    return 1 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
