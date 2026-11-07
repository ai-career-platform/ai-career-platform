# T63 STEP 04 — 로컬 PostgreSQL 통합 검증 (롤백 전용)

## 목적

T63 STEP 03의 Batch Worker + 품질 게이트 + `PostgresPostingStore`를 **기존 Windows 학습용 PostgreSQL에 연결하여** 검증합니다. 기존 데이터를 보존하기 위해 테스트용 외부 공고 ID를 매 실행마다 무작위로 생성하고, **전체 테스트를 하나의 외부 트랜잭션에 묶은 뒤 강제로 ROLLBACK**합니다.

이 문서는 **새로운 SQL Migration이나 운영 배포 지시서가 아닙니다.**

## 안전 조건

- 실행 대상은 로컬 `ai_career_crawler_training` 데이터베이스, 기존 `crawler_training.postings` 테이블 및 전용 비관리자 사용자만 허용
- `CRAWLER_LOCAL_PG_TEST=1`을 지정한 경우에만 실행; 일반 `unittest discover`에는 포함되지 않음
- `CRAWLER_LOCAL_DATABASE_URL`은 기존에 안전하게 설정된 환경변수를 그대로 사용하며, 채팅/PR/로그에 DSN·비밀번호를 출력하지 않음
- `crawler/tests/local_pg_integration.py`는 신규 합성 ID만 사용; 기존 공고를 업데이트하지 않음
- 테스트용 INSERT/UPDATE는 외부 트랜잭션 종료 전에 강제로 롤백하고 이후 `get()`으로 해당 ID가 남지 않았는지 검증
- PostgreSQL 연결/SQL 오류나 테스트 실패로 예외가 발생하더라도 트랜잭션 컨텍스트에서 롤백 처리
- 외부 사이트 호출 0; JobKorea 실제 요청/재게시 확인/권한 승인과 무관

## 실행 (Windows PowerShell, 저장소 루트)

먼저 현재 설정을 확인합니다. **비밀번호를 출력하지 마세요.**

```powershell
if ($env:CRAWLER_LOCAL_DATABASE_URL) { "LOCAL_DSN_SET" } else { "LOCAL_DSN_MISSING" }
```

기존 세션에 학습용 DSN이 안전하게 설정되어 있고 현재 PC의 로컬 PostgreSQL이 실행 중인 경우에만:

```powershell
$env:CRAWLER_LOCAL_PG_TEST = "1"
py -3.12 -m unittest crawler.tests.local_pg_integration -v
```

기대되는 테스트: `Ran 2 tests` / `OK`. 환경변수가 없는 상태에서는 `skipped`이며 **DB 통합 검증 PASS로 판정하면 안 됩니다.**

일반 오프라인 테스트는 기존 `84 tests` 유지:

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

## 점검 범위

1. Insert 2건 → 동일 Fixture 재처리 Unchanged 2건 → 제목 변경 Update 1건, 다른 1건 Unchanged
2. 기존 공고의 source URL 변경은 Review로 보류, 유효하지 않은 공고와 중복은 미저장, 사유별 집계 확인
3. 모든 테스트 합성 행이 트랜잭션 롤백 후 조회되지 않음을 검증
4. CI에는 실제 PostgreSQL 연결 검증 증빙이 없으므로 CI PASS와 사용자 Windows DB 실증을 **별도 표기**

## 완료 판정

- GitHub CI PASS
- Windows 일반 테스트 84/84 PASS
- Windows 로컬 PG 통합 테스트 2/2 PASS (skip 0)
- 테스트 실행 후 학습용 PostgreSQL 기존 공고 유지
- T61의 실제 사이트 접근 승인 게이트는 여전히 HOLD
