# AI Career Platform — Windows 11 개발자별 로컬 설정 가이드

> 2026-11-06 기준 main SHA `2338031c2dfdcf14c2a7ddba01800cffba10be41`. 본 문서는 설치·실습 절차이며, 개별 Windows PC에서의 성공 여부는 직접 실행 후에만 PASS 처리합니다.

| 담당자 | 가이드 | 현행 구현 스택 |
|---|---|---|
| DB | [DB_DEVELOPMENT_SETUP.md](DB_DEVELOPMENT_SETUP.md) | DBeaver / PostgreSQL 18.1, 개인 로컬 격리 DB |
| Backend | [BACKEND_DEVELOPMENT_SETUP.md](BACKEND_DEVELOPMENT_SETUP.md) | Python + FastAPI 0.115.12 / Uvicorn 0.34.2 / psycopg 3.2.9 |
| Frontend | [FRONTEND_DEVELOPMENT_SETUP.md](FRONTEND_DEVELOPMENT_SETUP.md) | 정적 HTML/CSS/JavaScript + Nginx (**Node 프레임워크 미도입**) |

**실제로 구현된 API:** FastAPI `/health`, `/version`, `/health/db` (Nginx 경유 `/api/health`, `/api/version`, `/api/health/db`).

**아직 설계 후보:** F-001~F-030 기능 30개, 데이터 모델 46개 엔터티 및 UI/API 계약. DRAFT 초기 10개 테이블의 격리 검증은 Staging 스키마 구축을 의미하지 않습니다.

**공유 시스템 주의:** Staging PostgreSQL `10.2.10.104:15432`, DB `ai_career_poc`. `career_reader`의 실제 최소권한 검증은 HOLD. `ai_career_poc`은 SUPERUSER이므로 개발자에게 비밀번호를 배포하지 않습니다. 백엔드 쓰기 테스트용 전용 최소권한 LOGIN 계정은 아직 준비되지 않았습니다. 네트워크 ACL/TLS 정책도 최종 확인 전입니다. 승인 없는 Staging SQL 변경·볼륨 삭제·Migration·Seed 수행 금지.

**진행 순서:** 각 가이드의 1~11절 수행 → 로컬 실행/오류/보안 경계 증빙 → 개인 브랜치 PR → CI 및 PM/JM 리뷰. PM 승인 없이 main Merge 금지.

**근거 문서:** [온보딩](../ONBOARDING.md) · [운영 가이드 인덱스](../README.md) · [DB 규정](../DATABASE.md) · [전체 설계](../FULL_SCOPE_DESIGN_PLAN.md) · [기능 추적표](../FULL_SCOPE_TRACEABILITY.md) · [API 초안](../API_CONTRACT.md) · [AI 설계](../AI_SYSTEM_ARCHITECTURE.md) · [DB 전체 모델](../../database/FULL_DATABASE_MODEL.md) · [실제 PoC](../../poc/staging/README.md) · [Staging 운영](../STAGING.md) · [CI/CD](../CI_CD.md).
