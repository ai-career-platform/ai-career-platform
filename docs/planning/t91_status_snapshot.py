# T91 task status snapshot generator. Usage (repo root):
#   gh pr list --state all --limit 500 --json number,title,state,mergedAt,isDraft > prs.json
#   python docs/planning/t91_status_snapshot.py prs.json docs/planning/T91_TASK_STATUS_SNAPSHOT.json
import json
import re
import sys
from collections import Counter
from pathlib import Path

prs = json.load(open(sys.argv[1], encoding="utf-8"))
wo = {}
for f in Path("docs/work-orders").glob("*/T*.md"):
    m = re.fullmatch(r"T(\d+)\.md", f.name)
    if not m or int(m.group(1)) > 90:
        continue
    t = f"T{int(m.group(1)):02d}" if int(m.group(1)) < 10 and f.name.startswith("T0") else f.stem
    text = f.read_text(encoding="utf-8")
    head = text.split("\n## ")[0]
    feats = sorted(set(re.findall(r"F-0\d\d", head)))
    wo[f.stem] = {"title": text.splitlines()[0].lstrip("# ").strip(), "features": feats, "file": f.as_posix()}

def tasks_of(title: str) -> set:
    """PR 제목의 일감 번호. 작업지시서 묶음 PR은 구현 증빙이 아니므로 제외, 범위(T35~T40)는 펼침."""
    if re.search(r"work.?orders?|signup TSV|작업지시서", title, re.I):
        return set()
    found = {f"T{int(n):02d}" for n in re.findall(r"\bT(\d{1,3})\b", title)}
    for a, b in re.findall(r"\bT(\d{1,3})\s*[~–-]\s*T(\d{1,3})\b", title):
        found |= {f"T{n:02d}" for n in range(int(a), int(b) + 1)}
    return found


status = {}
for t, v in wo.items():
    rel = [p for p in prs if t in tasks_of(p["title"])]
    merged = [p["number"] for p in rel if p["state"] == "MERGED"]
    opened = [p["number"] for p in rel if p["state"] == "OPEN"]
    state = "MERGED" if merged else ("OPEN_PR" if opened else "NO_PR")
    status[t] = {**v, "state": state, "merged": merged, "open": opened}

Path(sys.argv[2]).write_text(json.dumps(dict(sorted(status.items(), key=lambda x: int(x[0][1:]))),
                                        ensure_ascii=False, indent=1), encoding="utf-8")
print(Counter(v["state"] for v in status.values()), len(status))
feat = {}
for t, v in sorted(status.items(), key=lambda x: int(x[0][1:])):
    for f in v["features"]:
        feat.setdefault(f, []).append(f"{t}:{v['state'][0]}")
for f in sorted(feat):
    print(f, " ".join(feat[f]))
missing = [t for t, v in status.items() if not v["features"]]
print("no-feature:", " ".join(sorted(missing, key=lambda x: int(x[1:]))))
