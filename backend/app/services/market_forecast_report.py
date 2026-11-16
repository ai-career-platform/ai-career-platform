"""T69 검증 보고서 생성기 — 합성 데이터 3종으로 백테스트하고 Markdown 표를 출력한다.

실행 (backend 폴더):  python -m app.services.market_forecast_report > docs/T69_VALIDATION_REPORT.md
같은 코드·같은 seed면 항상 같은 보고서가 나온다(재현성). 실행 시각은 넣지 않는다.
"""

from app.services.market_forecast import LIMITATION, EvaluationReport, backtest
from app.services.market_forecast_synthetic import SYNTHETIC_SOURCE, random_walk, weekly_postings

CASES = (
    ("계절성+상승 추세 52주", lambda: weekly_postings()),
    ("빈 구간 3주 포함 52주", lambda: weekly_postings(missing=(20, 21, 35))),
    ("무작위 걸음 52주 (기준선 이기기 어려움)", lambda: random_walk()),
    ("데이터 부족 14주", lambda: weekly_postings(weeks=14)),
)


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:.1%}" if pct else f"{x:.3f}"


def render(cases=CASES) -> str:
    lines = [
        "# T69 채용시장 추세 예측 Baseline — 검증 보고서 (합성 데이터)",
        "",
        f"> 데이터 출처: `{SYNTHETIC_SOURCE}` (실제 시장 데이터 아님). {LIMITATION}",
        "> 생성: `python -m app.services.market_forecast_report` — 같은 코드면 같은 결과.",
        "",
    ]
    for title, make in cases:
        series = make()
        r: EvaluationReport = backtest(series)
        lines += [
            f"## {title}",
            "",
            f"- 지표 `{r.metric_code}` · 주기 `{r.period}` · 관측 {len(series.observations)}개 · "
            f"예측 기간 {r.horizon} · 최소 학습 {r.min_train} · fold {r.folds}",
            f"- 판정 **{r.verdict}** · 최선 후보 `{r.best_model or '—'}` · naive 대비 MAE 개선 "
            f"{_fmt(r.improvement_vs_naive, pct=True)}",
        ]
        if r.reasons:
            lines.append(f"- HOLD 사유: {'; '.join(r.reasons)}")
        lines += [
            f"- 데이터 지문 `{r.model_version['dataset_sha256'][:16]}…`",
            "",
            "| 모델 | MAE | WAPE | sMAPE |",
            "|---|---:|---:|---:|",
        ]
        lines += [f"| {s.model} | {_fmt(s.mae)} | {_fmt(s.wape, True)} | {_fmt(s.smape, True)} |" for s in r.scores]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(render())
