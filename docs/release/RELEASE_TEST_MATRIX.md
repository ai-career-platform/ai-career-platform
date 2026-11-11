# T90 — 릴리스 시험 매트릭스

> 기준 main `1f3cecd` · 2026-11-11 · 구분: MAIN / PR / MOCK / ISOLATED / STAGING-RO / NOT_VERIFIED ([Gate 문서](FINAL_RELEASE_GATE.md) §1)
> 미병합 PR의 결과는 main 검증 결과로 표시하지 않습니다.

| 영역 | 시험 | 위치 | 결과 | 구분 |
|---|---|---|---|---|
| CI | main 모든 workflow (CI, Backend tests, T49 E2E, Crawler MVP, Publish) | GitHub Actions | PASS | MAIN |
| Backend 단위·통합 | `backend/tests` (PostgreSQL 18.1 서비스 포함) | `backend-tests.yml` | PASS (T86 병합 기준 1236 passed / 53 skipped) | MAIN |
| 보안 회귀 | 인증·인가·IDOR·SQLi·CORS·업로드·로그 (424건) | `backend/tests/security` | PASS | MAIN |
| 개인정보 E2E | 철회·탈퇴 전파, 삭제/보존 분류, purge 사전 검증 | `backend/tests/test_t87_privacy_e2e_postgres.py` | PASS (5) | PR #189 / ISOLATED |
| 개인정보 물리 삭제 | 보존 기간 경과 후 purge | — | **NOT_IMPLEMENTED (HOLD)** | — |
| 문서 업로드 E2E | 실제 서버·파일 보안 | `t49-upload-e2e.yml` | PASS | MAIN |
| 성능 기준선 | 7개 API, 동시성 1~16·32 | `backend/perf/t88_baseline.py` | 측정 완료(기준 미승인) | PR #190 / ISOLATED |
| AI 성능 | Mock 분석 worker | 같음 | 건당 약 6 ms | PR / MOCK |
| 접근성 자동 | 19개 화면 규칙·키보드·모달·대비 | `frontend/src/a11y` | PASS (35) | PR #191 |
| 접근성 브라우저 | Chrome 156·Edge 157, 1280/375/200% | `frontend/scripts/a11y-browser-check.mjs` | PASS | PR / ISOLATED |
| 스크린리더·Firefox·Safari | — | — | NOT_RUN | NOT_VERIFIED |
| Frontend | typecheck·lint·Vitest·build·check:api | `frontend-ci` | PASS | MAIN |
| 관리자 감사·비용 화면 | Mock Adapter, 계약 시험 | T85 | PASS | MAIN / MOCK |
| 백업·복원 | pg_dump → pg_restore, 내용 md5·객체 수·앱 연결 | `database/tests/t90_backup_restore_drill.py` | PASS | ISOLATED (이 PR) |
| Staging 버전·Health | `/api/version` = main HEAD, `/`·`/api/health`·`/api/health/db` 200 | GET | PASS | STAGING-RO |
| Staging 실행 이미지 digest | 호스트 `docker inspect` | — | NOT_VERIFIED | — |
| Staging DB 스키마 | 0002·0003 적용, 원장 | PR #178 | **FAIL (미적용)** | — |
| Staging 사용자 화면 E2E | React 앱 | — | NOT_VERIFIED (미배포) | — |
| Staging 실제 백업 복원 | — | — | NOT_VERIFIED | — |
| 운영 | — | — | NOT_VERIFIED (운영 환경 없음) | — |

## 백업·복원 훈련 결과 (ISOLATED, 2026-11-11)

| 항목 | 값 |
|---|---|
| PostgreSQL / pg_dump | 18.6 / 18.6 (Staging은 18.1 — 같은 18 계열, 운영 버전으로 재훈련 권장) |
| 원본 | Migration 0001~0003 + Seed + 합성 사용자 200·경험·감사·AI 사용량 |
| 덤프 | custom 형식(`-Fc`, `--no-owner --no-privileges`), 약 204 KB, 0.14초, 목차 321항목, sha256 기록 |
| 복원 | `pg_restore --exit-on-error`, 0.46초 |
| 비교 | 표 51개 **내용 md5 전부 일치**(2,058행), 제약 458·인덱스 138·FK 78 동일 |
| 앱 연결 | 복원 DB에 `create_app()` → `/health/db` 200, `/api/v1/job-roles` 200 (5건) |
| 정리 | 원본·복원 DB 삭제, 덤프 파일 삭제(합성 데이터만 포함) |
| 원자료 | [`T90_BACKUP_RESTORE_DRILL.json`](T90_BACKUP_RESTORE_DRILL.json) |

한계:
- 역할·권한은 덤프에 넣지 않았습니다(`--no-owner --no-privileges`). 실제 복원 시에는 권한 스크립트를 따로 적용해야 합니다.
- Migration 원장(`career_migration`)이 없는 기준선 상태는 PR #178 범위입니다.
