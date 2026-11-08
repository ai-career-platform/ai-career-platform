# T154 Night Activation Checklist

본 STEP23에서는 아래 운영 변경을 수행하지 않는다. 기존 T64 Timer, DB 스케줄 및 Auto-CD 설정을 보존한다.

## 활성화 전 필수 확인

- [ ] 승인된 main SHA와 스테이징 이미지/SHA, PR 리뷰 및 CI Smoke Test/offline-tests 일치 확인.
- [ ] 기존 공고 7건의 식별자/행 지문, 앱 DB 51개 테이블의 건수/행 지문, 컨테이너 ID, 볼륨, 기존 runs/events 기록 보존 기준 확보.
- [ ] 0009 Attempt 테이블까지 포함한 최신 전용 크롤러 DB 전체 백업을 고유 경로에 생성. 기존 백업은 덮어쓰지 않는다. SHA-256, pg_restore 목록, 독립 PostgreSQL 실제 복원, 테이블/제약/시퀀스/행 지문을 확인.
- [ ] 전용 DB 이름 `ai_career_crawler_training` 확인. 0010이 없을 때만 승인된 파일을 수동 적용. 0002~0009 및 이미 적용된 0010 재실행 금지. 새 STEP23 Migration은 없음.
- [ ] runtime의 Slot SELECT/INSERT, Attempt SELECT/INSERT/UPDATE 및 Worker 기존 권한 검증. 다른 계정 세션은 종료하지 않는다. 본인 계정·고유 application token·정확한 PID에 한한 DB 정리 동작을 확인.
- [ ] T64 schedule enabled=false/mode=fixture, T64 timer disabled/inactive, Auto-CD 정상 확인. 본 one-shot으로 T64를 활성화하지 않는다.
- [ ] 원본 공고와 구별되는 synthetic keyword/job/payload/raw 준비. Raw metadata의 job_id, mode, payload ID가 일치하고 Fixture 파일 SHA가 올바른지 확인. 실제 사이트 요청 금지.
- [ ] 적용 대상 Ubuntu/Python/PostgreSQL에서 TERM 무응답 → KILL → 자식 회수 → DB backend/lock 정리를 짧은 격리 데드라인으로 재검증. Supervisor SIGTERM 경로도 검증. DB 장애/권한 부족이면 활성화 HOLD.

## 향후 승인된 실행 구성

명령 예시(인증정보는 비공개 환경에만 설정):

```sh
python -m crawler.jobs.fixture_night_executor once --job-id <prepared-synthetic-job-uuid> --raw-root <dedicated-fixture-root> --log-file <private-summary-jsonl>
```

- [ ] 30분 간격의 외부 호출은 별도 검수 후 구성. 이번 변경에는 Timer 설치/enable/start가 없다. 기존 T64 및 Auto-CD unit은 수정하지 않는다.
- [ ] 승인된 날짜 범위와 최종 종료일을 외부 호출기에도 명시. 과거 슬롯 재생/Persistent catch-up 금지. 08:00 이후 신규 호출 중단. 본 코드는 현재 KST 슬롯만 예약한다.
- [ ] 야간 22개 슬롯과 작업당 3회 Attempt는 서로 다른 제한임을 확인. COMPLETED 작업은 재실행하지 않는다. RETRYABLE의 다음 슬롯 실행도 명시적 정책 하에서만 호출한다.
- [ ] 기본 120초 제한, 2초 TERM 유예 및 2초 DB 정리 예산 확인. 남은 시간이 정리 예산 이하이면 시작하지 않는다. 자식이 종료돼도 DB 쿼리가 남을 수 있으므로 DB 정리 결과까지 확인.

## 모니터링

- [ ] JSONL invocation 수와 실제 Attempt/Worker 실행 수, 신규 공고 수를 구분한다. rejected invocation은 Slot/Attempt가 없을 수 있다.
- [ ] night_date/slot_index/job_id, 시작/종료 시각, 상태, attempt_count, processed_postings, error_code, termination_reason, external_http_requests=0, db_cleanup=PASS, cleanup_before_deadline=true 확인.
- [ ] Job COMPLETED/Attempt IN_PROGRESS 등 state_mismatch 또는 requires_manual_review 발견 시 자동 재실행 금지.
- [ ] PostgreSQL fixture_night_slots, fixture_job_attempts, keyword_jobs, raw_parse_results, keyword_checkpoints를 읽기 전용으로 교차 확인. 비밀번호/DSN/Raw/예외 원문을 로그에 출력하지 않는다.

## 중단 및 복구

- [ ] 신규 호출을 중지하고 실행 중 Supervisor에 정상 종료 신호를 전달한다. 단순히 Supervisor만 SIGKILL하지 않는다.
- [ ] 자식 및 해당 DB PID/고유 application token의 세션과 잠금이 사라졌는지 확인. 다른 서비스/계정 세션을 종료하지 않는다.
- [ ] 미완료 Attempt IN_PROGRESS는 수동 검수 대상으로 유지한다. 임의 RETRYABLE/COMPLETED 변경, 횟수/시퀀스 초기화 금지.
- [ ] 상태 불일치 시 공고/Lineage/Checkpoint가 이미 COMMIT됐는지 먼저 조회한다. 완료된 Worker를 다시 실행하지 않는다.
- [ ] 원본 공고/앱 테이블 지문, 컨테이너/볼륨, Auto-CD, T64 비활성 상태를 다시 확인. 전체 백업 복원은 별도 승인 없이 실행하지 않는다.
- [ ] 종료 후 야간 호출기를 inactive/disabled로 확인하고 Evidence를 보존. 테스트 파일 삭제 차단 우회 금지.
