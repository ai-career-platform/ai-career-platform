#!/usr/bin/env python3
"""Markdown 상대 링크 검사기 (T28 PR 게이트, 표준 라이브러리만 사용).

git 추적/미추적(무시 제외) *.md 파일에서 코드 블록과 인라인 코드를 제외한
`[text](path)`, `![alt](path)`, `[ref]: path` 링크의 대상 파일이 존재하는지 확인합니다.

검사하지 않는 것: 외부 URL(http/https/mailto 등), `#anchor`의 유효성.
종료 코드: 0 = 깨진 링크 없음, 1 = 깨진 링크 있음.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_files import repo_files  # noqa: E402

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")
INLINE_LINK_RE = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*(<[^>]*>|[^)\s]+)")
REF_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def iter_links(text: str):
    """(줄 번호, 링크 대상) 목록. 코드 블록·인라인 코드는 제외합니다."""
    fence: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = FENCE_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        line = INLINE_CODE_RE.sub("", line)
        for target in INLINE_LINK_RE.findall(line):
            yield lineno, target
        ref = REF_DEF_RE.match(line)
        if ref:
            yield lineno, ref.group(1)


def resolve(md_file: Path, target: str, root: Path) -> Path | None:
    """검사할 로컬 경로. 외부 URL·앵커 전용이면 None."""
    target = target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#") or SCHEME_RE.match(target):
        return None
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    if path.startswith("/"):
        return (root / path.lstrip("/")).resolve()
    return (md_file.parent / path).resolve()


def check(root: Path, files: list[Path] | None = None) -> tuple[int, int, list[str]]:
    root = root.resolve()
    files = files if files is not None else repo_files(root, "*.md")
    broken: list[str] = []
    count = 0
    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")
        for lineno, target in iter_links(text):
            dest = resolve(md, target, root)
            if dest is None:
                continue
            count += 1
            inside = dest == root or root in dest.parents
            if not inside or not dest.exists():
                rel = md.resolve().relative_to(root).as_posix()
                why = "outside repository" if not inside else "not found"
                broken.append(f"{rel}:{lineno}: {target} ({why})")
    return len(files), count, broken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="저장소 루트 (기본: 현재 폴더)")
    args = parser.parse_args(argv)
    n_files, n_links, broken = check(Path(args.root))
    for item in broken:
        print(f"BROKEN_LINK {item}")
    print(f"md_files={n_files} relative_links={n_links} broken={len(broken)}")
    if broken:
        print("DOCS_LINK_CHECK=FAIL")
        return 1
    print("DOCS_LINK_CHECK=PASS (relative file targets only; anchors/URLs not checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
