"""check_md_links.py 단위 테스트 (정상 + 실패 주입)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI_DIR))

import check_md_links  # noqa: E402


class MdLinkCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "target.md").write_text("# T\n", encoding="utf-8")
        (self.root / "README.md").write_text("# R\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_check(self, text: str):
        md = self.root / "docs" / "index.md"
        md.write_text(text, encoding="utf-8")
        return check_md_links.check(self.root, [md])

    def test_valid_links_pass(self) -> None:
        text = (
            "[a](target.md) [b](./target.md#sec) [c](../README.md)\n"
            '![img](target.md) [d](</docs/target.md>) [e](target.md "title")\n'
            "[ref]: ../README.md\n"
            "[web](https://example.com/x) [mail](mailto:a@b.c) [anchor](#top)\n"
        )
        _, count, broken = self.run_check(text)
        self.assertEqual(broken, [])
        self.assertEqual(count, 7)

    def test_broken_link_is_detected(self) -> None:
        _, _, broken = self.run_check("ok [x](target.md)\n[bad](missing.md)\n")
        self.assertEqual(len(broken), 1)
        self.assertIn("docs/index.md:2: missing.md (not found)", broken[0])

    def test_broken_reference_definition_is_detected(self) -> None:
        _, _, broken = self.run_check("[ref]: ./nope/file.md\n")
        self.assertEqual(len(broken), 1)

    def test_link_outside_repository_is_rejected(self) -> None:
        _, _, broken = self.run_check("[x](../../outside.md)\n")
        self.assertEqual(len(broken), 1)
        self.assertIn("outside repository", broken[0])

    def test_code_blocks_and_inline_code_are_ignored(self) -> None:
        text = (
            "```text\n[x](missing.md)\n```\n"
            "~~~\n[y](missing.md)\n~~~\n"
            "inline `[z](missing.md)` text\n"
        )
        _, count, broken = self.run_check(text)
        self.assertEqual((count, broken), (0, []))

    def test_url_encoded_path(self) -> None:
        (self.root / "docs" / "a b.md").write_text("x", encoding="utf-8")
        _, _, broken = self.run_check("[s](a%20b.md)\n")
        self.assertEqual(broken, [])

    def test_cli_exit_codes_with_git_repo(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "docs" / "index.md").write_text(
            "[a](target.md)\n", encoding="utf-8"
        )
        script = str(CI_DIR / "check_md_links.py")
        ok = subprocess.run(
            [sys.executable, "-B", script, "--root", str(self.root)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("DOCS_LINK_CHECK=PASS", ok.stdout)
        # 실패 주입: 미추적 새 파일의 깨진 링크도 잡아야 합니다.
        (self.root / "new.md").write_text("[b](gone.md)\n", encoding="utf-8")
        bad = subprocess.run(
            [sys.executable, "-B", script, "--root", str(self.root)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(bad.returncode, 1)
        self.assertIn("BROKEN_LINK new.md:1: gone.md", bad.stdout)
        self.assertIn("DOCS_LINK_CHECK=FAIL", bad.stdout)


if __name__ == "__main__":
    unittest.main()
