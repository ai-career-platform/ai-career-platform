"""T111 환경 계약의 정상·실패 주입 및 비밀값 비노출 회귀 테스트."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI_DIR))
import check_env_examples as checker  # noqa: E402

ROOT = CI_DIR.parents[1]
SOURCES = checker.EXAMPLE_PATHS + (
    "poc/staging/compose.yaml",
    "backend/app/core/config.py",
    "poc/staging/backend/main.py",
    "frontend/src/config/env.ts",
    "frontend/vite.config.ts",
)


class EnvironmentContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in SOURCES:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)

    def replace(self, name, before, after):
        path = self.root / name
        source = path.read_text(encoding="utf-8")
        self.assertIn(before, source)
        path.write_text(source.replace(before, after), encoding="utf-8")

    def test_current_examples_pass(self):
        self.assertEqual(checker.check(self.root), [])

    def test_missing_compose_input_is_rejected(self):
        self.replace("poc/staging/.env.example", "POSTGRES_DB=ai_career_poc", "")
        self.assertIn(
            "poc/staging/.env.example: missing variable POSTGRES_DB",
            checker.check(self.root),
        )

    def test_new_required_compose_input_needs_an_example(self):
        path = self.root / "poc/staging/compose.yaml"
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n      NEW_OPTION: ${NEW_OPTION:?required}\n")
        self.assertIn(
            "poc/staging/.env.example: missing variable NEW_OPTION",
            checker.check(self.root),
        )

    def test_escaped_container_variable_is_not_a_host_requirement(self):
        path = self.root / "poc/staging/compose.yaml"
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n# $${CONTAINER_ONLY:?required}\n")
        self.assertEqual(checker.check(self.root), [])

    def test_new_backend_input_needs_its_own_example(self):
        path = self.root / "backend/app/core/config.py"
        with path.open("a", encoding="utf-8") as stream:
            stream.write('\nnew_value = os.environ["NEW_REQUIRED_INPUT"]\n')
        self.assertTrue(
            any(
                "backend/.env.example: missing variable NEW_REQUIRED_INPUT" in e
                for e in checker.check(self.root)
            )
        )

    def test_formal_backend_settings_do_not_change_poc_contract(self):
        path = self.root / "backend/app/core/config.py"
        with path.open("a", encoding="utf-8") as stream:
            stream.write('\nnew_value = os.environ["NEW_REQUIRED_INPUT"]\n')
        with (self.root / "backend/.env.example").open("a", encoding="utf-8") as stream:
            stream.write("\nNEW_REQUIRED_INPUT=local-only\n")
        self.assertEqual(checker.check(self.root), [])

    def test_poc_backend_input_needs_a_compose_mapping(self):
        path = self.root / "poc/staging/backend/main.py"
        with path.open("a", encoding="utf-8") as stream:
            stream.write('\nnew_value = os.environ["NEW_POC_INPUT"]\n')
        self.assertTrue(
            any(
                "unmapped variable NEW_POC_INPUT" in e for e in checker.check(self.root)
            )
        )

    def test_browser_credential_name_is_rejected_even_with_placeholder(self):
        path = self.root / "frontend/.env.example"
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\nVITE_CLIENT_SECRET=CHANGE_ME\n")
        self.assertTrue(
            any(
                "browser-exposed credential variable" in e
                for e in checker.check(self.root)
            )
        )

    def test_mock_mode_cannot_silently_replace_real_requests(self):
        self.replace(
            "frontend/.env.example", "VITE_API_MOCK=false", "VITE_API_MOCK=true"
        )
        self.assertTrue(
            any("mode does not match" in e for e in checker.check(self.root))
        )

    def test_protocol_relative_api_base_is_rejected(self):
        self.replace(
            "frontend/.env.example",
            "VITE_API_BASE_URL=/api",
            "VITE_API_BASE_URL=//example.invalid/api",
        )
        self.assertTrue(
            any("same-origin absolute path" in e for e in checker.check(self.root))
        )

    def test_proxy_credentials_are_rejected_without_disclosure(self):
        private = "R7m" + "Q9nB4vZ8"
        self.replace(
            "frontend/.env.example",
            "http://127.0.0.1:18080",
            f"http://local-user:{private}@127.0.0.1:18080",
        )
        errors = checker.check(self.root)
        self.assertTrue(any("without credentials" in e for e in errors))
        self.assertNotIn(private, "\n".join(errors))

    def test_duplicate_and_quoted_values(self):
        values, errors = checker.parse_example(
            'APP_ENV="local" # note\nAPP_ENV=ci\n', "example"
        )
        self.assertEqual(values["APP_ENV"], "ci")
        self.assertEqual(errors, ["example:2: duplicate variable APP_ENV"])

    def test_missing_example_fails_closed(self):
        (self.root / "frontend/.env.mock").unlink()
        self.assertTrue(
            any("required source missing" in e for e in checker.check(self.root))
        )

    def test_cli_rejects_realistic_password_without_logging_it(self):
        script = str(CI_DIR / "check_env_examples.py")
        command = [sys.executable, "-B", script, "--root", str(self.root)]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("ENV_EXAMPLE_CHECK=PASS", good.stdout)
        private = "L9v" + "N3kP7rX2"
        self.replace(
            "poc/staging/.env.example",
            "POSTGRES_PASSWORD=CHANGE_ME",
            f"POSTGRES_PASSWORD={private}",
        )
        bad = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("ENV_EXAMPLE_CHECK=FAIL", bad.stdout)
        self.assertNotIn(private, bad.stdout + bad.stderr)

    def test_runtime_dotenv_is_never_read(self):
        # An invalid/binary local file must not affect the example-only validator.
        (self.root / "poc/staging/.env").write_bytes(b"\0\xffnot-an-example")
        self.assertEqual(checker.check(self.root), [])


if __name__ == "__main__":
    unittest.main()
