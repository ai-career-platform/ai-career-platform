# T45 — 규칙 기반 개인화 추천 Run API (학습용)

## 1. API 계약

T06 `docs/api/openapi.yaml` 기준. 새 `GET /recommendations/jobs`는 만들지 않는다.

- `POST /api/v1/recommendation-runs` → 201 + Location, JWT 사용자별 추천 계산·기존 DB 테이블에 결과 기록. body `{ "limit": 20 }` 또는 body 생략 가능, 1~50.
- `GET /api/v1/recommendation-runs/latest` → 200/404. 기존 최신 run 읽기 전용.
- `GET /api/v1/recommendation-runs/{recommendation_run_id}` → 200/404. 타 사용자 run도 404.

## 2. 계산·출력

- T27 `recommendation_baseline.recommend()` 재사용. 기술 코드 일치율 0~100이며 확률 아님.
- T18 공개/미만료 공고 필터를 DB에 적용한다. `expires_at IS NULL` 상시 공고 포함. 최신 공개 공고 500건 상한 내 후보만 살핀다.
- 순위: T27 기술 일치 점수 내림차순, 동점 시 사용자 목표 직무 우선순위, 그다음 공고 ID 오름차순. T27 함수는 후보를 50건씩 나눠 적용하고, 전체 후보를 합쳐 한 번 더 정렬하므로 500건 범위의 동점도 일관되게 처리한다.
- 중복 공고 ID는 T18 목록 쿼리에서 발생하지 않으며, 최신 `not_interested` 피드백 공고 제외. 실제 데이터의 원본 품질/중복 출처 통합은 범위 밖.
- 보유 기술이 없거나 기술 비교 가능한 공고가 없으면 `fallback` + 최신 공개 공고 (점수 null). 공개 공고 자체가 없으면 `fallback` + 빈 items.
- 기존 `career.model_versions`에 규칙 버전 (`skill_overlap_baseline` / `skill-overlap-draft-v2`, `kind=rule`)을 upsert한 후 기존 `recommendation_runs/items`에 기록. **미승인 학습용 규칙**임을 description에 명시. 새로운 DDL/Migration 없음.

## 3. 테스트

```powershell
cd backend
python -m pytest -q tests/test_recommendation_baseline.py tests/test_recommendation_runs.py
python -m pytest -q
```

합성 fixture와 Mock 서비스 경로는 GitHub Backend CI에서 검증한다. 실제 PostgreSQL run 저장/조회 E2E, 부하/스냅샷, 개인정보 동의 기반 행동 추천, 배포 검증은 **별도 NOT_VERIFIED**로 기록한다.

## 4. 구현 경계

- T25 실제 ML Feature/RAG 연동 없음. 모델 학습·예측 성능 검증 없음.
- **Staging DB DDL·Seed·테스트 사용자 조작 없음**. Staging에서 pytest 실행 금지.
- 추천 저장은 API POST에서만 수행하며 GET은 저장하지 않는다.
- 조회 결과는 저장된 rank/score/reason에 현재 공고 정보 및 최신 피드백을 붙인다. 공고가 사라지거나 숨겨지면 GET에서 해당 항목을 생략할 수 있다. 과거 추천 당시 공고 내용의 완전한 snapshot은 현재 DB 계약에서 저장하지 않는다.
- 후보 조회 상한 500, 1회 최대 50개 결과. 대규모 데이터·페이징, 점수별 전체 후보 검증, 모델 버전 승인 정책 및 DB E2E는 후속 단계.
