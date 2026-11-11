# T129 검증 보고서 — 공개 포트폴리오 조회·공유 링크 API

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 실제 FastAPI 라우터·인증과 메모리 저장소로 검증했습니다. DB 저장소와 Staging은 미실행입니다.
> - **실제 외부 공개 API는 비활성**입니다(플래그 기본 꺼짐, 켜도 저장소가 없어 503).
> **스택**: main `ab56765` → T121 #210 → T128 #215 → 이 PR

## 1. 목적
동의한 개인 경력 공유와 링크 만료·철회 API를 만듭니다. 소유권, 추측 방지, 기간 제한, 캐시 무효화를 시험합니다.

## 2. 선행 일감
- T37 경력·프로젝트, T49 문서: main
- T128 정책: **#215 미병합(스택)**. 필드 카탈로그·링크 규칙을 코드가 그대로 따르는지 시험합니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/public_portfolio.py` (신규) | 선택·미리보기·동의·철회, 링크(256비트 토큰, 해시 저장), 공개 조회, 렌더링(선택한 것만, 현재 데이터), 메모리 저장소 |
| `backend/app/routers/public_portfolio.py` (신규) | 소유자 엔드포인트 7개(로그인) + 공개 조회 1개(비로그인, 보안 헤더, IP당 한도). 기본 의존성 503 |
| `backend/app/core/config.py`, `backend/app/main.py` | `public_portfolio_api`(기본 꺼짐), 조건부 등록 |
| `backend/tests/test_t129_public_portfolio.py` (신규) | 25건 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12, **메모리 저장소이며 DB 저장소 PASS 아님**)

| 범주 | 시험 | 결과 |
|---|---|---|
| 정책 일치 | 공개 가능 13·불가 6 항목, 링크 3개, 기간 30/90일 = T128 카탈로그 | PASS |
| 플래그 | 기본 꺼짐(경로 없음) | PASS |
| **비공개 기본** | 선택 전 미리보기 `{}`, 선택·확인 전 공유 409, 확인 후 공유, 동의 기록 | PASS |
| 공개 불가 항목 | 6종 각각 422 | PASS |
| 소유권 | 남의 경력 ID 선택 404, 남의 링크 회수 404, 남의 설정에 내 링크 없음 | PASS |
| **미리보기 = 공개 화면** | 같은 내용. 비공개 소개·이메일·선택 안 한 경력·지역·프로젝트·설명 노출 0, 기간은 연·월만 | PASS |
| 별칭 | 실명 대신 별칭 | PASS |
| **추측 방지** | 토큰 43자 이상(256비트), 저장은 64자 해시, 설정 화면에 토큰 없음, 같은 404 본문(없음·형식 오류·만료), IP당 60회 초과 시 429 | PASS |
| 헤더 | `no-store`, `noindex, nofollow, noarchive`, `no-referrer` | PASS |
| **철회 즉시** | 링크 회수 → 다음 요청 404. 동의 철회 → 모든 링크 404, 선택 초기화, 철회 기록 | PASS |
| 재동의 | 선택을 바꾸면 기존 링크 404 → 확인 후 새 범위만 공개 | PASS |
| **캐시·삭제 전파** | 원본 수정·삭제가 다음 조회에 바로 반영, 새 경력은 비공개, 계정 삭제 시 링크 삭제 | PASS |
| 기간·개수 | 0일·91일 422, 90일 허용, 4번째 409, 만료 뒤 새 링크 | PASS |
| 인증 | 소유자 API 401, 공개 조회는 비로그인 200 | PASS |
| 열람 기록 | 횟수만, 열람자 정보 필드 없음 | PASS |

- `test_t129_public_portfolio.py` **25 passed**
- 전체 Backend: **1212 passed / 265 skipped**. 실패·오류 32건은 기존 Windows 전용 시험이며 PASS로 세지 않았습니다.

## 5. 병합 주의
- `config.py`·`main.py`는 T123(#218)·T126과 겹칩니다. 나중에 병합하는 쪽에서 모두 유지해야 합니다.
- T111(#207)이 먼저 병합되면 `env_contract.py`에 `PUBLIC_PORTFOLIO_API`를 추가해야 합니다.
- 공개 조회 경로의 토큰은 T112(#208) `safe_path`가 접근 로그에서 `:token`으로 가립니다(43자 이상).

## 6. 미승인·후속
1. T128 승인 → 선택·링크 표 migration → DB 저장소. 프로필 원천은 기존 표(`users`, `user_profiles`, `user_experiences`, `user_projects`, `user_skills`, `user_target_roles`)를 읽기 전용으로 씁니다.
2. 동의 코드 `public_profile` seed(법무 문구)
3. 요청 한도 값(PROPOSED 60/60초)
