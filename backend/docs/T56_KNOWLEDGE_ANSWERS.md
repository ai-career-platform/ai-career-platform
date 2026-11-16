# T56 RAG Q&A API·인용 근거 검증 — 구현 기록 (mock 범위)

Redmine #1560 · 작업지시서 `docs/work-orders/next-30/T56.md` · FR-AI-003 / F-022 · 브랜치 `task/t56-knowledge-answers`
상태 **PARTIAL** — 선행 T53(청킹·색인)·T54(권한 기반 검색) 미완료, LLM 제공자·데이터 처리 계약 미승인.
권한 필터·실행 기록·인용 검증은 **실제 DB**로 동작하고, 청크 본문·검색·답변 생성만 교체 가능한 mock이다.

## API — `POST /api/v1/knowledge/answers` (operationId `askKnowledge`)

| 항목 | 내용 |
|---|---|
| 요청 | `question`(2~1000자, 공백만 불가), `document_ids`(선택, 최대 20, 중복 불가). 추가 필드·쿼리 문자열 422 |
| 응답 | `retrieval_run_id`, `status`(answered / no_evidence), `answer`(no_evidence면 null), `citations[]`(rank, document_id, document_title, chunk_index, score), `limitations[]` |
| 오류 | 401 인증, 422 입력, 503 생성 실패, 504 생성 시간 초과. 공통 `{code, status, message}` |
| 헤더 | `Cache-Control: no-store` |

## 흐름

`routers/knowledge.py` → `services/knowledge.py` `KnowledgeService.answer`
1. `document_ids` 지정 시 접근 가능한 문서만 남김. 빠진 게 있으면 "일부 제외" 안내만 하고 **어떤 문서인지는 알리지 않음**
2. `retrieval_runs`에 `running` + **질문 sha256** 기록 후 커밋 (질문 원문 저장·로그 안 함)
3. `repositories/knowledge.py` SQL로 **내 문서 또는 공용(shared), status=ready** 문서의 청크만 조회 (최대 500)
4. 검색기 → 점수 0.2 미만 제외, 상위 5개 → 문맥 4000자 상한(`fit_context`)
5. 생성기 → **인용 검증**(`verify_citations`): 인용이 이번 검색 결과에 있고 권한 확인된 청크여야 함.
   하나라도 아니면 **답변 전체 폐기** → no_evidence ("확인되지 않은 인용…")
6. 결과 기록: answered면 `retrieval_citations`(rank·score)와 모델 버전, no_evidence/failed면 모델 없음

## FR-AI-003 수용 기준 대응

| 기준 | 구현 | 테스트 |
|---|---|---|
| 1. 근거 1개 이상, 없으면 답변 안 함 | 검증된 인용 0개 → `no_evidence`, `answer=null` | 본문 없음·무관 질문·인용 없음·허위 인용 |
| 2. 다른 사용자 문서 사용 금지 | SQL 권한 필터 + 인용 재검증(2중) | 남의 비공개 문서 지정·검색·인용 시도 (메모리·PostgreSQL) |
| 3. 문서 속 지시문 따르지 않음 | 지시문 패턴 문장은 근거에서 제거, 안내 문구 추가. 생성기는 발췌만 함 | 한·영 인젝션 4종, 정상 문장 오탐 없음 |
| 4. 질문 원문 저장 안 함 | `query_hash`만 저장 | 메모리·DB 모두 원문 미존재 확인 |

작업지시서 §2-3의 "시간초과·비용/토큰 상한·사용자 ACL": 504/503 + run `failed`, 문맥 4000자·상위 5개·스캔 500개 상한, ACL 위와 같음.

## mock으로 대신한 것

| 부분 | 현재 (`services/knowledge_provider.py`) | 실제 연동 시 (`app.state`로 교체) |
|---|---|---|
| 청크 본문 | `UnavailableChunkText` → 본문 없음 → **실서버에서는 항상 no_evidence** | T53 색인 본문 소스 (`knowledge_text_source`) |
| 검색기 | `LexicalMockRetriever` 단어 겹침(조사 단순 제거) | T54 권한 기반 검색 (`knowledge_retriever`) |
| 답변 생성 | `ExtractiveMockGenerator` 근거 문장 발췌, LLM 아님, model kind=`rule` | 승인된 LLM (`knowledge_generator`), 인용 검증은 그대로 유지 |
| 429 요청 한도 | 미구현 | 공통 한도 정책(T06-2) 결정 후 |
| `ai_usage_records` | 기록 안 함 (mock은 토큰·비용 없음, PM T51과 같은 기준) | LLM 연동 시 |

## 확인 필요

1. 접근 불가 `document_ids`를 422가 아니라 "제외 + 안내"로 처리 (계약에 404 없음, 존재 여부 숨김)
2. `model_versions`의 mock 행(`knowledge_answer_mock`/`t56-mock-1`/rule)을 앱이 없으면 생성 (T45·T51과 같은 방식)
3. 점수 기준 0.2·상위 5개·문맥 4000자는 mock 기준값. 실제 검색기 도입 시 재조정

## 검증 (2026-11-09, Windows 11 / Python 3.12.13 / 로컬 일회용 PostgreSQL 18.4)

| 테스트 | 결과 |
|---|---|
| `tests/test_knowledge.py` (API 계약·권한·허위 인용·인젝션·장애·입력, 메모리 저장소) | 38 passed |
| `tests/test_knowledge_postgres.py` (T15 fixture 재사용: 실제 가입·토큰·Session·SQL 권한·기록) | 2 passed |
| Backend 전체 + DB 격리 테스트 (Windows 전용 실패인 T49 `test_documents.py` 제외) | 565 passed, 0 failed |

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_knowledge.py
# 일회용 DB만 (Staging 금지)
$env:T15_TEST_DATABASE_URL="postgresql://<user>@localhost:<port>/<disposable_db>"
$env:T15_SCHEMA_SQL="<repo>/database/migrations/0001_initial_schema.sql"
.\.venv\Scripts\python.exe -m pytest -q tests/test_knowledge_postgres.py
```

공용 Staging DB 접속·변경 없음. Schema/Migration/Seed 변경 없음. 외부 호출·비밀값·실사용자 데이터 없음.
