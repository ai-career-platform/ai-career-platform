# AI Career Platform — 2차 개발 일감 30개 (T31~T60)

> **상태:** 1차 T01~T30 이후의 후속 **개발 후보**. 담당자 미배정, 범위/일정 미승인. 작성일 2026-11-06.
>
> 기존 1차와 중복된 개발환경·공통 프로젝트 골격·규칙 기반 Baseline 구축을 제외하고, 사용자가 접하는 2차 기능의 API ↔ Frontend ↔ AI/RAG/Agent 구현을 중심으로 정리했습니다.

## 작업 시작 규칙

1. `docs/FULL_SCOPE_TRACEABILITY.md` (기능 F-001~F-030), `docs/API_CONTRACT.md`, `database/FULL_DATABASE_MODEL.md`, `docs/AI_SYSTEM_ARCHITECTURE.md`를 검토하고 요구사항 미확정/구현 상태를 구분합니다.
2. **선행 작업의 실제 PASS 또는 승인된 mock 계약**이 있어야 구현을 시작합니다. 기존 T01~T30은 PR #6 작업지시서를 참고하되 PR 상태를 확인하고, 미완료 작업을 자동 완료 처리하지 않습니다.
3. 신청자는 구글 스프레드시트에 이름, GitHub ID, GitHub 이메일, 진행 상태를 작성합니다. GitHub 로그인 이메일이 비공개라면 **담당자가 연락 가능한 공개용 이메일**만 기록하고 비밀정보를 기입하지 않습니다.
4. 담당 확정 후 개인 브랜치와 PR, 테스트 및 화면/Swagger 증빙으로 제출합니다.
5. 공용 Staging DB DDL/Seed 및 운영 컨테이너/자동 배포 변경은 별도 PM 승인 전 금지합니다.

## 일감 목록

| ID | 영역 | 작업명 | 우선순위 | 선행 | 기능 추적 |
|---|---|---|---|---|---|
| [T31](T31.md) | Backend/보안 | 개인정보 동의·탈퇴 요청 Backend API | P0 | T05,T06,T15,T16 | F-005 |
| [T32](T32.md) | Frontend | 개인정보 설정·동의 UI | P1 | T20,T21,T31 | F-005 |
| [T33](T33.md) | Backend | 내 보유 기술·숙련도 API | P1 | T05,T06,T14,T15,T17 | F-008 |
| [T34](T34.md) | Frontend | 내 기술·숙련도 관리 UI | P1 | T20,T21,T23,T33 | F-008 |
| [T35](T35.md) | Backend | 목표 직무 관리 API | P1 | T05,T06,T14,T15,T17 | F-009 |
| [T36](T36.md) | Frontend | 목표 직무 선택 UI | P1 | T20,T21,T23,T35 | F-009 |
| [T37](T37.md) | Backend | 개인 경력·프로젝트 이력 API | P1 | T05,T06,T14,T15,T16 | F-010 |
| [T38](T38.md) | Frontend | 경력·프로젝트 편집 UI | P1 | T20,T21,T22,T37 | F-010 |
| [T39](T39.md) | Backend | 관심 채용공고 북마크 API | P1 | T05,T06,T14,T15,T18 | F-013 |
| [T40](T40.md) | Frontend | 저장한 채용공고 UI | P1 | T20,T21,T24,T39 | F-013 |
| [T41](T41.md) | Backend/AI | 직무·공고 적합도 평가 API | P1 | T15,T17,T18,T25,T27,T33 | F-015 |
| [T42](T42.md) | Frontend | 직무 적합도 결과 UI | P1 | T20,T23,T24,T41 | F-015 |
| [T43](T43.md) | Backend/AI | Skill Gap 분석 API | P1 | T15,T17,T25,T26,T33,T35 | F-016 |
| [T44](T44.md) | Frontend | Skill Gap 결과 UI | P1 | T20,T34,T36,T43 | F-016 |
| [T45](T45.md) | Backend/AI | 개인화 직무·공고 추천 API | P1 | T15,T17,T18,T25,T27,T33,T35 | F-017 |
| [T46](T46.md) | Frontend | 개인화 추천 목록 UI | P1 | T20,T23,T24,T45 | F-017 |
| [T47](T47.md) | Backend/AI | 추천 설명·피드백 API | P1 | T15,T25,T45 | F-018 |
| [T48](T48.md) | Frontend | 추천 설명·피드백 UI | P1 | T20,T46,T47 | F-018 |
| [T49](T49.md) | Backend/보안 | 개인 문서 업로드·보관 API | P1 | T05,T06,T15 | F-019 |
| [T50](T50.md) | Frontend | 개인 문서 관리 UI | P1 | T20,T21,T49 | F-019 |
| [T51](T51.md) | Backend/AI | LLM 기반 이력서 분석 Pipeline·API | P1 | T25,T49 | F-020 |
| [T52](T52.md) | Frontend | 이력서 분석 결과 UI | P1 | T20,T50,T51 | F-020 |
| [T53](T53.md) | AI/Backend | RAG 문서 청킹·색인·권한 동기화 | P2 | T25,T49 | F-021 |
| [T54](T54.md) | Backend/AI | 권한 기반 RAG 검색 API | P2 | T15,T25,T53 | F-021 |
| [T55](T55.md) | Frontend | 근거 기반 지식 검색 UI | P2 | T20,T50,T54 | F-021 |
| [T56](T56.md) | Backend/AI | RAG Q&A API·인용 근거 검증 | P2 | T25,T54 | F-022 |
| [T57](T57.md) | Frontend | 커리어 Q&A 채팅 UI | P2 | T20,T55,T56 | F-022 |
| [T58](T58.md) | AI/Backend/보안 | Agent 승인 기반 실행·감사 API | P2 | T15,T25,T28 | F-023 |
| [T59](T59.md) | Frontend | Agent 실행·승인 이력 UI | P2 | T20,T21,T58 | F-023 |
| [T60](T60.md) | AI/QA/Backend | AI 모델 버전·평가·사용량 운영 API | P1 | T25,T26,T27,T28 | F-026,F-028 |

## Excel / Google Sheets 복사 자료

[`NEXT_30_APPLICATION.tsv`](NEXT_30_APPLICATION.tsv)에는 **헤더 1행 + 일감 30행**, 기존 신청표와 동일한 14개 열이 포함됩니다. 기존 T01~T30 아래 붙여넣을 때는 **헤더 첫 행을 제외**하고 붙여넣습니다. `신청자 이름`, `GitHub ID`, `GitHub 이메일`, `진행 상태`는 신청자가 직접 수정합니다.

## 후속 작업 범위 경계

- F-024 채용시장 추세/예측, F-025 군집·행동·이상탐지, F-027 운영 콘텐츠 검수 및 F-028 감사 시각화·운영 대시보드는 이후 일감 후보로 남습니다.
- 외부 LLM/문서/Agent의 실제 이용은 개인정보·권한·제공자·저장소·비용 등 별도 승인 후 진행합니다.
- Draft 설계에 등장하는 API·테이블/화면은 아직 실제 구현/운영됨을 뜻하지 않습니다.

**문서 판정:** T31~T60 작성·신청 가능 / 실제 개발 NOT_STARTED / 담당자 UNASSIGNED / Staging 변경 없음.
