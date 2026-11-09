# AX 2기 크롤러 고도화 및 관리자 웹 구축 — 상위 Feature

상태: PROPOSED / NOT_STARTED · 우선순위: P1 · 담당자/일정/Redmine 실제 ID: 미배정.

## 목표
기존 T61~T64의 학습용 Fixture 검증 자산을 재사용하여 검색어 6개 관리→원본 수집/보관→독립 파싱·검증→증분 스케줄링→관리자 API·웹 UI까지 구현한다.

## 하위 일감
- [T151](T151.md) AX 2기 검색어·수집 작업 관리 / DB/Backend / 선행 T61,T62,T63,T64
- [T152](T152.md) 목록·상세 HTML 원본 수집·보관 / Crawler/DB / 선행 T151,T62,T61
- [T153](T153.md) 독립 파싱·검증·후처리 파이프라인 / Backend/DB / 선행 T152,T63
- [T154](T154.md) 증분 수집·분할 스케줄링·안전 재개 / Backend/DevOps / 선행 T151,T152,T153,T64
- [T155](T155.md) 크롤러 관리자 API 및 권한 연동 / Backend/보안 / 선행 T151,T152,T153,T154,T15
- [T156](T156.md) 크롤러 관리자 웹 UI 및 통합 QA / Frontend/QA / 선행 T155,T20,T21

## 확정 설계 원칙
- 기본 검색어: AI, Python, 데이터 분석, LLM, 업무 자동화, AI 엔지니어. 개별 검색과 통합 공고 저장, 검색어-공고 발견 관계 추적. 검색어는 관리자 CRUD.
- Fetch Worker는 허용된 목록·상세 HTML을 가져오되 HTTP/타입/크기·안전 경계만 검증하고, Raw artifact로 저장. Parse Worker가 별도 정규화·검증·UPSERT.
- Raw HTML은 적법하게 보관 가능한 데이터만 제한된 파일/객체 저장소에 저장하고 DB에는 해시·URL·시각·상태·storage_key 메타데이터를 기록. 개인정보·보존·삭제 정책 별도 검증.
- 신규 공고 우선 + 최근 3~7일 변경/지연 노출 재확인 + 실패 단위 재개. 검색어별 checkpoint·작업 큐·멱등성.
- 실행 시간창 21:00~다음날 08:00 KST는 관리자 편집 가능한 초기안일 뿐; 외부 대상 정책·요청 제한을 우선하며 차단 회피 금지.
- T61의 수집·저장/가공/재배포 조건이 확인되기 전까지 실사이트 Live 자동 수집 HOLD. Fixture·격리 환경에서 개발.
- 기존 앱 DB/Auto-CD/Docker 볼륨/5건 실제 공고 및 T64 이전 Fixture 2건 보존. 운영 Timer 및 schedule 비활성 유지.

## 통합 완료 기준
관리자 UI에서 6개 검색어 CRUD→합성 목록/상세 Raw 저장→독립 Parse·Validation→정제 DB 조회→실행/오류 통계까지 실제 staging Fixture E2E를 통과하고, CI·Auto-CD·Redmine 종료 게이트를 충족한다.

## 등록
Excel 등록용 15열 TSV: [APPLICATION_T151_T156.tsv](APPLICATION_T151_T156.tsv). Redmine 실제 Issue 번호/URL 및 담당자·날짜는 생성 후 기입한다.
