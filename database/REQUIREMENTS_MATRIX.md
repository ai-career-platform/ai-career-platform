# D1-6 기능 요구사항 ↔ DB 설계 추적표

> 상태: **REVIEWED / REQUIREMENTS INCOMPLETE / NOT APPROVED / NOT DEPLOYED**  
> 검토일: 2026-11-06 · 대상: PR #5의 `database/README.md` (10개 초기 테이블 후보)

## 1. 검토 근거와 증거 수준

1. GitHub `main`의 `README.md`: job matching, skill gap analysis, ML recommendations, RAG, LLM agents, full-stack development를 **서비스 방향**으로 소개.
2. 아직 Open 상태인 **PR #2**의 `docs/ARCHITECTURE.md`: 사용자·프로필·직무·기술·기업·채용공고를 공통 핵심 도메인으로 제안. 실제 화면 72개와 API는 미확정.
3. PR #2 `docs/AI_FEATURES.md`: AI/ML 7종, RAG/Agent는 구상·개발 원칙. 데이터 모델 확정 증거가 아님.
4. PR #2 `docs/DATABASE.md`: 초기 20~25개 테이블·Seed 건수는 **추정/예시**. PM/JM 승인 및 자동 배포와 Migration 분리 원칙.
5. GitHub `main`의 실제 파일: `poc/staging` 기반 PoC 구성뿐이며 본 서비스의 최종 화면/API 스펙이나 확정 ERD는 발견되지 않음.
6. Ubuntu 사용자가 실행한 PostgreSQL 읽기 전용 조회: 사용자 정의 테이블 0개, 비시스템 스키마 `public`, 비시스템 역할 `ai_career_poc`(SUPERUSER). 이는 DB 상태 증거이며 기능 요구사항 승인이 아님.
7. GitHub Issue 목록(2026-11-06 기준)에는 PR #2/#5 및 배포 PR 외에 확정적인 기능별 User Story/수용기준 이슈를 확인하지 못함. **Redmine·별도 기획 자료는 미확인**.

## 2. 도메인별 추적 매트릭스

| 도메인 / 사용자 시나리오 | 근거 | 매핑된 테이블 | 설계 적합성 | 누락/결정 필요 |
|---|---|---|---|---|
| 사용자 식별 및 프로필 | ARCHITECTURE 공통 핵심 | `users`, `user_profiles` | **부분** | 로그인/SSO, 역할, 개인정보 동의·삭제·공개 범위 미확정 |
| 직무 분류·기술 사전 | ARCHITECTURE 공통 핵심 | `job_roles`, `skills`, `job_role_skills` | **기본 구조 적합** | 분류 코드 출처/수준 기준/버전/동의어 미확정 |
| 개인 기술·Skill Gap 기초 | README 및 AI_FEATURES | `user_skills`, `job_role_skills` | **부분** | 역량 증거·숙련도 척도·목표 직무·Gap 계산/저장 정책 미확정 |
| 기업·채용공고 기본 목록 | ARCHITECTURE 공통 핵심 | `companies`, `job_postings`, `job_posting_skills` | **부분** | 공고 수집권한·외부 ID·중복·게시기간·검색/필터 요구사항 미확정 |
| 공고 북마크 | PR #5 설계 가정 | `user_job_bookmarks` | **요구 근거 없음** | MVP 사용자 스토리로 확인하거나 D1 목록에서 제외 |
| 직무 매칭·추천 | README 및 AI_FEATURES 기획 | 현재 핵심 10개는 입력 데이터만 제공 | **불충분** | 점수·설명·모델 버전·피드백·평가 저장 계약은 후속 확장으로 분리 |
| 이력서·LLM 문서 분석 | AI_FEATURES 기획 | 해당 없음 | **범위 밖** | 파일·보관·접근 통제·민감정보 처리 결정 후 별도 설계 |
| RAG 및 Agent 실행 | README / AI_FEATURES 기획 | 해당 없음 | **범위 밖** | 문서 권한·청크·실행 로그·도구 승인·비용은 후속 단계 |
| 관리자/운영 권한·감사 | DATABASE / SECURITY 운영 정책 | 현재 사용자 역할/감사 테이블 없음 | **불충분** | DB 역할과 서비스 RBAC는 별개. 관리자 화면·감사 요구 정의 필요 |

**판정:** 10개 테이블은 *초기 도메인 스케치*로는 일관성이 있으나, 실제 서비스 MVP 충족성을 확인할 기능별 API/화면/수용기준이 부족합니다. **D1 승인 또는 D2 실행 가능 판정 불가(HOLD)**.

## 3. D1 승인에 필요한 결정 목록 (PM/JM 검토)

| 중요도 | 결정 | DB에 미치는 영향 | 승인 증거 |
|---|---|---|---|
| 필수 | MVP 실제 기능·화면·API 목록과 사용자 역할 | 테이블 추가/삭제 및 외래키 | 사용자 스토리/수용기준/화면-API 매핑 |
| 필수 | 인증/인가: 외부 IdP vs 자체 인증 및 서비스 RBAC | `users` 키, identity/roles/consents 테이블 | 인증 아키텍처 결정 |
| 필수 | 실제 기업·공고 데이터 수급 경로·법적 이용 범위 | 소스 ID, 중복·보존 모델 | 데이터 계약·출처 목록 |
| 필수 | Skill Gap 기준: 기술 분류/점수 범위/목표 직무 | 관계 테이블 컬럼/제약조건 | 계산 규칙 및 예시 2~3건 |
| 필수 | 북마크 기능의 MVP 포함 여부 | `user_job_bookmarks` 유지/제외 | 화면/요구사항 확인 |
| 필수 | 이메일 정규화·중복·탈퇴·삭제 정책 | UNIQUE/NULL/삭제 연쇄 | 개인정보/계정 정책 |
| 필수 | DB 백업/복원 및 테이블 소유자·Migration 도구 | DDL/GRANT/스키마 버전 | 백업 검증 증빙, 권한 계획 |
| 필수 | Seed 데이터 구성, 검증 기준 | Seed SQL/테스트 | 합성 데이터 범위·멱등성 |

## 4. D2 착수 게이트

- [x] PR #5의 10개 후보 테이블, 컬럼/PK/FK/자료형 초안
- [x] 사용자 조회로 현재 Staging DB 사용자 테이블 0개/역할 현황 확인
- [x] 기능 ↔ 데이터 도메인 **잠정 추적 매트릭스** 작성
- [ ] MVP 화면·API·서비스 역할 수용기준 확정 및 PR #5 매핑 갱신
- [ ] 보안·개인정보·데이터 출처 정책 반영
- [ ] DB 백업/복원 가능성 검증 및 D2 실행 계획 승인
- [ ] PR #2의 최신 운영 문서 현행화(자동 배포는 이미 활성·검증되어 일부 기록이 오래됨)
- [ ] PM/JM D1 스키마 명시적 승인

**금지:** 위 미결정 상태에서 Staging에 DDL/Seed/권한 변경을 실행하거나 PR #5를 `main`으로 Merge하지 않음.

## 5. 후속 작업 권장

**D1-7:** 실제 요구사항 원본(Redmine/기획서/화면 목록/API 명세)을 확보하여 이 매트릭스의 미확정 항목을 닫고 승인 가능한 초기 테이블 목록을 확정한다. Redmine 정보를 보지 않은 상태로 사용자 역할이나 CRUD 세부 내용을 상상하여 채우지 않는다.
