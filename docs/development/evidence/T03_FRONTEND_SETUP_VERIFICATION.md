# T03 — Frontend 개발환경 가이드 실행 검증 결과

> 검증일 2026-11-06 · Windows 11 Pro 10.0.26200 · 개인 PC 로컬 Docker 전용(Staging 변경 NO)

## 검증 환경
| 항목 | 결과 |
|---|---|
| Git | 2.55.0.windows.3 |
| VS Code | 1.145.0 |
| Docker / Compose | 29.7.2 / v5.5.0, OSType `linux` |
| Node.js | 설치되어 있으나 사용하지 않음(`package.json` 없음 — 가이드 정책과 일치) |
| `.env` | `.env.example` 복사 후 무작위 로컬 비밀번호로 변경, `.gitignore`로 제외 확인 |

## 실행 결과 (STEP 02~06)
| 단계 | 명령 | 결과 |
|---|---|---|
| STEP 02 | `Get-ChildItem .\poc\staging\frontend` | `Dockerfile`, `index.html`, `nginx.conf` — PASS |
| STEP 03 | `Select-String index.html 'fetch','/api/'` | `/api/health`, `/api/version`, `/api/health/db` 상대경로 호출 — PASS |
| STEP 05 | `docker compose --env-file .env config --quiet` | exit 0 — PASS |
| STEP 05 | `docker compose --env-file .env up --build -d` / `ps` | db·backend·frontend 모두 healthy, `127.0.0.1:18080->80` 만 바인딩 — PASS |
| STEP 06 | `GET /api/health` | 200 `{"status":"ok","service":"ai-career-backend"}` |
| STEP 06 | `GET /api/version` | 200 `{"application":"ai-career-platform","environment":"staging-poc","version":"0.1.0"}` |
| STEP 06 | `GET /api/health/db` | 200 `{"status":"ok","service":"ai-career-database"}` |
| STEP 06 | 브라우저 `http://127.0.0.1:18080/` | `Backend connection: Connected`, `Backend version: 0.1.0`, `PoC status: Operational`, Console 오류 0 — PASS |

## 예외/거부 케이스
| 케이스 | 결과 |
|---|---|
| 미구현 `GET /api/v1/jobs` | 404 (가이드 기대값과 일치) |
| 로컬 `db` 컨테이너만 `stop` | `/api/health` 200, `/api/health/db` **503**, 화면 `PoC status: Degraded` (수 초간 `Checking...` 후 전환) |
| 로컬 `db` 재시작 | 약 10~15초 후 `/api/health/db` 200 복구 |

## 가이드 보완 사항 (본 PR 반영)
1. STEP 05: 첫 실행 직후 frontend `health: starting` 대기 안내 추가
2. STEP 06: 예외 케이스(404 / DB 중지 503·Degraded) 재현·복구 명령 추가, `Checking...` 지연 원인(`connect_timeout=3`) 명시
3. STEP 11-1 신설: 로컬 PoC 안전한 중지 방법(`stop`/`down`, `-v` 금지)
4. STEP 12: 브랜치명을 작업지시서 규칙 `task/t##-short-name`으로 통일

## 미검증 / HOLD
- Mock 데이터 연결(STEP 08): 기능 API 계약(T06) 미확정으로 HOLD — T19에서 진행
- 다른 Origin 직접 호출 시 CORS(STEP 07): 현재 CORSMiddleware 없음, 별도 Origin 앱이 없어 미검증
- 빌드/Lint/테스트: `package.json` 없음 → 해당 없음
