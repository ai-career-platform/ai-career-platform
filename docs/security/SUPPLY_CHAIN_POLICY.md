# 공급망·의존성 보안 정책 (T118)

> 상태: **PROPOSED**(PM 승인 전)입니다.
> - 이번 PR에서 한 일: 스캔을 실제로 실행, SBOM 생성기·정책 검사·게이트 작성, 수정이 쉬운 취약점 2개 패키지(+개발용 1개)를 버전 상향
> - 남은 것: starlette 취약점은 FastAPI 업그레이드가 필요해 **게이트 판정은 FAIL(NO-GO)** 입니다.

## 1. 범위와 도구

| 대상 | 원천 | 스캔 도구 | 이번 실행 |
|---|---|---|---|
| Backend Python | `backend/requirements.txt`, `requirements-dev.txt` | pip-audit 2.9.0(PyPI·OSV), 심각도는 api.osv.dev | **실행**(로컬, 2026-11-11) |
| PoC Staging 이미지 Python | `poc/staging/backend/requirements.txt` | 같음 | 실행: starlette 7건(같은 버전) |
| Frontend npm | `frontend/package-lock.json`, `frontend/tools/openapi/package-lock.json` | `npm audit` | **실행**: 0건(164개, 33개 패키지) |
| 컨테이너 베이스 이미지 | Dockerfile `FROM` | trivy·grype 미설치 | **NOT_RUN**(설치·승인 필요) |
| 비밀 노출 | 변경 파일 | 기존 비밀 스캔 + T111 시험 | 실행 |
| 이미지 서명·provenance | GitHub Publish | — | **NOT_RUN**(cosign 등 미도입, 제안만) |

**NOT_RUN 항목을 통과로 보지 않습니다.**

## 2. 잠금·고정 정책 (`t118_sbom.py policy`)

| 규칙 | 수준 | 현재 |
|---|---|---|
| Python 직접 의존성은 `==` 고정 | FAIL | 통과(3개 파일 모두) |
| Python 전이 의존성 잠금(해시) | WARN → 승인 후 FAIL 제안 | **없음**. `pip install` 때마다 전이 버전이 바뀔 수 있습니다. 제안: `pip-compile --generate-hashes`로 `requirements.lock` 생성 |
| npm lockfile v2 이상, 모든 패키지에 integrity 해시 | FAIL | 통과(v3) |
| 베이스 이미지 고정 태그(`latest` 금지) | FAIL | 통과(`python:3.12.10-slim`, `nginx:1.27.5-alpine`) |
| 베이스 이미지 digest 고정 | WARN → 승인 후 FAIL 제안 | **없음**(태그만). 같은 태그도 다시 빌드되면 내용이 바뀔 수 있습니다 |

## 3. SBOM

- 생성: `python scripts/supply_chain/t118_sbom.py sbom --resolved <pip-audit.json> --out docs/security/sbom/ai-career-platform.cdx.json`
- 형식은 CycloneDX 1.5입니다. **타임스탬프가 없고**, serial은 구성요소 sha256에서 만듭니다. 같은 입력이면 같은 바이트가 나옵니다(2회 생성 sha256 일치 확인).
- 구성요소 243개:
  - Python 직접 의존성과 스캔 시점의 전이 의존성(`transitive-resolved-at-scan` 표시)
  - npm 전체(integrity 해시 포함)
  - 베이스 이미지 2종(digest `UNPINNED` 표시)
- 직접 의존성을 바꾸고 SBOM을 다시 만들지 않으면 시험이 실패합니다(드리프트 방지).

## 4. 스캔 결과와 조치

### 4.1 수정 전(`t118_scan_before.json`): 30건, 4개 패키지

| 패키지 | 버전 | 건수(심각도) | 조치 |
|---|---|---|---|
| PyJWT | 2.10.1 | 17 (CRITICAL 1, HIGH 5, MODERATE 9, LOW 1, 미분류 1) | **2.15.0으로 상향**(이 PR) |
| python-multipart | 0.0.22 | 5 (HIGH 2, MODERATE 1, LOW 2) | **0.0.31로 상향**(이 PR) |
| pytest(개발용) | 8.3.5 | 1 (MODERATE) | **9.0.3으로 상향**(이 PR) |
| starlette(FastAPI 전이) | 0.46.2 | 7 (HIGH 3, MODERATE 3, LOW 1) | **보류**: FastAPI 0.115.x가 starlette<0.47로 고정. FastAPI 업그레이드는 별도 PR(영향 범위 큼) |

PyJWT 적용성: 앱은 `algorithms=["HS256"]` 고정, 대칭키 하나, JWK·공개키를 쓰지 않습니다. 따라서 키 혼동 계열(CRITICAL·HIGH 대부분)은 **현재 코드에서 경로가 닿지 않는 것으로 판단**합니다. 그래도 같은 2.x 안의 상향이라 비용이 낮아 올렸습니다.

### 4.2 수정 후(`t118_scan_after.json`): 7건, starlette만

| ID | 심각도 | 수정 버전 | 이 앱에서의 적용성(코드 검토) |
|---|---|---|---|
| PYSEC-2026-249 | HIGH | 1.3.1 | urlencoded `request.form()` 제한 무시 → 문서 업로드는 자체 `BoundedMultipartParser`로 `multipart/form-data`만 받음. **경로 없음으로 판단** |
| PYSEC-2026-1942 | HIGH | 0.49.1 | `FileResponse` Range DoS → 앱에서 `FileResponse` 미사용. **경로 없음** |
| PYSEC-2026-2281 | HIGH | 1.1.0 | Windows `StaticFiles` UNC → `StaticFiles` 미사용, 배포는 Linux. **경로 없음** |
| PYSEC-2026-161 | MODERATE | 1.0.1 | Host 헤더 검증 누락으로 `request.url.path` 오염. 미들웨어는 `scope["path"]`를 씀. Nginx 뒤 배치. 추가 확인 필요 |
| PYSEC-2026-1941·2280·248 | MODERATE·LOW | 0.47.2~1.3.0 | 보고 대상(게이트 비차단) |

"경로 없음"은 **코드 검토 결과이고, 공격 재현 시험은 하지 않았습니다.**

## 5. 게이트 (`t118_sbom.py gate`)

- HIGH·CRITICAL·심각도 미분류는 **유효한 예외**가 있을 때만 통과합니다.
  - 유효한 예외: 승인자, 사유, 만료일(오늘 이후)이 모두 있어야 합니다.
- MODERATE·LOW는 보고만 합니다. 수정 기한(제안): MODERATE 30일, LOW 90일.
- 예외 목록 `docs/security/supply_chain_exceptions.yaml`: starlette HIGH 3건이 **승인 대기**(`approved_by` 비어 있음) 상태입니다. 따라서 **현재 판정은 FAIL**입니다.
- PM이 할 결정은 둘 중 하나입니다.
  - (a) 예외 승인. 만료 2026-12-11을 제안하며, 그 전에 FastAPI 업그레이드를 진행합니다.
  - (b) 업그레이드 완료 전까지 릴리스 NO-GO(T120).
- CI 연결: 스캔은 네트워크와 외부 도구가 필요해 **CI에 넣지 않았습니다.** 정책 검사와 게이트 로직은 시험으로 CI에서 돌고, 실제 스캔 결과 파일은 사람이 갱신합니다. CI 스캔 도입은 PM 결정 사항입니다.

## 6. 재현 명령

```bash
python -m venv .audit && .audit/bin/pip install pip-audit==2.9.0
.audit/bin/pip-audit -r backend/requirements-dev.txt -f json -o /tmp/pip-audit.json
(cd frontend && npm audit --json) ; (cd frontend/tools/openapi && npm audit --json)
python scripts/supply_chain/t118_sbom.py policy
python scripts/supply_chain/t118_sbom.py sbom --resolved /tmp/pip-audit.json --out docs/security/sbom/ai-career-platform.cdx.json
python scripts/supply_chain/t118_sbom.py gate --scan <rows.json>
```
