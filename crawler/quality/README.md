# T63 STEP 01 — 합성 채용공고 상태 및 만료 판정 (OFFLINE)

## 적용 범위

`crawler/quality/lifecycle.py`의 `classify_posting(posting, as_of=...)`은 T62의 `NormalizedPosting` 객체를 읽어 **상태를 분류**합니다. 입력 데이터·PostgreSQL·T62 Worker에 쓰지 않으며, 잡코리아 사이트나 외부 네트워크를 호출하지 않습니다. 정책 검증 전용입니다.

## 우선순위와 날짜 경계

1. `status=closed` → `CLOSED` (마감일과 무관)
2. `status=draft` → `DRAFT` (마감일과 무관)
3. `status=published`, `expires_on < as_of` → `EXPIRED`
4. 그 외 `status=published` → `ACTIVE`

`expires_on == as_of`는 **당일까지 진행 중**으로 가정합니다. 날짜는 `YYYY-MM-DD`, 비교 기준일은 호출자가 `date`로 명시합니다. 원문 타임존·시각이 없는 날짜-only fixture를 사용하는 것이므로 실제 잡코리아의 마감시간 정책을 확인한 것은 아닙니다. `expires_on`이 없다는 이유만으로 만료 또는 삭제를 추정하지 않습니다. 데이터 삭제·원천에서 사라짐·재게시 판정은 이 단계에서 구현하지 않습니다.

## 검증 명령

저장소 루트의 Windows PowerShell에서:

```powershell
py -3.12 -m unittest crawler.tests.test_lifecycle -v
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 T62 48개 + 신규 T63 10개 = **58개 테스트 기대**. 로컬 테스트 결과가 제출되기 전에는 PASS를 선언하지 않습니다.

## 후속 작업

T63 STEP 02 이후에 필수값·재게시·삭제/비활성·입력별 이유 코드, 재처리 및 원본 출처 계약을 설계·검증합니다. 정식 `career` DB 스키마·Migration, Staging, 운영 환경은 변경하지 않습니다.
