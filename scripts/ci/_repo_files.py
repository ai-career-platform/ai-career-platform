"""T28 CI 스크립트 공용: 검사 대상 파일 목록 (표준 라이브러리만 사용)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def repo_files(root: Path, pattern: str | None = None) -> list[Path]:
    """git이 추적하는 파일과, 무시되지 않은 미추적 파일을 반환합니다.

    미추적 파일도 포함해야 커밋 전 로컬 실행에서 새 파일이 검사됩니다.
    """
    cmd = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others"]
    cmd += ["--exclude-standard"]
    if pattern:
        cmd += ["--", pattern]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    names = sorted({n for n in out.decode("utf-8").split("\0") if n})
    return [root / n for n in names if (root / n).is_file()]
