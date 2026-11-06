# AI Career Platform — 1차 일감 30개 작업지시서

> 작성 기준: 2026-11-06 · 상태: **담당자 배정·개별 착수 전 검토용** · 기준 브랜치: `main`
>
> 목적: DB/Backend/Frontend/AI/QA 개발자가 일감별 요구·산출물·검증 기준을 정확히 확인하고 **개인 브랜치에서 독립적으로 수행**하도록 표준화. 실제 담당자와 날짜는 **미배정**이며 일정 확정 및 Redmine 등록 전 초안입니다.

## 사용 방법

1. PM/PL이 선행조건과 미확정 요구사항을 검토해 담당자·기간·Redmine 이슈를 배정합니다.
2. 각 개발자는 아래에서 자신의 **T번호 문서를 열고 담당자 확인 체크리스트**를 먼저 검토합니다.
3. 신규 브랜치 `task/t##-short-name`에서 작업하고, Pull Request에 **실행 명령/테스트/화면·Swagger 증빙**을 첨부합니다.
4. `PASS`는 해당 일감의 완료 기준을 실제 검증했을 때만 사용합니다. 미확인·선행 의존성·권한 부족은 `PARTIAL` 또는 `HOLD`로 남깁니다.
5. PM/JM의 별도 승인 없이 Staging DB DDL·Seed 변경 또는 기존 운영/자동배포 설정을 변경하지 않습니다.

## 일감 목록 및 개별 지시서

| ID | 일감 | 담당 영역 | 담당자 | 상태 |
|---|---|---|---|---|
| [T01](T01.md) | DB 개발환경 세팅 가이드 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T02](T02.md) | Backend 개발환경 세팅 가이드 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T03](T03.md) | Frontend 개발환경 세팅 가이드 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T04](T04.md) | 전체 기능·화면 요구사항 기준선 확정 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T05](T05.md) | 전체 DB ERD 및 테이블 계약 확정 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T06](T06.md) | 전체 API·DTO 계약 확정 | 공통 환경·설계 | 미배정 | NOT_STARTED |
| [T07](T07.md) | DB 계정·권한·접근 제한 검증 | Database | 미배정 | NOT_STARTED |
| [T08](T08.md) | PostgreSQL Migration 체계 구축 | Database | 미배정 | NOT_STARTED |
| [T09](T09.md) | 전체 DB Schema 생성 SQL 작성 | Database | 미배정 | NOT_STARTED |
| [T10](T10.md) | 초기 Seed·Fixture 데이터 제작 | Database | 미배정 | NOT_STARTED |
| [T11](T11.md) | DB 제약조건·인덱스·권한 테스트 | Database | 미배정 | NOT_STARTED |
| [T12](T12.md) | 승인된 Staging Migration·Seed 적용 | Database | 미배정 | NOT_STARTED |
| [T13](T13.md) | FastAPI 애플리케이션 골격 구축 | Backend | 미배정 | NOT_STARTED |
| [T14](T14.md) | PostgreSQL DB 연결·세션 수명주기 | Backend | 미배정 | NOT_STARTED |
| [T15](T15.md) | 인증·인가 API 구현 | Backend | 미배정 | NOT_STARTED |
| [T16](T16.md) | 사용자 프로필 CRUD API | Backend | 미배정 | NOT_STARTED |
| [T17](T17.md) | 직무·기술 조회·검색 API | Backend | 미배정 | NOT_STARTED |
| [T18](T18.md) | 기업·채용공고 조회·검색 API | Backend | 미배정 | NOT_STARTED |
| [T19](T19.md) | Frontend 프로젝트 기본 구조·실행 | Frontend | 미배정 | NOT_STARTED |
| [T20](T20.md) | Frontend 공통 레이아웃·UI 컴포넌트 | Frontend | 미배정 | NOT_STARTED |
| [T21](T21.md) | 로그인·사용자 인증 UI | Frontend | 미배정 | NOT_STARTED |
| [T22](T22.md) | 사용자 프로필 조회·수정 UI | Frontend | 미배정 | NOT_STARTED |
| [T23](T23.md) | 직무·기술 탐색 UI | Frontend | 미배정 | NOT_STARTED |
| [T24](T24.md) | 기업·채용공고 탐색 UI | Frontend | 미배정 | NOT_STARTED |
| [T25](T25.md) | AI·ML 공통 데이터·Feature 계약 | AI/ML | 미배정 | NOT_STARTED |
| [T26](T26.md) | Skill Gap 규칙 기반 Baseline | AI/ML | 미배정 | NOT_STARTED |
| [T27](T27.md) | 직무 적합도·추천 규칙 기반 Baseline | AI/ML | 미배정 | NOT_STARTED |
| [T28](T28.md) | PR·CI·QA 기본 정책 검증 강화 | QA·DevOps | 미배정 | NOT_STARTED |
| [T29](T29.md) | Frontend↔Backend 통합 API 회귀 테스트 | QA·DevOps | 미배정 | NOT_STARTED |
| [T30](T30.md) | 1차 Staging 통합 배포·운영 검증 | QA·DevOps | 미배정 | NOT_STARTED |

## 선행 관계 및 작업 순서

- **즉시 독립 착수:** T01~T04(가이드·기능 요구사항 대조), T28의 현 CI 상태 점검. 환경 가이드는 저장소의 실제 PoC 코드만 근거로 작성합니다.
- **설계 게이트:** T04 완료 후 T05/T06를 확정합니다. S03 전체 46개 테이블은 설계 후보이지 승인된 DDL이 아닙니다.
- **DB 경로:** T07(권한) → T08(Migration 프레임워크) → T09(전체 DDL) → T10(Seed) → T11(제약/권한 테스트) → T12(승인된 Staging 적용). 상세 선행 조건은 각 문서를 따릅니다.
- **앱 병렬:** T13/T19 골격은 합의된 API Mock과 독립 환경으로 병렬 시작 가능. T14~T18/T20~T24는 필요한 기반 기능의 구현 상태에 따라 병합합니다.
- **AI/QA:** T25 공통 계약, T26~T27 baseline, T29 E2E, T30 Staging 검증.

## 현재 환경과 변경 금지 조건

- 메인 저장소에는 `poc/`, `docs/`, `database/`가 존재합니다. 독립된 `backend/`, `frontend/` 소스는 **아직 존재하지 않음**(2026-11-06 확인).
- Staging PostgreSQL 18.1: `ai_career_poc`, 내부망 `10.2.10.104:15432` 프록시 연결 확인. `career_reader` 생성 보고 수신; 권한의 실제 부정 테스트 **아직 필요**.
- `ai_career_poc`는 DB SUPERUSER이므로 개인 개발자에게 비밀번호 공유하지 않음. Backend 로컬 쓰기는 별도 최소권한 로그인 마련 전 HOLD.
- 내부망 프록시 포트는 기동/TCP 연결을 검증했으나 접근 제한·전송 암호화의 완료 증빙은 아직 없습니다.
- 기존 Ubuntu Auto-CD는 Compose SHA를 보호함. `compose.yaml`, `automation/config.json` 등 운영 파일을 실습 편의로 수정하지 않습니다.
- **절대 금지:** `docker compose down -v`, 글로벌 Docker prune, 실제 DB 초기화, 공개 채널 비밀번호/Token 게시.

## 공통 PR 증빙 템플릿

```text
[AI Career Platform 일감 작업 완료 보고]
- 일감 ID / 제목:
- 담당자:
- Redmine Issue: (미등록이면 NONE)
- 브랜치 / PR URL:
- 구현/문서 변경 범위:
- 선행조건 완료: YES / HOLD
- 로컬 실행·테스트 명령:
- 정상/예외 증빙:
- CI run URL / SHA:
- DB Schema 또는 Seed 변경: YES / NO
- Staging 서비스 변경: YES / NO
- 보안·복구·특이사항:
- 최종 상태: PASS / PARTIAL / HOLD
```

## 관련 설계 문서

- [전체 기능/화면/API/DB 매핑](../../FULL_SCOPE_TRACEABILITY.md)
- [전체 API 계약](../../API_CONTRACT.md)
- [전체 DB 모델](../../../database/FULL_DATABASE_MODEL.md)
- [AI 시스템 설계](../../AI_SYSTEM_ARCHITECTURE.md)
- [협업 가이드](../../CONTRIBUTING.md)
- [DB 변경 정책](../../DATABASE.md)

**판정:** `WORK_ORDERS_30=AUTHORED`, `ASSIGNEES=PENDING`, `SCHEDULE=PENDING`, `REDMINE_ISSUES=NOT_CREATED`. 문서 작성 완료는 기능 구현 완료를 뜻하지 않습니다.
