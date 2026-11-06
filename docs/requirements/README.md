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
- 기능 요구사항은 [10개 항목 양식](functional/ACCOUNT.md#양식), 비기능 요구사항은 [7개 항목 양식](non-functional/NON_FUNCTIONAL.md#양식)을 모든 항목에 똑같이 씁니다.
- 문서는 분류별 폴더에 한 단계로만 나눕니다(`분류/문서.md`).
