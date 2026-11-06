"""T111: 추적된 환경 예시와 소스의 설정 계약을 오프라인 검증합니다.

실제 .env, 프로세스 환경, 자격증명 파일은 읽지 않습니다. 진단에는 값 대신
파일·변수 이름과 문제 종류만 출력합니다. 운영 설정 검증/Secret 회전은 별도입니다.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from urllib.parse import urlsplit

EXAMPLE_PATHS = (
    ".env.example",
    "backend/.env.example",
    "frontend/.env.example",
    "frontend/.env.mock",
    "poc/staging/.env.example",
)
SSH_KEYS = {
    "STAGING_SSH_HOST",
    "STAGING_SSH_PORT",
    "STAGING_SSH_USER",
    "STAGING_SSH_KEY_PATH",
    "STAGING_SSH_ALIAS",
}
ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)")
COMPOSE_REQUIRED = re.compile(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*):\?[^}]*\}")
PUBLIC_SECRET_NAME = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|PRIVATE|API_KEY|ACCESS_KEY|DATABASE_URL|DB_URL)"
)


def python_env_names(source: str) -> set[str]:
    """현재 설정 코드의 os.environ/getenv에서 리터럴 변수 이름만 추출합니다."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            key = node.slice
        elif (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) in {"os.environ.get", "os.getenv"}
            and node.args
        ):
            key = node.args[0]
        else:
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
    return names


def parse_example(text: str, path: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if match is None:
            errors.append(
                f"{path}:{number}: invalid example assignment (value omitted)"
            )
            continue
        name, value = match.groups()
        if name in values:
            errors.append(f"{path}:{number}: duplicate variable {name}")
        if value.startswith(("'", '"')):
            quoted = re.fullmatch(r"""(['"])(.*?)\1\s*(?:#.*)?""", value)
            if quoted is None:
                errors.append(f"{path}:{number}: invalid quoted value for {name}")
                continue
            value = quoted.group(2)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[name] = value
    return values, errors


def check(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []

    def read(path: str) -> str:
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            errors.append(f"{path}: source outside repository")
            return ""
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"{path}: required source missing or unreadable")
            return ""

    examples: dict[str, dict[str, str]] = {}
    for path in EXAMPLE_PATHS:
        examples[path], found = parse_example(read(path), path)
        errors.extend(found)

    compose = read("poc/staging/compose.yaml")
    compose_required = set(COMPOSE_REQUIRED.findall(compose))
    # This checks the current flat service environment mappings, not arbitrary YAML.
    compose_names = set(re.findall(r"^      ([A-Z][A-Z0-9_]*):", compose, re.MULTILINE))
    frontend_names = set(
        re.findall(
            r"import\.meta\.env\.(VITE_[A-Z0-9_]+)", read("frontend/src/config/env.ts")
        )
    )
    proxy_names = set(
        re.findall(r"env\.(DEV_[A-Z0-9_]+)", read("frontend/vite.config.ts"))
    )

    source_names: dict[str, set[str]] = {}
    for path in ("backend/app/core/config.py", "poc/staging/backend/main.py"):
        try:
            source_names[path] = python_env_names(read(path))
        except SyntaxError:
            errors.append(f"{path}: invalid Python source (details omitted)")
            source_names[path] = set()

    expected = {
        ".env.example": SSH_KEYS,
        "backend/.env.example": source_names["backend/app/core/config.py"],
        "frontend/.env.example": frontend_names | proxy_names,
        "frontend/.env.mock": frontend_names,
        "poc/staging/.env.example": compose_required,
    }
    for path, required in expected.items():
        for missing in sorted(required - examples[path].keys()):
            errors.append(f"{path}: missing variable {missing}")

    for missing in sorted(source_names["poc/staging/backend/main.py"] - compose_names):
        errors.append(
            f"poc/staging/compose.yaml: source requires unmapped variable {missing}"
        )

    for path in ("frontend/.env.example", "frontend/.env.mock"):
        values = examples[path]
        for name in sorted(values):
            if name.startswith("VITE_") and PUBLIC_SECRET_NAME.search(name):
                errors.append(f"{path}: browser-exposed credential variable {name}")
        base = values.get("VITE_API_BASE_URL", "")
        if not base.startswith("/") or base.startswith("//") or "\\" in base:
            errors.append(
                f"{path}: VITE_API_BASE_URL must use a same-origin absolute path"
            )
        expected_mock = "true" if path.endswith(".env.mock") else "false"
        if values.get("VITE_API_MOCK") != expected_mock:
            errors.append(
                f"{path}: VITE_API_MOCK mode does not match the example purpose"
            )

    target = examples["frontend/.env.example"].get("DEV_API_PROXY_TARGET", "")
    try:
        url = urlsplit(target)
        valid = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
        )
        _ = url.port  # Reject invalid port syntax without printing the URL.
    except ValueError:
        valid = False
    if not valid:
        errors.append(
            "frontend/.env.example: DEV_API_PROXY_TARGET must be an HTTP URL without credentials"
        )

    poc = examples["poc/staging/.env.example"]
    for name in sorted(compose_required - {"POSTGRES_PASSWORD"}):
        if name in poc and not poc[name]:
            errors.append(f"poc/staging/.env.example: empty required variable {name}")
    # Bootstrap credentials are never usable credentials in a tracked example.
    if poc.get("POSTGRES_PASSWORD") not in {"CHANGE_ME", "REPLACE_ME", "<password>"}:
        errors.append(
            "poc/staging/.env.example: POSTGRES_PASSWORD must be an explicit placeholder"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    errors = check(parser.parse_args(argv).root)
    for error in errors:
        print(f"ENV_EXAMPLE_ERROR {error}")
    result = "FAIL" if errors else "PASS"
    print(
        f"ENV_EXAMPLE_CHECK={result} (offline examples only; no runtime secrets read)"
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
