"""앱 코드는 DB 드라이버(psycopg)를 직접 import하지 않고 SQLAlchemy만 쓴다."""

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_app_does_not_import_db_driver_directly():
    offenders = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "psycopg" or name.startswith("psycopg.") for name in names):
                offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    assert offenders == [], f"psycopg를 직접 import하는 곳: {offenders}"
