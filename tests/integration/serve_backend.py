"""T29용 실제 Backend HTTP 서버. DB/공유 환경 없이 loopback 임의 포트만 사용."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import create_app  # noqa: E402


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        print(f"T29_URL=http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
        config = uvicorn.Config(create_app(), log_level="critical", access_log=False)
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
