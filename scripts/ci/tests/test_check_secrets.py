"""check_secrets.py 단위 테스트 (정상 + 실패 주입).

실제처럼 보이는 가짜 값은 저장소 스캔에 걸리지 않도록 런타임에 문자열을 조립합니다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI_DIR))

import check_secrets  # noqa: E402

AWS_KEY = "AKIA" + "Q7XK2M9WZP4RT3VB"
GH_TOKEN = "ghp" + "_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z5A"
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
OPENSSH_KEY = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
SLACK = "xox" + "b-123456789012-abcdefABCDEF"
REAL_PW = "Pr0d" + "Passw0rd!2026"


def rules(text: str) -> list[str]:
    return [rule for _, rule, _ in check_secrets.scan_text(text)]


class SecretPatternTest(unittest.TestCase):
    def test_detects_aws_access_key(self) -> None:
        self.assertEqual(rules(f"aws_key_id = {AWS_KEY}\n"), ["aws-access-key-id"])

    def test_detects_private_key_headers(self) -> None:
        self.assertEqual(rules(PRIVATE_KEY), ["private-key"])
        self.assertEqual(rules(OPENSSH_KEY), ["private-key"])

    def test_detects_github_and_slack_tokens(self) -> None:
        self.assertIn("github-token", rules(f"url = https://{GH_TOKEN}@github.com\n"))
        self.assertEqual(rules(SLACK), ["slack-token"])

    def test_detects_hardcoded_password_assignments(self) -> None:
        self.assertEqual(rules(f'password = "{REAL_PW}"'), ["hardcoded-credential"])
        self.assertEqual(rules(f'{{"api_key": "{REAL_PW}"}}'), ["hardcoded-credential"])
        self.assertEqual(rules(f"DB_PASSWORD={REAL_PW}"), ["hardcoded-credential-env"])
        self.assertEqual(
            rules(f"docker run -e POSTGRES_PASSWORD={REAL_PW} img"),
            ["hardcoded-credential-env"],
        )

    def test_placeholders_and_references_are_allowed(self) -> None:
        safe = "\n".join(
            [
                "POSTGRES_PASSWORD=CHANGE_ME",
                "STAGING_SSH_KEY_PATH=",
                'password="test_password"',
                "-e POSTGRES_PASSWORD=d1test-disposable-only",
                "'GH_TOKEN':'fixture-only'",
                "TOKEN=${GH_TOKEN}",
                'password = os.environ["DB_PASSWORD"]',
                'token: "<your-token-here>"',
                "password = get_password()",
                'secret = "short"',
            ]
        )
        self.assertEqual(check_secrets.scan_text(safe), [])

    def test_inline_allow_marker(self) -> None:
        line = f'password = "{REAL_PW}"  # secret-scan: allow'
        self.assertEqual(check_secrets.scan_text(line), [])

    def test_values_are_masked_in_output(self) -> None:
        findings = check_secrets.scan_text(f"k={AWS_KEY}")
        self.assertEqual(len(findings), 1)
        self.assertNotIn(AWS_KEY, findings[0][2])
        self.assertTrue(findings[0][2].startswith("AKIA*"))


class SecretCliTest(unittest.TestCase):
    def test_cli_pass_then_fail_on_injected_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (root / ".env.example").write_text("POSTGRES_PASSWORD=CHANGE_ME\n")
            (root / "img.bin").write_bytes(b"\0" + AWS_KEY.encode())  # 바이너리는 제외
            script = str(CI_DIR / "check_secrets.py")
            ok = subprocess.run(
                [sys.executable, "-B", script, "--root", tmp],
                capture_output=True,
                text=True,
            )
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("SECRET_PATTERN_SCAN=PASS", ok.stdout)

            (root / "leak.txt").write_text(f"aws={AWS_KEY}\n")
            bad = subprocess.run(
                [sys.executable, "-B", script, "--root", tmp],
                capture_output=True,
                text=True,
            )
            self.assertEqual(bad.returncode, 1)
            self.assertIn("leak.txt:1: aws-access-key-id", bad.stdout)
            self.assertNotIn(AWS_KEY, bad.stdout)

            # .gitignore 대상(.env)은 git에 올라가지 않으므로 검사하지 않습니다.
            (root / "leak.txt").unlink()
            (root / ".gitignore").write_text(".env\n")
            (root / ".env").write_text(f"aws={AWS_KEY}\n")
            ignored = subprocess.run(
                [sys.executable, "-B", script, "--root", tmp],
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0, ignored.stdout)


class ReviewerFoundGapsTest(unittest.TestCase):
    """T28 리뷰에서 발견된 미탐/과허용 사례 회귀 테스트."""

    def test_unquoted_yaml_value_in_config_file(self) -> None:
        line = "    POSTGRES_PASSWORD: " + REAL_PW + "\n"
        found = [r for _, r, _ in check_secrets.scan_text(line, "compose.yaml")]
        self.assertIn("hardcoded-credential-unquoted", found)

    def test_unquoted_rule_not_applied_to_code(self) -> None:
        line = '    password=os.environ["POSTGRES_PASSWORD"],\n'
        self.assertEqual(check_secrets.scan_text(line, "main.py"), [])

    def test_unquoted_placeholder_allowed(self) -> None:
        for v in ("CHANGE_ME", "${POSTGRES_PASSWORD}", "<your-password>"):
            line = "POSTGRES_PASSWORD: " + v + "\n"
            self.assertEqual(check_secrets.scan_text(line, "compose.yaml"), [], v)

    def test_unquoted_rule_skips_docs_examples(self) -> None:
        # OpenAPI 명세의 example 값(docs/api/openapi.yaml)은 문서 예시입니다.
        line = "              password: correct-horse-" + "battery-1\n"
        self.assertEqual(check_secrets.scan_text(line, "docs/api/openapi.yaml"), [])
        found = [r for _, r, _ in check_secrets.scan_text(line, "deploy/app.yaml")]
        self.assertIn("hardcoded-credential-unquoted", found)

    def test_credential_in_url(self) -> None:
        url = "postgresql://app:" + REAL_PW.replace("!", "") + "@db:5432/app"
        self.assertIn("credential-in-url", rules("DATABASE_URL=" + url + "\n"))

    def test_url_with_placeholder_password_allowed(self) -> None:
        self.assertEqual(
            rules("postgresql://dev_local:<password>@127.0.0.1:25432/x\n"), []
        )

    def test_placeholder_word_must_be_whole_word(self) -> None:
        # "Latest"·"contestant" 안의 test 때문에 허용되면 안 됩니다.
        self.assertIn(
            "hardcoded-credential", rules('password = "MyLatest' + 'Pw2026!"\n')
        )
        self.assertIn(
            "hardcoded-credential", rules('api_key = "contest' + 'ant99Zq"\n')
        )
        # 단어 단위 자리표시자는 계속 허용합니다.
        self.assertEqual(rules('password = "test-only-value"\n'), [])


if __name__ == "__main__":
    unittest.main()
