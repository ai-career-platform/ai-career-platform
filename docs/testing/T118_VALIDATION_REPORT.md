# T118 검증 보고서 — 취약점 점검·SBOM·의존성 정책

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=FAIL(게이트)**
> - 스캔은 실제로 실행했습니다(pip-audit, npm audit).
> - 수정 후에도 starlette HIGH 3건이 남아 있고, 그 예외가 승인 대기라 게이트 판정은 FAIL입니다.
> - 컨테이너 이미지 스캔과 서명은 NOT_RUN입니다.

## 1. 목적
Backend·Frontend·Container 의존성 보안, 비밀 노출, 이미지 provenance를 검토합니다.

## 2. 선행 일감

| 일감 | 상태 |
|---|---|
| T28 CI | 병합 |
| T86 보안 회귀 | 병합 |
| T111 환경·Secret | PR #207(미병합). 비밀 노출 시험은 그 PR에 있음 |

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/requirements.txt` | PyJWT 2.10.1 → **2.15.0**, python-multipart 0.0.22 → **0.0.31** |
| `backend/requirements-dev.txt` | pytest 8.3.5 → **9.0.3** |
| `scripts/supply_chain/t118_sbom.py` (신규) | sbom / policy / gate |
| `docs/security/sbom/ai-career-platform.cdx.json` (신규) | SBOM(구성요소 243개) |
| `docs/security/t118_scan_before.json`, `t118_scan_after.json` (신규) | 스캔 결과(심각도 포함) |
| `docs/security/supply_chain_exceptions.yaml` (신규) | starlette HIGH 3건(승인 대기) |
| `docs/security/SUPPLY_CHAIN_POLICY.md` (신규) | 정책, 결과, 적용성, 게이트, 재현 명령 |
| `backend/tests/test_t118_supply_chain.py` (신규) | 29건 |

`poc/staging/backend/requirements.txt`(PoC Staging 이미지)는 바꾸지 않았습니다. 운영 컨테이너 변경이라 승인이 필요하며, 결과만 기록했습니다.

## 4. 시험·스캔 결과

| 항목 | 결과 |
|---|---|
| pip-audit 수정 전(dev 46개 패키지) | 30건 / 4개 패키지 |
| pip-audit 수정 후 | **7건 / starlette 1개 패키지**(HIGH 3, MODERATE 3, LOW 1) |
| PoC Staging requirements | starlette 7건(변경 안 함) |
| npm audit(frontend 164개, openapi 도구 33개) | **0건** |
| 컨테이너 이미지 스캔 | **NOT_RUN**(trivy·grype 없음) |
| 정책 검사 | FAIL 0 / WARN 4(Python 전이 잠금 없음, 베이스 이미지 digest 없음 ×3) |
| SBOM 재현성 | 2회 생성 sha256 동일(`71da7950…`) |
| 게이트(수정 후 + 현재 예외) | **FAIL**(차단 3건, 예외 승인 대기) |
| `test_t118_supply_chain.py` | **29 passed** |
| **전체 Backend(상향 버전, 새 venv, 격리 PostgreSQL 18.6 포함)** | **1321 passed / 95 skipped**. 실패·오류 32건은 기존 Windows 전용이며 PASS로 세지 않았습니다 |

시험 29건의 내용은 다음과 같습니다.
- SBOM 재현성·정렬, 직접 의존성·npm 전체(해시)·베이스 이미지 포함, 커밋된 SBOM과 현재 의존성 일치
- 정책 실패 6종(합성 저장소), digest 고정 이미지 통과
- 게이트
  - HIGH·CRITICAL·미분류는 차단, MODERATE·LOW는 보고만
  - 유효 예외는 통과
  - 승인자 없음·공백, 사유 없음, 만료, 만료일 없음, ID·패키지 불일치 예외는 무효
  - 만료 당일까지 유효
  - 저장소 현재 상태는 FAIL
- 상향 버전 고정 확인

## 5. 발견 사항

| ID | 심각도 | 내용 | 조치 |
|---|---|---|---|
| S-1 | High(보고 기준) | PyJWT 2.10.1에 CRITICAL 1·HIGH 5. 이 앱의 HS256 고정 사용에서는 경로가 닿지 않는 것으로 판단 | 2.15.0 상향 |
| S-2 | High | python-multipart DoS 2건(문서 업로드에서 사용) | 0.0.31 상향 |
| S-3 | High(경로 없음 판단) | starlette 0.46.2 HIGH 3. FastAPI 0.115.x에 묶여 있음 | **FastAPI 업그레이드 별도 PR** 또는 예외 승인(PM) |
| S-4 | Medium | Python 전이 의존성 잠금 없음, 베이스 이미지 digest 없음 | 제안(§2) |
| S-5 | — | PoC Staging 이미지 requirements의 starlette 동일 | 운영 컨테이너 변경 승인 필요 |

## 6. 미승인·후속
1. starlette: FastAPI 업그레이드 PR, 또는 예외 승인(만료 2026-12-11 제안)
2. `requirements.lock`(해시)·digest 고정 도입 승인
3. 컨테이너 스캔 도구(trivy) 도입, 이미지 서명(cosign)·provenance: NOT_RUN
4. CI에 스캔 단계를 넣을지 결정(네트워크 의존)
