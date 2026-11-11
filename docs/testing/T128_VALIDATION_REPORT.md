# T128 검증 보고서 — 후보자 공개 프로필·동의 범위 정책

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**: 정책은 PROPOSED(PM·법무 승인 전)입니다. 구현, DB 변경, 동의 코드 추가는 없습니다.
> **스택**: main `ab56765` → T121 #210 → 이 PR

## 1. 목적
기업에 공개할 경력·포트폴리오 범위와 철회 정책을 정합니다. 다룬 범위는 다음과 같습니다.
- 비공개 기본, 필드별 동의
- 삭제 전파
- URL 공유 위험

## 2. 선행 일감
- T31 동의·탈퇴, T37 경력·프로젝트: main
- T121: **#210 미병합(스택)**
- 기존 `user_consents`·`consent_policies`를 재사용하며, 선택 코드 `public_profile`은 제안만 합니다(seed 미변경).

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `docs/enterprise/T128_PUBLIC_PROFILE_CONSENT_POLICY.md` (신규) | 원칙 5개, 항목 19개 공개 범위, 링크 규칙, URL 위험 7종과 대응·남는 위험, 동의 기록, 불변 조건 7개, 결정 D-1~D-6 |
| `docs/enterprise/t128_public_profile_fields.json` (신규) | 항목 카탈로그·노출·링크·철회·삭제 규칙(T129·T130이 읽음) |
| `backend/tests/test_t128_public_profile_policy.py` (신규) | 15건 |

## 4. 시험 결과 (로컬)

| 시험 | 결과 |
|---|---|
| PROPOSED, 선택 동의 필수 | PASS |
| PP-INV-1: 19개 항목 모두 기본 비공개 | PASS |
| PP-INV-2: 이메일·문서·AI 분석·지원 기록·행동 데이터·계정 정보 공개 불가(6건) | PASS |
| 공개 가능 항목은 위험 low·medium만 | PASS |
| **공개 가능 항목의 원천이 실제 0001 스키마 열에 존재** | PASS |
| PP-INV-3: 철회 즉시, 모든 링크 무효, 선택 초기화 | PASS |
| PP-INV-4: 색인·기업 검색·목록 없음, noindex·no-store·no-referrer. T121 `candidate.search` 전부 거부와 일치 | PASS |
| PP-INV-5: 토큰 128비트 이상, 기간 ≤ 90일, 링크 ≤ 3개, 404 동일 | PASS |
| PP-INV-6: 현재 데이터를 그림, 새 항목 비공개, 경력·프로젝트는 항목별 선택 | PASS |
| 문서에 모든 항목·불변 조건·URL 위험 7종·법무 표시 | PASS |

**15 passed.**

## 5. 미승인·후속
- PM·법무 결정 D-1~D-6: 동의 문구, 별칭, 링크 기간, 열람 기록, 미성년자, 문서 공개
- 동의 코드 seed 추가와 선택 표 migration은 승인 후 진행합니다.
- T129(API)와 T130(화면)이 이 카탈로그를 사용합니다.
