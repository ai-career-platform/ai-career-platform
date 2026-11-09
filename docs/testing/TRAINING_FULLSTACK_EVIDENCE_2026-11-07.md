# AI Career Platform — 합성 크롤러 Full-Stack 로컬 실습 검증 보고서

> **기록 기준일:** 2026-11-07 (KST)  
> **판정:** `LOCAL_FULLSTACK_TRAINING=PASS` (확인된 범위만) / `PRODUCTION_DEPLOYMENT=NOT_TESTED` / `LIVE_JOBKOREA_COLLECTION=NOT_RUN`  
> **근거의 성격:** PM과 실습자가 대화에서 공유한 Windows PowerShell 실행 출력 및 Swagger/브라우저 스크린샷 확인. 스크린샷 원본을 이 공개 GitHub 저장소에 첨부하거나 저장하지 않았음.

## 1. 범위 및 안전 경계

- **학습 목적:** 합성 채용공고 Fixture → 정규화/품질 검사 → 격리된 로컬 PostgreSQL → 별도 학습용 FastAPI → JavaScript 카드 UI.
- **대상 데이터:** 가상기업 Alpha/ Beta의 공고 `SYNTH-AX-001`, `SYNTH-AX-002` (실제 채용공고 아님).
- **전용 DB:** `ai_career_crawler_training`; 스키마/테이블 `crawler_training.postings`; 계정 `crawler_student`(비슈퍼유저).
- **실습 API:** `backend.training_jobs_api:app`, `GET /jobs`, `GET /training`; `127.0.0.1:8001`에서만 실행.
- 실제 잡코리아 요청, 실공고 HTML 취득·정확도 실증, 정식 `backend/app/main.py` 및 운영 `frontend/` 연동, 운영 DB 배포·운영 보안 검증은 **범위 밖**.
- 잡코리아 권리·이용조건 확인에 따른 실제 수집 승인은 **없음(HOLD)**. 프로젝트 교육 범위에서 공식 문의 발송·추가 승인관리 작업은 **SKIP**으로 결정했으며, 이 결정이 실제 사이트 수집 허가를 의미하지는 않음.

## 2. Windows 로컬 확인 결과

| 검증 단계 | 관찰된 실행 결과 | 판정 |
|---|---|---|
| 합성 Worker 메모리 실행 | `fetched=2`, `normalized=2`, `inserted=2`, `external_requests=0`, `status=SUCCEEDED` | PASS |
| 같은 메모리 저장소 재실행 | 최초 `FIRST: 2 0`, 재실행 `SECOND: 0 2` (inserted/unchanged) | PASS |
| 저장소 단위 테스트 | `Ran 7 tests ... OK` | PASS |
| Worker 품질 통합 테스트 | `Ran 9 tests ... OK` | PASS |
| 전체 크롤러 테스트 | `Ran 278 tests in 0.100s ... OK` (T61 STEP10 브랜치) | PASS (당시 HEAD 기준) |
| 학습 DB/테이블 확인 | DB `ai_career_crawler_training` 및 `crawler_training.postings` 존재 | PASS |
| DB 권한 | `crawler_student` 비슈퍼유저/로그인 가능; USAGE, SELECT, INSERT, UPDATE = true | PASS |
| DB 사전 상태 | 합성 공고 ID 2건; 001 제목에 `(변경 테스트)` 부가 | PASS |
| 사전 백업 | `crawler_training_backup.sql` 크기 1698 bytes, 2026-11-07 19:41:58 KST 확인 | FILE_EXISTS; RESTORE_NOT_TESTED |
| Python DB 연결 | `DB_CONNECTION=PASS` (두 개발 폴더에서 연결 확인) | PASS |
| PostgreSQL 갱신 | `inserted=0`, `updated=1`, `unchanged=1`, `db_writes=1`, `status=SUCCEEDED` | PASS |
| PostgreSQL 반복 실행 | `inserted=0`, `updated=0`, `unchanged=2`, `db_writes=0`, `status=SUCCEEDED` | PASS |
| DB 최종 제목 조회 | 001: `AI 데이터 분석 실습 개발자`; 002: `Python 백엔드 개발 실습`; 총 2건 | PASS |
| 학습 FastAPI 테스트 | PR #81에서 `Ran 6 tests ... OK` | PASS (당시 HEAD 기준) |
| 학습 Backend+Frontend 테스트 | PR #82에서 `Ran 10 tests in 0.053s ... OK` | PASS (당시 HEAD 기준) |
| Swagger | `GET /jobs?limit=20` → HTTP 200 / JSON 공고 2건 확인 | PASS |
| 카드 UI | `GET /training` 정상 표시, 2건 카드에 제목·가상기업·지역·고용형태 표시 | PASS |
| 재조회 버튼 클릭 후 결과 유지 | 실행 결과 별도 미수신 | NOT_VERIFIED |
| 장애 복구/운영 접근제어/대용량 성능 | 실습 범위 외 | NOT_TESTED |

**테스트 수 유의:** 크롤러 278개, 학습용 API/Frontend 10개는 서로 다른 모듈과 시점에서 각각 실행한 **별도 테스트 결과**다. 단일 통합 명령에서 288개를 실행했다고 주장하지 않는다. GitHub CI의 `SUCCESS`는 해당 워크플로의 결과이며, CI가 이 288개 테스트를 모두 실행했다는 뜻은 아니다(현재 워크플로는 주로 smoke/automation 검증).

## 3. 실패 사례와 해결 이력

1. **Python DB 인증 실패:** `fe_sendauth: no password supplied`. 학습 계정의 비밀번호를 로컬 PowerShell 프로세스 환경변수 `PGPASSWORD`로 설정한 뒤 `DB_CONNECTION=PASS` 확인. 비밀번호 값은 공개 문서와 채팅에 기록하지 않음.
2. **Frontend 404:** 이전 별도 폴더 `C:\dev\ai-career-platform-t62-step04`의 Uvicorn 실행 중 `/training` 경로 없음. 새로운 Frontend 코드가 있는 `C:\dev\ai-career-platform`에서 실행해 `/training` HTTP 200 확인.
3. **Frontend API 503:** 브라우저 화면은 정상이나 `GET /jobs`가 503. 새로운 PowerShell 세션에 DB URL/비밀번호 환경변수가 없어 발생한 것으로 확인; 동일 세션에 학습용 연결값을 설정하고 Python 연결 PASS 확인 후 재시작해 카드 2건 표시.
4. **테스트 파일명 오기:** 처음 안내한 `crawler.tests.test_storage_memory`는 없는 모듈. 실제 `crawler.tests.test_storage` 실행으로 7/7 PASS.

## 4. 관련 GitHub 변경 및 검증 이력

| PR | 내용 | 병합 커밋 |
|---|---|---|
| [#79](https://github.com/ai-career-platform/ai-career-platform/pull/79) | 실사이트 Worker 실행 경계 차단 | `1da01e235035f459022abac32a85006edaa36377` |
| [#80](https://github.com/ai-career-platform/ai-career-platform/pull/80) | 공식 문의 증빙 상태관리 오프라인 구현 (운용 단계 SKIP) | `7ae521275821c288cc3372cdd4a8a9e98d7c93d5` |
| [#81](https://github.com/ai-career-platform/ai-career-platform/pull/81) | 학습용 FastAPI `GET /jobs` | `046fc07679019bf899e1f6e2f437c89a87959a24` |
| [#82](https://github.com/ai-career-platform/ai-career-platform/pull/82) | 학습용 HTML/JavaScript 공고 카드 `/training` | `1c8320467c6ab37fd684d5cda192700583d3c04b` |

위 PR들은 개별 Windows 테스트 PASS 및 당시 GitHub CI SUCCESS를 확인하고 Squash Merge됨.

## 5. 재현 가이드 (DB 데이터 변경 없이 조회만)

학습용 DB와 계정은 **이미 설치·프로비저닝된 로컬 개발 PC**를 전제한다. `CRAWLER_LOCAL_DATABASE_URL`과 `PGPASSWORD`는 현재 PowerShell 세션에만 설정하고 비밀값을 공개 저장소/공유 로그에 넣지 않는다.

```powershell
# 저장소 최상위에서 테스트 (모의 DB, 외부 네트워크 요청 없음)
py -3.12 -m unittest discover -s crawler/tests -v
py -3.12 -m unittest discover -s backend/training_tests -v

# 조회용 학습 서버 시작 (DB URL/비밀번호 설정 완료 후)
py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001
```

- 브라우저: http://127.0.0.1:8001/docs → `GET /jobs` 실행.
- 브라우저: http://127.0.0.1:8001/training → 합성 공고 2건 카드 확인.
- 서버 종료: 실행 터미널에서 `Ctrl+C`.
- 로컬 백업 파일 `crawler_training_backup.sql`은 프로젝트 작업 폴더에만 두고 **GitHub에 커밋하지 않기**. 파일 존재·크기 확인과 복원 성공은 별개의 검증이다.

## 6. 현재 결론 및 남은 범위

- **완료:** 합성 Fixture 기반 로컬 크롤러, 메모리/PG 멱등성, DB 조회, 독립 FastAPI 조회 API 및 카드 UI의 사용자 확인.
- **미완료/미검증:** 실제 채용 사이트 활용 허가·실데이터·정확도, 정식 서비스 API/Frontend/인증, 운영 및 부하 테스트, 백업 복원 검증, 재조회 버튼 직접 클릭 검증.
- **교육 범위 결정:** 추가 공식 문의·승인 워크플로 확장은 중단(SKIP). 실제 잡코리아 접근 차단 로직은 유지.
- **다음 학습 후보:** 현재 합성 데이터에 대한 검색/필터/페이지네이션 또는 AI 분석. 신규 구현은 별도 작업으로 진행.
