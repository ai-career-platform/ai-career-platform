# 요구사항 정의서

AI Career Platform의 요구사항 문서 목차입니다.

- 문서 버전: v0.2 (2026-11-06)
- 작성자: 이상재
- 관련 일감: Redmine #1495 (T04)
- 상태: 검토 중. 모든 요구사항은 PM 승인 전입니다.

## 목차

| 분류 | 문서 | 내용 |
|---|---|---|
| 개요 | [overview/PROJECT_OVERVIEW.md](overview/PROJECT_OVERVIEW.md) | 프로젝트명, 목적, 배경, 범위, 사용자, 기능 구성 |
| 기능 요구사항 | [functional/ACCOUNT.md](functional/ACCOUNT.md) | 계정·인증·개인정보 (FR-ACC) |
| | [functional/PROFILE.md](functional/PROFILE.md) | 프로필·보유 기술·목표 직무·경력 (FR-PRF) |
| | [functional/JOB.md](functional/JOB.md) | 직무·기업·채용공고 탐색 (FR-JOB) |
| | [functional/ANALYSIS.md](functional/ANALYSIS.md) | 적합도·Skill Gap·추천·시장 추세 (FR-ANL) |
| | [functional/AI.md](functional/AI.md) | 문서 분석·커리어 Q&A·AI 작업 (FR-AI) |
| | [functional/ADMIN.md](functional/ADMIN.md) | 운영 관리 (FR-ADM) |
| | [functional/COMMON.md](functional/COMMON.md) | 홈·온보딩·공통 화면 (FR-CMN) |
| 비기능 요구사항 | [non-functional/NON_FUNCTIONAL.md](non-functional/NON_FUNCTIONAL.md) | 보안, 개인정보, 성능, 가용성, AI 품질, 운영, 사용성 (NFR) |
| 유스케이스 | [use-cases/USE_CASE_DIAGRAM.md](use-cases/USE_CASE_DIAGRAM.md) | 액터별 유스케이스 다이어그램 (Mermaid) |
| 추적·결정 | [traceability/TRACEABILITY.md](traceability/TRACEABILITY.md) | 요구사항 ↔ 화면 ↔ 기존 기능 후보 대응, 미결정 사항 |

## 작성 규칙

- 요구사항 ID: `FR-분류-번호`(기능), `NFR-분류-번호`(비기능)
- 우선순위: **Must**(1차 릴리스 필수) · **Should**(1차 목표, 일정에 따라 조정) · **Could**(여유가 있을 때)
- 문서는 분류별 폴더에 한 단계로만 나눕니다(`분류/문서.md`).
- 모든 요구사항은 아래 양식의 항목을 같은 순서로 적습니다.

## 양식

### 기능 요구사항

| 항목 | 적는 내용 |
|---|---|
| 요구사항명 | 기능을 한 줄로 |
| 우선순위 | Must / Should / Could |
| 사용자 스토리 | "(사용자)로서, (행동)하고 싶다. (목적) 때문이다." |
| 설명 | 기능 범위 |
| 입력 | 사용자가 넣는 값과 제한 |
| 출력 | 시스템이 보여주거나 저장하는 결과 |
| 선행 조건 | 기능을 쓰기 전에 필요한 상태 |
| 수용 기준 | 완료를 판단하는 확인 항목 |
| 예외 처리 | 실패·오류 시 동작 |
| 관련 화면 | 화면 ID ([화면 목록](traceability/TRACEABILITY.md#2-화면-목록)) |

### 비기능 요구사항

| 항목 | 적는 내용 |
|---|---|
| 요구사항명 | 품질 기준을 한 줄로 |
| 우선순위 | Must / Should / Could |
| 사용자 스토리 | 이 기준이 필요한 사람과 이유 |
| 설명 | 지켜야 할 내용 |
| 적용 대상 | 적용되는 기능·요구사항 |
| 측정 기준 | 통과 여부를 판단하는 수치·조건 |
| 검증 방법 | 확인 방법과 담당 일감 |
