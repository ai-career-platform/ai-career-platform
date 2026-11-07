# T61 — 데이터 출처 레지스트리 (STEP 01 초안)

> 작성일: 2026-11-07 · 상태: **DRAFT / EXTERNAL_COLLECTION=HOLD** · 담당/최종 승인자: PM 배정 및 승인 대기  
> 범위: 출처 조사·데이터 계약 매핑·승인 체크리스트 **문서 전용**. 실사이트 수집, DB 변경, 배포, API 구현 없음.  
> 기준: `main` e2b2d13dbf2da107d43314f073e9f6ec072e2b7c (PR #51 병합본)

## 1. 확인한 기준과 선행 게이트

- [T61 작업지시서](../work-orders/remaining-30/T61.md) §7: `approval_status=APPROVED/HOLD/DENIED`, 승인 증빙, 출처별 제한, 만료 및 재검토를 요구한다.
- [T04 작업지시서](../work-orders/initial-30/T04.md) 및 [T05 작업지시서](../work-orders/initial-30/T05.md)는 `READY_FOR_REVIEW` (완료 증빙이 아님). [데이터 사전](../../database/DATA_DICTIONARY.md)은 `T05_STATUS=PARTIAL`, PM/DB 리뷰·CI 검증 대기다.
- [T25 작업지시서](../work-orders/initial-30/T25.md)도 `READY_FOR_REVIEW`. 지정 산출물 `docs/ai/FEATURE_CONTRACT.md`는 이 기준 `main`에서 확인되지 않는다. T04 지정 `docs/requirements/FEATURE_BASELINE.md`도 확인되지 않는다. **세 선행 일감의 PASS/최종 수용을 확인하지 못했다.**
- [전체 데이터 모델](../../database/FULL_DATABASE_MODEL.md)과 [AI 아키텍처](../AI_SYSTEM_ARCHITECTURE.md)는 후보 설계이며, 외부 데이터 권리·운영 승인 증빙이 아니다.
- [Seed 안내](../../database/seeds/README.md)와 [Seed SQL](../../database/seeds/0001_initial_seed.sql)에 `synthetic_seed`가 1개 정의된다. **이는 로컬/일회용 DB용 합성 fixture이지, 공유 Staging 반영 또는 외부 수집 실행 증빙이 아니다.**
- 결정 D-05(외부 출처), D-06(삭제/보존 기간) 및 T05/T09 스키마 확정이 미완료다.

**STEP 01 결정:** 설계/Mock 문서 작성만 허용. 외부 출처 실연동, 배치 가동, 승인된 출처로의 상태 전환은 모두 HOLD.

## 2. 출처 식별 현황 (문서·Seed 기준; 실제 운영 DB 조회 아님)

| 등록 구분 | source code / 후보 ID | 대상/근거 | collection_method | approval_status | 실제 수집 | 확인된 권리/근거 |
|---|---|---|---|---|---|---|
| 기존 합성 Seed 정의 | `synthetic_seed` | T10 `0001_initial_seed.sql` (가상 기업·공고) | `SYNTHETIC` (외부 API/CSV/Web 해당 없음) | `HOLD` (T61 외부 수집 승인과 별개) | **외부 호출 없음** | 외부 콘텐츠 미사용; 로컬/일회용 fixture만 문서상 허용 |
| 외부 API 후보 (미선정) | `TBD_API_01` (임시 표기, DB code 아님) | 공식 공급자 선정·계약 확인 필요 | `API` (제안) | `HOLD` | **금지** | 공식 이용 조건·API 사용 목적·재배포 근거 미확보 |
| 외부 CSV/다운로드 후보 (미선정) | `TBD_CSV_01` (임시 표기, DB code 아님) | 공식 데이터 제공처 선정 필요 | `CSV` (제안) | `HOLD` | **금지** | 다운로드·가공·재배포·보존 조건 미확보 |
| 외부 웹페이지 후보 (미선정) | `TBD_WEB_01` (임시 표기, DB code 아님) | 개별 출처 선정 필요 | `WEB` (제안) | `HOLD` | **금지** | 약관·robots.txt·접근 권한·자동 수집 허용 근거 미확보 |

**주의:** `TBD_*`는 후보 유형을 설명하기 위한 자리표시자일 뿐, 실제 사이트 또는 DB 등록 건수가 아니다. 현재 기준선에서 **식별 가능한 외부 실사이트/공식 API/CSV 승인 목록은 0건**이며, 레지스트리에 임의 업체명·도메인·권리를 만들어 넣지 않는다. `synthetic_seed`의 `HOLD`는 외부 수집 승인 필드의 보수적 표시이며, 합성 fixture의 독립 실행 가능 여부는 기존 T10 문서·격리 환경 정책을 따른다.

## 3. 출처별 필수 기록 계약 (T61 제안; DB 적용 전)

| 필드 | 의미 / 필수 규칙 | 현재 C05 `data_sources` 대응 |
|---|---|---|
| `source_id` | 변하지 않는 내부 UUID (실제 등록 시 생성) | **존재** (`uuid` PK) |
| `code`, `name` | 유일한 출처 코드, 명칭 | **존재** (`code` UQ, `name`) |
| `official_url`, `endpoint` | 공식 도메인 및 수집 주소, 인증정보 제외 | **없음 — 문서 관리** |
| `collection_method` | API / CSV / WEB; 합성 fixture는 SYNTHETIC | **없음 — 문서 관리** |
| `approval_status` | APPROVED / HOLD / DENIED (기본 HOLD) | **없음 — 문서 관리** |
| `approver`, `approved_at`, `review_due_at` | 승인자, 승인일, 재검토/만료일 | **없음 — 문서 관리** |
| `approval_evidence` | 실제 약관 조항·계약 링크/증빙 파일과 검토 일자 | **없음 — 문서 관리** |
| `license_ref` | 허가·계약 참조; 외부 출처에는 필수 | **존재** (nullable, 외부 출처 CHECK 제한) |
| `allowed_scope` | 공고/기업/직무/시장지표 및 허용 필드·목적 | **없음 — 문서 관리** |
| `redistribution_policy` | 원문 노출·API 재제공·파생지표 허용 범위 | **없음 — 문서 관리** |
| `retention_days`, `delete_policy` | 보존 상한과 만료·철회 시 삭제 처리 | `retention_days` **존재**; 삭제 방식 **없음** |
| `pii_exclusion` | 개인 연락처·식별정보 등 비필수 개인정보 기본 제외 | **없음 — 문서 관리** |
| `enabled` | 수집 실행 가능 플래그; 승인과 동시 확인 | `is_active` **존재**하나 동등한 승인 상태 아님 |
| `rate_limit`, `backoff`, `access_rules` | 요청량, 오류 대기, 인증/접근 제한 | **없음 — 문서 관리** |
| `schedule_timezone`, `proposed_local_time` | 기본 `Asia/Seoul`, **03:00 KST 제안** | **없음 — 문서 관리** |
| `owner`, `history` | 출처 담당자, 승인/정책 변경 이력 | **없음 — 문서 관리** |

`is_active=true` 또는 `license_ref IS NOT NULL`만으로 수집을 허용해서는 안 된다. T05/T09 스키마·API 합의 전까지 상기 추가 필드를 기존 DB에 임의로 추가하거나 컬럼 호환성을 주장하지 않는다.

## 4. 승인·실행 게이트 (T62/T64에 전달할 설계 계약)

**실제 외부 요청 전 모든 조건 충족 필요:**

1. `approval_status == APPROVED`, 승인자·승인일·검증 가능한 근거가 존재하고 재검토/만료일을 지나지 않았는지 확인.
2. 출처별 허용 방법(API/CSV/WEB), 수집 필드, 상업적 이용 및 파생/재배포 권리, 보존·삭제 규칙이 명시되어 있는지 확인.
3. `enabled == true`이며 출처별 rate limit·백오프·접근 제한을 준수하는지 확인.
4. 개인정보 제외 기준 및 Secret 보관 방식이 확인되고, T04/T05/T25 선행 계약과 실행 대상 환경의 별도 승인을 충족하는지 확인.
5. **HOLD, DENIED, 승인 만료, 출처 차단/약관 변경 징후는 관리자 수동 재실행을 포함하여 모두 차단.** 의심 시 즉시 비활성화 후 재검토.

`robots.txt`만 허용이라고 해서 저작권·약관·접근권한까지 해결되는 것은 아니다. 미확정 조건은 기본 HOLD. 외부 자격 증명이나 비밀 키는 문서/로그/PR에 기록하지 않는다.

### 검증 시나리오 (계획만 정의, 미실행)

| 시나리오 | 기대 결과 | STEP 01 검증 상태 |
|---|---|---|
| 승인 유효 + enabled + 정책 적합한 Mock 출처 | 별도 구현 후 허용 | `NOT_RUN` |
| HOLD 또는 DENIED (수동 실행 포함) | 거부 | `NOT_RUN` |
| 승인 만료 / enabled=false / 이용약관 변경·차단 감지 | 거부·중단 | `NOT_RUN` |
| rate limit 초과·인증 실패 | 제한/백오프/차단 기록 | `NOT_RUN` |

Mock fixture와 자동화 테스트 구현은 선행조건 확인 후 별도 STEP에서 다룬다. 본 문서는 정책 계약 초안이지 정책 엔진 테스트 PASS 증빙이 아니다.

## 5. 승인 체크리스트 (각 실출처별 복사하여 사용)

- [ ] 출처명 / `code` / 공식 URL / 책임자 / 수집 방식 식별
- [ ] 공식 API·CSV·약관·라이선스의 정확한 링크/버전/검토일 확보
- [ ] 수집·저장·가공·공개·재배포 목적별 권한과 금지 항목 확인
- [ ] 상업적 이용 여부 / 개인정보 제외 / 필드 범위 명시
- [ ] 보존 일수 / 변경·삭제 통지 / 접근 차단 시 처리 정의
- [ ] 허용 요청량·시간·접근방법·실패 백오프 확정
- [ ] 승인자 / 승인 시각 / 승인 근거 / 재검토·만료일 기록
- [ ] T04·T05·T25 선행 승인과 실제 배포 환경 승인 확인
- [ ] 정책 변경 이력 및 `enabled=false` 중단 수단 검토
- [ ] 최종 승인까지 `approval_status=HOLD` 및 외부 실행 불가 유지

## 6. 변경 이력 · 보류 의사결정

| 날짜 | 항목 | 처리 | 이유 / 필요 승인 |
|---|---|---|---|
| 2026-11-07 | 출처 레지스트리 STEP 01 작성 | DRAFT | GitHub 문서 및 합성 Seed 정의 대조 |
| 2026-11-07 | 외부 후보 API/CSV/WEB | HOLD | 특정 공급자 미선정, 이용권한 미검증 |
| 2026-11-07 | DB 승인 상태 필드 추가 | HOLD | T05/T09 데이터 계약 및 Migration 승인 필요 |
| 2026-11-07 | 외부 수집 실행 | HOLD | T04/T05/T25 승인 및 개별 출처 허가 필요 |

**다음 STEP 제안:** 출처별 공식 제공처 후보와 권리·정책 근거를 조사한 뒤, 출처 레지스트리에 *실제 사이트별* 기록을 추가한다. 이때도 최종 PM 승인 전 `APPROVED`를 부여하지 않는다.

### STEP 01 증빙 한계

- **확인:** 기준 `main`의 T61/T04/T05/T25 작업지시서, 데이터 사전, 전체 DB 모델, AI 아키텍처, T10 Seed 문서·SQL.
- **미확인:** 실제 DB 행, 외부 사이트 법적 권리, Redmine 실시간 상태, T04/T05/T25 PM 최종 수용, T62/T64 실행 허용.
- **테스트:** 문서 검토만; DB 테스트/외부 HTTP 수집/CI 실행은 별도 확인 전 `NOT_VERIFIED`.


---

## 7. STEP 02 — 공식 채용정보 API 제공처 1차 조사 (2026-11-07)

> 상태: **RESEARCH_ONLY / ALL_EXTERNAL_SOURCES=HOLD**. 이 표는 기존 `synthetic_seed` 이외의 **미등록 후보 3곳**을 조사한 기록이다. API 신청·키 발급·실제 API 호출·스크래핑·DB 등록·운영 수집은 하지 않았다. 아래 후보 코드는 임시 문서 식별자이며 실DB `data_sources.code`가 아니다.

| 후보 코드 (임시) | 공식 제공처 / 안내 URL | 방식 | 공식 문서에서 확인된 사항 | 저장·가공·재배포 판정 | 승인 상태 |
|---|---|---|---|---|---|
| `candidate_work24` | 고용24 / https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do | API (XML) | 회원가입·인증키 신청 필요, 서비스별 사양 준수, 인증키 양도 금지. 채용정보 목록·상세 API 안내 존재. | API 제공 자체는 확인. 상세정보에 출처 표시·원문 연결 의무 및 무단복제·배포 금지 안내가 있어 **내부 DB 저장·정규화·재배포/상업적 활용 범위는 별도 공식 확인 필요**. | **HOLD** |
| `candidate_saramin` | 사람인 / https://oapi.saramin.co.kr/guide/info | API (XML/JSON) | 이용신청 심사·승인 및 access-key 필요, **일 500회** 호출 제한. 출처/브랜드 표시 요구. | 공식 신청 제한사항상 API 서비스 재판매·유료화 제한. 채용원문 저장·2차 가공·장기 보존 권리 확인 전 사용 불가. | **HOLD** |
| `candidate_jobkorea` | 잡코리아 / https://www.jobkorea.co.kr/network/Popup_Xml.asp | API (신청·승인 방식) | 기관 중심 신청. 약관 제5조는 프로젝트·DB 수집 목적 승인 제한, 제7조는 데이터 별도 복제·저장과 재가공을 제한. | **현재 설계(독립 Batch Worker→정규화→DB 저장)와 약관상 직접 충돌**. 제공자의 별도 서면 계약 또는 명시적 예외 승인 없으면 채택 불가. | **HOLD (현 방식 적용 불가)** |

### 7.1 공식 근거 및 확인 범위

- **고용24:** https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do ; 채용정보 안내 https://www.work24.go.kr/cm/e/a/0110/selectOpenApiSvcInfo.do?fullApiSvcId=000000000000000000000000000000 (공식 API 목록·상세 안내). 목록/상세 조회와 출처·원문 링크 의무 확인. 라이선스별 보존/재배포 기간은 미확인.
- **사람인:** https://oapi.saramin.co.kr/guide/info ; https://oapi.saramin.co.kr/guide/job-search ; https://oapi.saramin.co.kr/join (공식 API 가이드·신청 제한). 일 500회 및 승인 절차 확인. 유료화·재판매 제한은 명시, 데이터의 저장·가공 권한은 미승인.
- **잡코리아:** https://www.jobkorea.co.kr/network/Popup_Xml.asp (공식 API 신청 및 이용약관 제5·7조). 요청 목적이 프로젝트·DB 수집이면 승인되지 않을 수 있으며, 원문 별도 저장·가공이 제한됨.
- **조사 방법:** 공개 공식 안내/약관 **읽기만 수행**. 인증이 필요한 실제 API 응답, 할당량, 최신 개별 계약서는 검증하지 못했다. 조사가 이용승인 또는 법률 검토를 대체하지 않는다.

### 7.2 다음 승인 판단 전에 필요한 질문

| 출처 | 반드시 서면/공식적으로 확인할 쟁점 | 현 단계 결정 |
|---|---|---|
| 고용24 | 저장 가능한 필드, 보존기간, 재가공·재배포/AI 분석, 출처 표시 및 원문 링크 방식, API 인증키 발급 주체, 사용량 제한 | **우선 협의 후보** / HOLD |
| 사람인 | 신청 심사, 서비스 비영리·상업 목적 구분, 가공 및 DB 보관·삭제 허용, 사용자 노출과 출처 표시, 일 500회 제한 | **조건부 후보** / HOLD |
| 잡코리아 | 프로젝트/DB 수집 목적의 별도 계약 허용 여부, 별도 저장·가공 금지 조항 예외 및 라이선스 명시 | **현 아키텍처 사용 제외 후보** / HOLD |

**중요:** 잡코리아의 '현 방식 적용 불가'는 현재 공개 약관 기준 **기술 설계와의 부적합**을 뜻한다. 법적 의미의 영구 금지 `DENIED` 또는 제공자의 개별 계약을 단정하지 않는다. 별도 사용 계약이 확보되면 PM이 근거 검토 후 재평가한다. 세 곳 모두 `APPROVED` 아님.

### 7.3 정책 게이트 영향 및 후속 작업

- T62가 API를 호출하기 전에 출처별 신청 승인, 이용 목적 적합성, 데이터 DB 저장·가공 권리, 보존·재배포 규칙을 **모두 증빙**해야 한다.
- `data_sources.is_active`의 기본값 `true`는 허가 증빙이 아니며, 임시 후보를 실제 DB/Seed에 넣지 않는다.
- 다음 STEP은 **PM의 후보 우선순위 검토 + 공식 사용권한 질의서/승인 증빙 확보**다. 외부 제공자에게 자동 신청/메일 발송하지 않는다.
- 테스트: 문서 조사만 수행. API 네트워크 호출·권한 확인·실 DB·크롤러 실행 `NOT_RUN`; CI 결과는 해당 PR에서 별도 확인.
