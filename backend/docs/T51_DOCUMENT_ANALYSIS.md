# T51 — 문서 분석 Pipeline·API (Mock 분석기 기준선, 학습용)

> 상태: **PARTIAL** — 비동기 API·워커·상태 전이·검수 후 적용은 동작한다. 분석기는 **결정적 Mock**뿐이다.
> 실제 LLM, 텍스트 추출, 입력 마스킹, 토큰·비용 기록은 PM 승인 전까지 **HOLD**다.

## 1. 구조

```
Router (app/routers/document_analyses.py)
  -> DocumentAnalysisService (app/services/document_analyses.py)   POST 접수 / GET 조회 / apply
  -> SqlAnalysisRepository (app/repositories/document_analyses.py) 기존 0001 테이블만 사용
       재사용: T49 SqlDocumentRepository.get (소유자 + FOR UPDATE)
              T31 SqlPrivacyRepository.latest_consent / current_policy
              T33 SqlMySkillsRepository.usable_skill_ids / list_skills
AnalysisWorker (같은 서비스 모듈) — 단발성: python -m app.document_analysis_worker [--max-jobs N]
  -> AnalysisProvider(Protocol) -> MockAnalysisProvider (app/services/analysis_provider.py)
```

- T49 워커(`app.document_worker`, scanning/deleting)와 **별도 모듈**이다. T49 코드는 변경하지 않았다.
- API 서버 시작 시 분석을 실행하지 않는다. 예약 실행(cron 등)도 추가하지 않았다.
- 새 DDL·Migration·Seed 없음. `career.document_analyses`, `career.model_versions`, `career.user_skills`만 사용한다.

## 2. API (T06 `docs/api/openapi.yaml`)

| operationId | 경로 | 성공 | 오류 |
|---|---|---|---|
| requestDocumentAnalysis | `POST /api/v1/documents/{document_id}/analyses` | 202 + `Location`, `Retry-After: 3` | 401, 404 타인/없는 문서, 409 `DOCUMENT_NOT_READY`, 403 `CONSENT_REQUIRED`, 422, 429 `RATE_LIMITED` |
| getDocumentAnalysis | `GET /api/v1/document-analyses/{analysis_id}` | 200 (queued/running이면 `Retry-After: 3`) | 401, 404 |
| applyDocumentAnalysis | `POST /api/v1/document-analyses/{analysis_id}/apply` | 200 내 기술 전체 | 401, 404, 409 `CONFLICT`(succeeded 아님), 422 |

검사 순서(POST): 소유 문서 404 → `status=ready` 아니면 409 → 유효한 `llm_processing` 동의 없으면 403.
요청 본문은 `{"analysis_type": "skill_extraction" | "summary"}`만 허용(`extra=forbid`). `user_id`, `model_version`을 넣으면 422다.

```http
POST /api/v1/documents/7c9e.../analyses
Authorization: Bearer <JWT>
{"analysis_type": "skill_extraction"}

202 Accepted
Location: /api/v1/document-analyses/1a3c...
Retry-After: 3
{"analysis_id":"1a3c...","document_id":"7c9e...","analysis_type":"skill_extraction","status":"queued",
 "result":null,"error_code":null,
 "model_version":{"model_code":"resume_analysis_mock","version":"mock-fixture-v1","kind":"rule"},
 "requested_at":"2026-11-09T09:00:00Z","completed_at":null}

POST /api/v1/document-analyses/1a3c.../apply
{"skills":[{"skill_id":"<결과에 있던 skill_id>","proficiency":3}]}
```

- **중복 요청**: 같은 문서·같은 `analysis_type`의 queued/running 분석이 있으면 새로 만들지 않고 그 분석을 202로 돌려준다. 문서 행 잠금(FOR UPDATE)으로 동시 요청을 직렬화한다.
- **사용자당 활성 분석 상한**: queued+running 5건. 초과 시 429 `Retry-After: 30`.
- 문서가 `deleting`이면 해당 분석 GET/apply는 404다(결과 비노출). T49 purge 시 FK CASCADE로 분석 행도 삭제된다.

## 3. 상태 전이와 워커 경계

```
queued --(claim: SELECT … FOR UPDATE SKIP LOCKED)--> running --> succeeded | failed
queued  : requested_at + 30분 경과         -> failed(TIMEOUT)
running : requested_at + 60분 경과(워커 중단) -> failed(TIMEOUT)
running : 저장소 일시 장애                   -> queued (해당 실행은 즉시 중단, 다음 실행에서 재시도; 30분 TTL로 상한)
```

- **최종 기록은 조건부**: `UPDATE … WHERE status='running'`. 다른 워커·만료 처리로 상태가 바뀌었으면 늦게 끝난 결과는 버려진다(단일 기록자).
- **재확인 2회**: 문서를 읽기 전과 결과 저장 직전에 문서 소유·`ready`·동의를 다시 확인한다. 삭제·동의 철회가 발생하면 결과를 저장하지 않고 `failed`로 기록한다.
- **자동 재시도 없음**(failed는 최종). 사용자가 새로 요청한다.
- **한도**: 1회 실행 최대 20건(`--max-jobs` 1~100), 호출당 30초 timeout, 실행당 300초 이후 새 작업을 claim하지 않음. 문서는 T49에서 10MB 이하.
- **오류 코드**(T06 enum): `TIMEOUT`, `PROVIDER_ERROR`(예외·출력 검증 실패), `UNREADABLE_DOCUMENT`(문서 미준비/삭제, 크기·SHA-256 불일치, 읽기 실패).
- **로그**: 실행별 건수만 기록한다. analysis/document ID, 파일명, 저장 키, 문서 내용, provider 예외 메시지는 남기지 않는다.

## 4. 동의 정책

`llm_processing`의 **가장 최근** `user_consents` 행이 `granted=true`이고, 그 `policy_version`이 현재 시행 중인 정책 버전과 같을 때만 유효하다. 정책 버전이 바뀌면 다시 동의해야 한다(보수적 해석, PM 확인 필요). 요청 시와 워커 실행 시 모두 검사한다.

## 5. Mock 분석기와 한계

- `MockAnalysisProvider`는 `analysis_type`만 보고 코드 안의 **합성 fixture**를 돌려준다. 문서 내용을 파싱하거나 해석하지 않는다. 따라서 문서 속 "이전 지시를 무시하라" 같은 문장은 출력에 영향을 줄 수 없다(테스트로 확인).
  - `skill_extraction`: PYTHON(3), SQL(2) 후보와 합성 근거 문장. 카탈로그에 없거나 비활성인 코드는 버린다.
  - `summary`: 합성 요약 문장 + 합성 경력 1건.
- `model_versions`에 `resume_analysis_mock` / `mock-fixture-v1`, **`kind=rule`**, `approved_at=NULL`, 설명 "no LLM or external call"로 기록한다. LLM 결과나 승인된 모델로 표시하지 않는다.
- `ai_usage_records`는 **기록하지 않는다**. Mock에는 실제 토큰·비용이 없으므로 숫자를 만들어 내지 않는다.
- PDF/DOCX **텍스트 추출은 구현하지 않았다**. 무결성(크기·SHA-256)만 검사한다.
- 분석 결과는 사용자 기술에 **자동 반영하지 않는다**. apply는 결과에 있는 기술 중 사용자가 고른 것만, T33 정책(활성 기술 또는 이미 보유한 기술)으로 **추가·숙련도 갱신**한다. 고르지 않은 기존 기술은 지우지 않는다(전체 교체 아님). 적용 후 보유 기술이 100개를 넘으면 422.

## 6. 테스트·재현

```powershell
cd backend
python -m pytest -q tests/test_document_analyses.py          # 합성 31건 (Fake 저장소 + 실제 T15 인증 + HTTP)
python -m pytest -q                                          # 전체 회귀
# 일회용 PostgreSQL만 사용 (스키마를 DROP/CREATE 한다. 공유 DB 금지)
$env:T15_TEST_DATABASE_URL="postgresql://<user>:<pw>@127.0.0.1:<port>/<disposable_db>"
$env:T15_SCHEMA_SQL="../database/migrations/0001_initial_schema.sql"
python -m pytest -q tests/test_document_analyses_postgres.py  # E2E 2건
```

PostgreSQL E2E는 T49 POSIX 전용 디렉터리 저장소 대신 테스트용 메모리 저장소를 쓰고, 문서 행은 `ready` 상태의 합성 데이터로 넣는다. T49 purge(`run_batch`)는 실제 코드로 실행한다.

## 7. HOLD / PM 결정 필요

1. 실제 LLM 제공자·데이터 처리 계약·입력 마스킹·프롬프트 버전 관리·토큰/비용 기록 정책.
2. 동의 철회로 실패한 분석의 `error_code`: T06 enum에 맞는 값이 없어 `null`로 둔다. 새 코드(예: `CONSENT_REVOKED`)는 계약 변경이 필요하다.
3. Mock의 `model_versions.kind`: `rule`로 기록했다(T06 예시는 `llm`). 실제 LLM 연동 시 별도 버전으로 등록한다.
4. 동의 유효 기준(현재 정책 버전 일치 요구)과 사용자당 활성 분석 5건 상한.
5. 워커 실행 주기·운영 배치는 범위 밖(예약 실행 없음).
