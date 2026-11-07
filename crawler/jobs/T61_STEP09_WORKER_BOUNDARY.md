# T61 STEP 09 — Worker 실행 경계 통합 테스트

> 범위: 기존 합성 Fixture Worker의 호출 진입점에서 실사이트 모드를 **명시적으로 차단**.  
> 상태: **LIVE_COLLECTION=HOLD / T62_REAL_ACCURACY=NOT_VERIFIED**

## 변경 내용

`crawler/jobs/run_crawler.py`는 기존처럼 `synthetic_fixture_only`로 실행된다. T61 STEP08의 독립 정책 검사기와 혼동하지 않도록 `collection_mode`를 추가했다.

- **Python `run(..., collection_mode="live_jobkorea")`** → 즉시 `ValueError`; Fixture Adapter·Store 접근 전 중단
- **CLI `--collection-mode live_jobkorea`** → 종료 코드 `2`; `psycopg` import/DB 접속/Fixture 읽기 전 중단
- **CLI `--collection-mode external_api`** → 허용하지 않는 choice로 종료 코드 `2`
- **기본 synthetic 모드** → 기존과 동일하게 Memory Store/합성 Fixture 실행
- **승인 기록이 있다고 주장해도** 해당 값을 Worker에 전달하거나 실사이트 모드를 열 수 없음

테스트 `crawler/tests/test_worker_collection_boundary.py` 10개는 승인 객체의 단순 필드값이 실사이트 모드를 허용하지 않음, live/잘못된 모드 거부, DB 접속·Adapter 미호출, 기존 합성 경로 유지 여부를 검증한다.

### 핵심 한계

- 현재 **실제 크롤러/네트워크 어댑터는 아예 없다.** 이 테스트는 '실수집 차단' 경계를 검증하는 것이지 실제 수집이 허용됐을 때의 통합 경로가 구현됐다는 뜻이 아니다.
- T61 STEP08 `check_collection_permission`은 순수 함수이며 실제 승인 근거 진위를 확인하지 않는다.
- **운영에선 T61 승인과 별도 구현/테스트, robots/약관/요청량·중단·보존/삭제 규칙 검토가 완료된 후**에만 실수집을 고려할 수 있다.
- 이번 변경으로 PostgreSQL, 기존 JobKorea Adapter, HTML/Golden Dataset, T64 스케줄러, 운영 배포 설정을 변경하지 않았다.
- 실제 공고 `50246410`의 정확도는 여전히 `NOT_VERIFIED`.

## 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 **251개 + 신규 10개 = 261개 예상**. Windows 로컬과 GitHub CI를 확인한 뒤 PR 병합.

**결론: T61_STEP09=OFFLINE_BOUNDARY_READY (검증 후); SOURCE_APPROVAL=HOLD; LIVE_CRAWLER=NOT_IMPLEMENTED.**
