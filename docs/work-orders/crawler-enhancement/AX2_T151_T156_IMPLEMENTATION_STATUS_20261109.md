# AX 2기 크롤러 T151~T156 구현·검증 현황 (2026-11-09)

Feature #1577, Redmine T151 #1578, T152 #1579, T153 #1580, T154 #1581, T155 #1582, T156 #1583.
기준 `main`: `9efb94c99c8d381862f528f91fb4ee20c7ca954b`.
**GitHub 코드 확인과 사용자 제공 STEP26 보고를 구분한다.** 여기에서 Redmine 상태를 직접 변경하지 않았다. 로컬 Evidence 원본은 GitHub 코디네이터가 직접 열람하지 않았다.

## 상태표

| 일감 | 구현 (GitHub) | 검증 상태/미해결 | 다음 조치 |
|---|---|---|---|
| T151 검색어·수집 Job | `keyword_management.py`, migration 0003/0004, KeywordStore, Audit, seed 6개 | STEP05C 스테이징 메타데이터 PASS; 당시 full Worker E2E HOLD였으나 후속 T154에서 Keyword→Job→Posting 흐름 성공. 기본 CRUD/감사/멱등성 확인 기록 보존 | 기존 T154 E2E와 T151 DoD 대조, Redmine 업데이트 |
| T152 Raw 목록·상세 | `fixture_raw_batch.py`, `raw_artifact_store.py`, migration 0005 | 스테이징 STEP25/26에서 Raw 42개 SHA 검증 **사용자 보고**. 합성 HTML만, Live HTTP 0 | 중복·실패·고아 파일 처리 DoD 별도 확인, Redmine 업데이트 |
| T153 독립 Parse/검증/Lineage | `fixture_parse_pipeline.py`, `raw_parse_ledger.py`, migration 0006, 런타임 advisory xact lock 수정 | T154 STEP26 Raw→Posting/Lineage 28건 및 Checkpoint 성공 **사용자 보고**. 독립 `parser_version` 변경 재처리, INVALID, 최종 INSERT 실패 롤백을 포함한 T153 **전용** 스테이징 Evidence는 현재 기록으로 미확인 | 다음에 **T153 잔여 검증만** 수행; 중복 개발 금지 |
| T154 야간 증분/안전 재개 | `incremental_* / fixture_* / night_* `, migrations 0007..0010, PR #115 | 사용자 STEP26: 2026-11-08~09 자동 Timer 12회, Worker 14/14, 합성 Posting 28건, Raw SHA 42 PASS, 08:00 이후 Job 0, 데이터 보존 PASS. Timer disabled/inactive. GitHub main PR #115 병합 확인 | **Fixture 범위 개발/야간 검증 완료**로 Redmine Evidence 반영. 실제 사이트 수집은 별개 HOLD |
| T155 관리자 API | `T155.md` 요구사항 문서만; 실제 Backend `/api/v1` 등록 라우터 없음 | T15 인증·인가 GitHub issue #48 OPEN/PARTIAL, 현 main 실제 Auth 의존성 미연동. 교육용 `backend/training_jobs_api.py`는 단독 조회 API이며 관리자 인가 아님 | 먼저 T15 통합 가능성 확인; 읽기 전용 API는 역할 검증 없는 외부 노출 금지. T155 단계별 구현 |
| T156 관리자 UI | `T156.md` 기획 문서만 | 관리자 UI 통합 및 인증 E2E 미진행 | T155 인증·조회 API 이후 구현 |

## T154 검증 집계 (사용자 제공 STEP26, 원본 Evidence 로컬 경로)

- `MAIN_SHA=STAGING_SHA=9efb94c99c8d381862f528f91fb4ee20c7ca954b`.
- 최종 Timer 호출 12, Worker 성공 14(수동 2 포함), 실패 0, 수동 중복 IDLE 2, 신규 합성 Posting 28, 전체 Posting 35(기존 7).
- Lineage 28, Raw SHA 검증 42, Checkpoint 2, Attempt COMPLETED 14, 08:00 이후 새 Job 0, 외부 HTTP 요청 0.
- 기존 공고 7개 및 앱 DB 51테이블 지문 보존, T154 전용 Timer/T64 Timer 비활성, DB 세션/자문 잠금 정리, Auto-CD PASS.
- 로컬 원본 증빙: `T154_NIGHT_FINAL_REPORT.md`, `T154_NEXT_DAY_ANALYSIS.md`, `t154-step26-evidence.json`, `t154-step26-stop-check.log`.

## Redmine 동기화 시 주의

Redmine 화면의 T151~T156 `New 0%`은 실제 구현과 불일치. 위 자료와 개별 DoD를 확인하여 상태 변경하는 것이 적절하다. 이 문서는 **Redmine를 실제 갱신하거나 담당자·검토자의 확인을 대신하지 않는다**. T154는 Fixture 기능 범위에서 종료 가능하나 Live 작업을 완료로 표시하지 않는다.

## 즉시 다음 순서

1. T153 누락된 전용 재파싱/INVALID/원자적 실패 롤백 및 런타임 E2E Evidence만 회수/검증.
2. T151/T152/T153/T154 Redmine 진행률·Evidence 동기화(직접 Redmine 액세스가 확인된 뒤).
3. T155 관리자 API 단계 1: T15 issue #48/미병합 Auth 의존성을 먼저 확인. 인증 없는 관리자 CRUD나 임시 토큰 통과 로직 금지.
4. T155 인증 통합 후 T156 UI/QA.
