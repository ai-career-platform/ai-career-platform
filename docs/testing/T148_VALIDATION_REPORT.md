# T148 검증 보고서 — 기업·개인·관리자 다중 역할 E2E 권한 검증

## 1. 작업 목적
네 사용자 유형 사이의 권한 경계를 한 번에 확인하는 회귀 시험을 만듭니다.
- 사용자 유형: 개인 사용자(`job_seeker`), 기업 담당자(`company_member`), 기업 관리자(`company_owner`), 운영 관리자(`admin`)
- 확인 대상: 기업 간 IDOR, 역할 회수, 공유 링크 철회, 감사 추적

## 2. 기존 구현·PR 재사용
- T123·T126·T129(모두 main 병합, 플래그 기본 꺼짐)의 **실제 라우터와 실제 인증**을 그대로 씁니다.
  - 인증은 서명 검증 뒤 세션·사용자 상태·역할을 DB(메모리 저장소)에서 다시 읽습니다.
  - 각 기능의 메모리 저장소를 한 앱에 함께 연결했습니다.
- T86 `disposable_pg`(실제 0001 스키마 + T10 Seed + 최소 권한 앱 역할)로 실제 PostgreSQL 인증 층을 확인합니다.
- 새 시험 도구는 만들지 않았습니다.

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16` (main), 독립 PR
- HEAD_SHA: PR 댓글

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `backend/tests/test_t148_multi_role_security.py` | 14건(메모리 저장소 13 + PostgreSQL 1) |
| `backend/app/services/company_postings.py` | **F-2 수정**: 관리자 결정·내림에서 역할 확인을 공고 조회보다 먼저 |
| `docs/testing/T148_VALIDATION_REPORT.md` | 이 보고서 |

## 5. 선행조건
| 선행 | 상태 | 이번 범위 |
|---|---|---|
| T123 기업 계정 | 병합(플래그 꺼짐, 저장소 없음) | 라우터 + 메모리 |
| T126 기업 공고 | 병합(플래그 꺼짐, 저장소 없음) | 라우터 + 메모리 |
| T129 공개 포트폴리오 | 병합(플래그 꺼짐, 저장소 없음) | 라우터 + 메모리 |
| T141 개인정보 요청 정책 | **#230 OPEN** | 정책만. T142 API(#235)는 main 에 없어 이 시험에 넣지 않음 |
| T147 합성 데이터 공장 | 병합(#38) | 사용하지 않음. 합성 계정은 시험 안에서 만들고, PG 층은 T10 Seed 사용 |

## 6. 실제 실행 명령
```bash
cd backend
python -m pytest -q tests/test_t148_multi_role_security.py                      # 메모리 층
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<로컬>@127.0.0.1:<port>/t16_profile_test \
  python -m pytest -q tests/test_t148_multi_role_security.py -k pg              # PostgreSQL 층
python -m pytest -q tests/test_t123_company_accounts.py tests/test_t126_company_postings.py   # F-2 수정 회귀
T16_ISOLATED_DB_TEST=YES ... python -m pytest -q                                  # 전체 회귀
```

## 7. 정상·오류·권한 검증 (필수 10개)
| # | 시나리오 | 시험 | 층 | 결과 |
|---|---|---|---|---|
| 1 | 다른 기업 데이터 접근 차단 | 기업 A 담당자·관리자·개인 사용자 → 기업 B의 조직·멤버·초대·공고 목록·공고 상세·수정·생성, 내 조직 경로에 남의 공고 id → 모두 404, 원본 변경 없음 | 라우터+메모리 | PASS |
| 2 | 권한 회수 후 즉시 거부 | 멤버 제외 직후 조직·공고 404 / 운영 관리자 역할 회수 → 같은 토큰 다음 요청 403 / 세션 회수 → 401 / 계정 비활성 → 401 | 라우터+메모리, **PostgreSQL**(역할 행 삭제·세션 revoked_at) | PASS |
| 3 | 역할 토큰 위조 거부 | 올바른 서명 + 토큰 안 `roles:[admin]` → 403(토큰 역할 무시). 다른 키, payload 변조, `alg=none`, 만료, 남의 세션 id 섞기, 형식 오류, 빈 값 → 401 | 라우터+메모리 | PASS |
| 4 | 공유 링크 만료·철회 | 철회·만료(ttl 7일 + 8일)·동의 철회·없는 토큰 → 모두 같은 404 본문(이유 구별 불가) | 라우터+메모리 | PASS |
| 5 | 타 사용자 IDOR | 남의 공유 링크 철회 404(링크 유지) / 다른 기업 초대 재전송·취소 404 / **PG**: 다른 사용자의 경력 GET·PATCH·DELETE 404, 원본 유지 | 라우터+메모리, **PostgreSQL** | PASS |
| 6 | 비로그인 401 | 플래그 4개를 켠 앱의 **전체 경로 전수**: 공개 목록 16개를 뺀 85개 모두 401. 공개 목록이 바뀌면 실패 | 라우터 | PASS |
| 7 | 권한 부족 403 | 개인·기업 담당자·기업 관리자 → 모든 `/api/v1/admin/*`(형식이 맞는 본문) 403 / 담당자 → 초대·owner 제외 403 / 기업 관리자의 게시 결정 403 / 운영 관리자의 기업 콘솔 거부 | 라우터+메모리 | PASS |
| 8 | 비공개 프로필 외부 노출 차단 | 동의 전 링크 생성 거부 / 공개 화면에 전화번호·이메일·상세 주소 없음 / `/me/` 밖에 후보자·포트폴리오 경로 없음(공개 토큰 경로 제외) | 라우터+메모리 | PASS |
| 9 | 감사 추적 | 조직 승인(운영 관리자)·초대 수락(담당자)·공고 작성·결정 행위자 기록, 이메일 원문 없음, 거부된 시도는 감사·상태 변화 없음 / **PG**: 감사 조회 권한 | 라우터+메모리, PostgreSQL | PASS |
| 10 | 기존 권한 회귀 | 플래그 기본 꺼짐 = 기업·포트폴리오·지원 경로 없음 + 전체 Backend 회귀(T86 보안, T123·T126·T129·T155 포함) | 전체 | PASS(아래 §8) |

### 발견 사항
| ID | 심각도 | 내용 | 조치 |
|---|---|---|---|
| F-1 | Low | T123 조직 승인·T126 결정·내림은 역할을 **서비스 안에서** 확인합니다. 그래서 본문 형식이 틀리면 비관리자도 403이 아니라 **422**를 받습니다. 상태·데이터 노출은 없고 스키마는 OpenAPI에도 공개돼 있습니다 | 시험으로 고정(`test_7_observation…`). 라우터 수준 `require_roles("admin")`로 옮길지는 결정 필요 |
| F-2 | Low | T126 `decide`·`takedown`이 공고 존재 여부를 **역할보다 먼저** 확인했습니다. 비관리자가 공고 id 존재 여부를 구별할 수 있었습니다(없음 404 / 있음 403) | **수정**: 역할 확인을 먼저 합니다(T123 `verify`와 같은 순서). T126 기존 시험 전부 통과 |

## 8. PostgreSQL / Mock / 실제 API 구분
- **라우터+메모리(13건)**: 실제 HTTP 라우터·인증·CSRF를 거칩니다. 저장소는 메모리입니다(정식 migration 없음, 기본 의존성 503).
- **PostgreSQL 18.6(1건)**: 일회용 DB, 실제 스키마·Seed, 최소 권한 역할로 확인했습니다.
  - 운영 관리자 감사 조회: 비로그인 401, 개인 403, 관리자 200
  - DB 역할 회수 → 403, 세션 회수 → 401, 경력 IDOR → 404
- **Frontend Mock / 브라우저**: 이번 범위 아님. 화면 권한은 T124·T127·T130의 Mock 시험과 T117 브라우저 시나리오가 있습니다.
- **Staging**: NOT_RUN

로컬 전체 회귀(Windows, 일회용 PG): **1654 passed**, 101 skipped, 1 failed + 31 errors. 실패·오류는 모두 `test_documents.py`·`test_security_upload.py` 의 Windows 0700 기존 실패로 main 과 같습니다.

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- 기업·포트폴리오 기능에 정식 migration·DB 저장소가 없습니다. 그래서 기업 경계의 **실제 DB 시험은 불가**합니다(HOLD).
- T141 #230 / T142 #235가 미병합이라 개인정보 요청 API 경계는 이 시험에 포함하지 못했습니다.
- F-1 처리 방식 결정 필요

## 11. 후속 작업
- 기업·포트폴리오 DB 저장소가 생기면 같은 시나리오를 PostgreSQL 층으로 복제
- T142 병합 후 반출 요청 IDOR·재인증 시나리오 추가
- Staging에서 같은 경로 전수(401) 확인. 읽기 전용이며 접속 승인 필요

```text
UNIT_TESTS=PASS
POSTGRESQL_TESTS=PASS (admin role/session revocation, IDOR on real schema)
FRONTEND_TESTS=NOT_RUN
BROWSER_E2E=NOT_RUN
MOCK_VALIDATION=PASS (real routers + memory repositories for T123/T126/T129)
REAL_API_VALIDATION=PARTIAL (company/portfolio storage not provisioned)
STAGING_VALIDATION=NOT_RUN
```
