# AI Career Platform — Windows 11 개발자별 로컬 설정 가이드

> 2026-11-06 기준 main SHA `2338031c2dfdcf14c2a7ddba01800cffba10be41`. 본 문서는 설치·실습 절차이며, 개별 Windows PC에서의 성공 여부는 직접 실행 후에만 PASS 처리합니다.

| 담당자 | 가이드 | 현행 구현 스택 |
|---|---|---|
| DB | [DB_DEVELOPMENT_SETUP.md](DB_DEVELOPMENT_SETUP.md) | DBeaver / PostgreSQL 18.1, 개인 로컬 격리 DB |
| Backend | [BACKEND_DEVELOPMENT_SETUP.md](BACKEND_DEVELOPMENT_SETUP.md) | Python + FastAPI 0.115.12 / Uvicorn 0.34.2 / psycopg 3.2.9 |
| Frontend | [FRONTEND_DEVELOPMENT_SETUP.md](FRONTEND_DEVELOPMENT_SETUP.md) | **React** + Node.js LTS/npm (React 구조는 T19에서 생성) · 현행 PoC: 정적 HTML/CSS/JavaScript + Nginx |

**실제로 구현된 API:** FastAPI `/health`, `/version`, `/health/db` (Nginx 경유 `/api/health`, `/api/version`, `/api/health/db`).

**아직 설계 후보:** F-001~F-030 기능 30개, 데이터 모델 46개 엔터티 및 UI/API 계약. DRAFT 초기 10개 테이블의 격리 검증은 Staging 스키마 구축을 의미하지 않습니다.

**공유 시스템 주의:** Staging PostgreSQL `10.2.10.104:15432`, DB `ai_career_poc`. `career_reader`의 실제 최소권한 검증은 HOLD. `ai_career_poc`은 SUPERUSER이므로 개발자에게 비밀번호를 배포하지 않습니다. 백엔드 쓰기 테스트용 전용 최소권한 LOGIN 계정은 아직 준비되지 않았습니다. 네트워크 ACL/TLS 정책도 최종 확인 전입니다. 승인 없는 Staging SQL 변경·볼륨 삭제·Migration·Seed 수행 금지.

**진행 순서:** 각 가이드의 1~11절 수행 → 로컬 실행/오류/보안 경계 증빙 → 개인 브랜치 PR → CI 및 PM/JM 리뷰. PM 승인 없이 main Merge 금지.

**근거 문서:** [온보딩](../ONBOARDING.md) · [운영 가이드 인덱스](../README.md) · [DB 규정](../DATABASE.md) · [전체 설계](../FULL_SCOPE_DESIGN_PLAN.md) · [기능 추적표](../FULL_SCOPE_TRACEABILITY.md) · [API 초안](../API_CONTRACT.md) · [AI 설계](../AI_SYSTEM_ARCHITECTURE.md) · [DB 전체 모델](../../database/FULL_DATABASE_MODEL.md) · [실제 PoC](../../poc/staging/README.md) · [Staging 운영](../STAGING.md) · [CI/CD](../CI_CD.md).


## 테스트 자동화·결과 보고 (현재 main 기준)

- 테스트 공통 가이드: [docs/testing/README.md](../testing/README.md)
- Backend 정식 코드: [pytest 실행·JUnit XML](../testing/PYTEST_GUIDE.md) — `backend/requirements-dev.txt` 사용
- React Frontend: [Vitest 테스트](../testing/VITEST_GUIDE.md) — `frontend/package.json` 사용
- 브라우저 E2E: [Playwright 도입 가이드](../testing/PLAYWRIGHT_GUIDE.md) — **아직 미설치/미구현**
- PR·Redmine: [테스트 증빙 정책](../testing/TEST_EVIDENCE_GUIDE.md) 및 [보고서 양식](../testing/TEST_REPORT_TEMPLATE.md)

**기존 본문 일부는 T19/정식 Backend 구축 이전에 작성되었습니다.** 현재 저장소에는 `frontend/package.json`, `backend/requirements.txt`, `backend/requirements-dev.txt`가 존재합니다. 개발자들은 담당 영역의 현재 설치 파일을 우선하고, 운영 PoC와 정식 개발 코드의 라이브러리/테스트를 혼용하지 마세요. 실제 검증 결과를 받기 전에는 PASS가 아닙니다.
