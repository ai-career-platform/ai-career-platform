# T153 STEP04 — 스테이징 E2E runtime 권한 충돌 수정

## 사용자 보고 (기준 SHA `de6c3ad419f547720cba5dc47c7c54ff2675d067`)

- 0006 Migration **PASS**; runtime Fixture E2E **FAIL**.
- `RawParseLedger.process()`의 `raw_artifacts SELECT ... FOR UPDATE`가 `InsufficientPrivilege` 발생: runtime은 이 테이블에서 SELECT/INSERT만 허용.
- 테스트 트랜잭션 롤백, 기존 7개 공고·앱 51개 테이블·서비스·볼륨 보존. Scheduler false/Fixture, Timer disabled/inactive, Live HOLD.
- Parse lineage/INVALID/중복/rollback E2E는 그 구간까지 도달하지 않아 **검증 미완료**.
- STEP03에서 실패 주입 검사가 이력 INSERT 단계까지 도달했는지 확인하지 않아 **최종 이력 INSERT 실패에 대한 원자적 rollback 증거로 인정할 수 없음**.
- 사용자 제공 로컬 Evidence(원문은 GitHub 코디네이터가 미열람): `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t153-step04-evidence.json`, `t153-step04-smoke-diagnostic.log`, `t153-step04-final-preservation.log`.

## 수정 범위

`RawParseLedger.process`에서 `SELECT ... FOR UPDATE` 제거. 대신 트랜잭션 시작 시 `pg_advisory_xact_lock(hashtextextended(artifact_uuid::text, 0))` 실행 후 SELECT 수행. 같은 Raw artifact에 대한 처리 요청을 직렬화하고, 트랜잭션 commit/rollback 시 자동 해제된다.

- **권한 변경 없음**: raw_artifacts UPDATE 권한을 추가하지 않음.
- **스키마 변경 없음**: 0006은 그대로 재사용.
- 신규 offline 단위 테스트로 잠금 실행 순서와 `FOR UPDATE` 부재를 확인.
- PostgreSQL advisory lock은 동일 잠금 키를 사용하는 호출자 사이에서만 직렬화한다. 임의의 DB 직접 수정까지 차단하는 권한 수단은 아니다.

## 우선순위 높은 실제 재검증

1. 격리 DB에서 runtime SELECT/INSERT 권한만으로 성공하는지 우선 확인(필요할 경우 다른 권한 오류 확인).
2. 스테이징에 이미 0006 적용되어 있으므로 **0006 재적용 불필요**. 동일 코드 배포 여부 확인 후 fixture-only E2E 재검사.
3. 최종 이력 INSERT만 **명시적으로 실패**하도록 격리 DB에서 일회성 오류 주입(예: 별도 테스트 전용 연결/주입)하고, 그 전에 posting UPSERT와 발견 관계 변경이 발생했음을 기록한 다음 예외 발생 후 둘 다 롤백되는지 확인. 이전의 타입 오류만으로 합격 처리 금지.
4. 정상 Raw→Posting/lineage, INVALID, 동일 버전 멱등, 버전 라벨별 이력, 기존 데이터 보존 확인. Live HTTP, Worker, Timer, Auto-CD 설정 변경 없음.
5. 사용자가 정책 차단된 테스트 데이터 폴더를 삭제하도록 우회하지 않음.

**이 PR의 GitHub CI PASS는 실제 스테이징 runtime E2E PASS를 뜻하지 않는다.**
