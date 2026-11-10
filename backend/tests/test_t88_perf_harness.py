"""T88 성능 측정 도구의 순수 로직과 안전 가드 (DB·네트워크 없음)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("t88_baseline", Path(__file__).resolve().parents[1] / "perf/t88_baseline.py")
t88 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t88)


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert t88.percentile(values, 50) == 50
    assert t88.percentile(values, 95) == 95
    assert t88.percentile(values, 99) == 99
    assert t88.percentile([7.0], 99) == 7.0
    assert t88.percentile([], 50) is None


def test_summary_separates_success_errors_and_timeouts():
    result = t88.summarize([1.0, 2.0, 3.0, 4.0], [200, 200, 503, 429], timeouts=1, wall_s=2.0)
    assert result["requests"] == 5 and result["success"] == 2
    assert result["success_rate"] == 0.4 and result["error_rate"] == 0.6
    assert result["status_counts"] == {"200": 2, "429": 1, "503": 1}
    assert result["timeouts"] == 1 and result["throughput_rps"] == 2.5


@pytest.mark.parametrize("url,flag", [
    ("postgresql://u@10.0.0.5:5432/t16_profile_test", "YES"),
    ("postgresql://u@127.0.0.1:5432/ai_career_poc", "YES"),
    ("postgresql://u@127.0.0.1:5432/t16_profile_test", ""),
])
def test_guard_refuses_anything_but_the_disposable_loopback_db(monkeypatch, url, flag):
    monkeypatch.setenv("T16_ISOLATED_DB_TEST", flag)
    with pytest.raises(SystemExit):
        t88.guard(url)


def test_guard_accepts_the_disposable_db(monkeypatch):
    monkeypatch.setenv("T16_ISOLATED_DB_TEST", "YES")
    t88.guard("postgresql://u@127.0.0.1:5432/t16_profile_test")


def test_memory_probe_returns_numbers_or_none():
    result = t88.memory_mb()
    assert set(result) == {"rss_mb", "peak_rss_mb"}
    assert result["peak_rss_mb"] is None or result["peak_rss_mb"] > 0
