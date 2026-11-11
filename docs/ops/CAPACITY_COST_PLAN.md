# 비용·용량 계획과 복구 우선순위 (T149)

> 상태: **PROPOSED**. 목표값(RTO·RPO·보존 기간·경보 기준·예산)은 PM 승인 전입니다.
> - 이 문서의 숫자는 세 종류로 나뉩니다.
>   - **실측**: 로컬 일회용 PostgreSQL 18.6에서 합성 데이터로 잰 값, 또는 코드 상수
>   - **추정**: 실제 데이터가 없어 둔 가정
>   - **제안**: 승인 대기 목표
> - 숫자마다 근거(`basis`)가 [`capacity/t149_assumptions.json`](capacity/t149_assumptions.json)에 있습니다.
> - **Staging·운영 실측은 없습니다**(접속 승인 필요, HOLD). 운영 DB·Secret·스케줄은 변경하지 않았습니다.
> - AI 비용은 전부 추정입니다. AI 운영 일감 **T110이 NOT_STARTED**이고, 모델·단가 계약도 정해지지 않았습니다.

| 파일 | 내용 |
|---|---|
| `scripts/ops/t149_capacity.py` | `measure`(읽기 전용, loopback만), `project`(결정적 계산), `check`(이 문서 ↔ 계산 일치) |
| `scripts/ops/t149_activity_rows.sql` | 행당 바이트 측정용 합성 활동 행(`t149_local_*` DB가 아니면 중단) |
| `capacity/t149_measured_local.json` | 실측 결과 |
| `capacity/t149_assumptions.json` | 가정·제안값과 근거 |
| `capacity/t149_projection.json` | 시나리오별 12개월 예측(계산 결과) |

## 1. 실측 (합성 데이터, 로컬)

만든 방법
1. migration 0001~0003과 T10 Seed를 적용합니다.
2. T147 합성 데이터 공장을 seed 149로 실행합니다.
3. `t149_activity_rows.sql`로 활동 행(행동 이벤트, 감사, AI 사용량, 세션, 추천, 문서 메타데이터)을 넣습니다.

| 규모 | 입력 | career 행 수 | DB 크기(MiB) | 덤프 크기(MiB) |
|---|---|---|---|---|
| s0 | T10 Seed만 | 958 | 11.2 | 0.15 |
| s1 | 사용자 200·회사 30·공고 300 | 30,266 | 18.4 | 1.04 |
| s2 | 사용자 1,000·회사 150·공고 1,500 | 147,093 | 45.9 | 5.82 |
| s3 | 사용자 5,000·회사 750·공고 7,500 | 731,193 | 182.0 | 28.33 |

### 행당 바이트 (s3, 표+인덱스+TOAST)

| 표 | B/행 | 표 | B/행 |
|---|---|---|---|
| behavior_events | 234.3 | recommendation_items | 256.5 |
| audit_events | 250.8 | auth_sessions | 404.4 |
| ai_usage_records | 228.6 | user_documents(메타데이터만) | 408.0 |
| job_postings | 361.1 | job_posting_skills | 154.1 |
| users | 266.0 | user_skills | 163.2 |

### 그 밖의 실측
- **덤프 비율**(`pg_dump -Fc` / DB 크기) = **0.1557**(s3). 합성 데이터라 실제 데이터의 압축률과 다를 수 있습니다.
- **덤프·복원 훈련**(s3, 182 MiB, 3회)
  - 덤프 2.1~2.2초, 복원 4.8~6.1초
  - 복원 뒤 `behavior_events` 300,000행 일치를 확인했습니다. 복원 DB와 덤프는 삭제했습니다.
- **앱 접근 로그 한 줄**(T112 형식) = 135~144 B
- **코드 상한**
  - 문서 업로드 10 MiB(`document_validation.MAX_FILE_BYTES`)
  - 원본 HTML 한 쪽 2,000,000 B(`raw_artifact_store.MAX_HTML_BYTES`)
  - 합성 Fixture HTML 1,343 B(실제 페이지 크기가 아님)

## 2. 가정 (추정·제안)

| 항목 | 값 | 근거 |
|---|---|---|
| 사용자당 월 행동 이벤트 | 300 | 추정 |
| 사용자당 월 감사 이벤트 / 세션 / 추천 실행·항목 | 30 / 15 / 4·40 | 추정 |
| 사용자당 문서 / 평균 크기 | 2개 / 350,000 B | 추정(상한 10 MiB는 실측) |
| 하루 신규 공고 | 200건 | 추정. **실사이트 수집은 HOLD(T61)** |
| 공고당 저장 쪽수 / 쪽 크기 | 1.05 / 150,000 B | 추정. 실제 페이지를 저장한 적이 없음 |
| 원본 HTML 보존 | 30일 | 제안 |
| 요청 수 / 로그 한 줄 / 로그 보존 | 사용자당 하루 20 / 400 B / 30일 | 추정 / 추정(앱 줄 실측 + Nginx 추정) / 제안 |
| 백업 보관 개수 | 14(일 7·주 4·월 3) | 제안(T114 기본값) |
| AI 호출 | 사용자당 월 20회, 입력 2,000·출력 500 토큰 | 추정 |
| AI 단가 | 입력 3, 출력 15 USD / 100만 토큰 | **추정. 견적 아님**. 모델 미정 |
| 디스크 최대 사용률 | 70% | 제안 |

## 3. 12개월 예측 (단위 GiB, AI는 월 USD)

계산 방식
- 사용자는 시작 수에서 12개월 차 수까지 선형으로 늘어납니다.
- 이벤트 행은 누적 사용자-월에 비례합니다. 공고 행은 마감 뒤에도 남아 누적됩니다.
- DB 크기 = s0 기본 크기 + Σ(행 수 × 실측 B/행)
- 백업 = DB × 덤프 비율 × 보관 개수
- 필요 디스크 = 합계 ÷ 0.7

| 시나리오 | 12개월 차 사용자 | DB | 원본 HTML | 문서 | 로그 | 백업 | 합계 | 필요 디스크 | AI 월 비용(USD) |
|---|---|---|---|---|---|---|---|---|---|
| poc | 100 | 0.145 | 0.88 | 0.065 | 0.022 | 0.316 | 1.429 | 2.041 | 27.0 |
| class | 1,000 | 0.692 | 0.88 | 0.652 | 0.224 | 1.508 | 3.955 | 5.65 | 270.0 |
| growth | 10,000 | 6.215 | 0.88 | 6.519 | 2.235 | 13.546 | 29.396 | 41.994 | 2,700.0 |

이 표는 `python scripts/ops/t149_capacity.py check`와 `backend/tests/test_t149_capacity.py`가 계산 결과와 대조합니다. 숫자가 다르면 실패합니다.

### 해석
1. **백업이 가장 큰 항목이 됩니다.** 전체 덤프 14개를 보관하면 growth에서 13.5 GiB로 DB의 2.2배입니다. 보관 개수를 줄이거나(예: 일 7·주 4) 백업 저장소를 분리하는 것이 먼저입니다.
2. **DB에서는 행동 이벤트가 가장 큽니다**(growth에서 약 4.3 GiB). 보존 기간(예: 180일 뒤 집계만 남김)을 정하지 않으면 사용자 수가 같아도 계속 늘어납니다.
3. **원본 HTML은 사용자 수와 무관**하고 보존일과 수집량으로만 정해집니다. 실사이트 수집이 HOLD라 쪽 크기는 추정이며, 실제 수집 승인 뒤 다시 재야 합니다.
4. **AI 비용은 사용자 수에 정비례합니다.** class 규모에서 월 270 USD(가정 단가)입니다. 예산 승인 없이 AI 기능을 켜면 T119 `COST-AI-BUDGET`가 `no_threshold`로 남습니다.
5. 문서 저장량은 growth에서 DB와 비슷한 크기(6.5 GiB)입니다. 암호화·백업 범위는 T144와 함께 정해야 합니다.

## 4. RTO·RPO (제안)

| 대상 | RPO 제안 | RTO 제안 | 근거 |
|---|---|---|---|
| 앱 DB(career) | 24시간(일 1회 덤프, T114) | 1시간 | 실측: 182 MiB 복원 약 6초. growth 6.2 GiB면 선형 추정 약 3~4분이고, 나머지 시간은 확인·전환 |
| 업로드 문서 | 24시간 | 4시간 | 문서 백업 방식 미정(T144). 손실 시 사용자 재업로드 안내 |
| 크롤러 DB(공고·실행 이력) | 24시간 | 4시간 | 공고는 다시 수집할 수 있음(승인된 범위에서) |
| 원본 HTML | 백업 안 함 | — | 재파싱용 임시 자료. 손실 시 재수집 또는 포기 |
| 로그 | 백업 안 함 | — | 30일 보존 뒤 삭제 |

RPO를 24시간보다 짧게 하려면 WAL 보관(PITR)이 필요합니다. 이번 범위 밖입니다.

## 5. 복구 우선순위

1. **로그인·권한**
   - 대상: `users`, `auth_*`, `roles`
   - 이유: 이것 없이는 아무 기능도 안전하게 열 수 없습니다.
2. **개인정보 요청·동의**
   - 대상: `user_consents`, `account_deletion_requests`, 감사 이벤트
   - 이유: 법적 의무와 처리 기한이 있습니다.
3. **사용자 자료**
   - 대상: 프로필, 경력, 기술, 문서 메타데이터 → 문서 파일
4. **채용공고 조회**
   - 대상: `job_postings` 등 공고 표(읽기 전용으로 먼저 열 수 있음)
5. **추천·분석·AI**
   - 다시 계산할 수 있으므로 뒤로 둡니다. AI 기능은 비용 경보를 확인한 뒤 켭니다.
6. **크롤러 수집 재개**
   - 마지막에 둡니다. T154 체크포인트에서 재개하며, 403/429/CAPTCHA가 나오면 중단합니다.
7. **행동 이벤트·로그 보충**
   - 손실을 허용합니다. 집계에 공백이 있었다고 기록합니다.

## 6. 경보 기준 (제안)

| 지표 | 주의 | 위험 | 연결 |
|---|---|---|---|
| 디스크 사용률(DB·백업·문서 볼륨) | 70% | 85% | T113 경보 규칙에 추가 제안 |
| DB 주간 증가율 | 계획 대비 +50% | 계획 대비 +100% | `t149_capacity.py measure` 주간 비교 |
| 최신 백업 나이 | — | RPO(24시간) 초과 | T114 `freshness`, T113 A-BACKUP-STALE |
| 복원 훈련 | 마지막 훈련 후 30일 | 90일 | T114 |
| AI 월 비용 / 예산 | 80% | 100% | T119 `COST-AI-BUDGET`(예산 승인 필요) |
| 원본 HTML 저장량 | 계획(0.88 GiB)의 150% | 200% | T152 보존 정리 |

## 7. 재현 방법 (로컬 일회용 DB)

```bash
createdb -E UTF8 -T template0 t149_local_s0
psql -d t149_local_s0 -c "CREATE SCHEMA career"
psql -v ON_ERROR_STOP=1 -d t149_local_s0 -f database/migrations/0001_initial_schema.sql   # 0002·0003도 같은 방식
psql -v ON_ERROR_STOP=1 -d t149_local_s0 -f database/seeds/0001_initial_seed.sql
createdb -T t149_local_s0 t149_local_s3
python database/fixtures/synth_factory.py --target-env local --seed 149 --users 5000 --companies 750 --postings 7500 --out-sql s3.sql
psql -v ON_ERROR_STOP=1 -d t149_local_s3 -f s3.sql
psql -v ON_ERROR_STOP=1 -d t149_local_s3 -f scripts/ops/t149_activity_rows.sql
python scripts/ops/t149_capacity.py measure --db-url postgresql://<user>@127.0.0.1:<port>/t149_local_s3 --label s3 --dump
python scripts/ops/t149_capacity.py project --out docs/ops/capacity/t149_projection.json
python scripts/ops/t149_capacity.py check
```

측정한 DB는 모두 삭제했습니다.

## 8. 결정 필요 (PM)

1. 보존 기간
   - 행동 이벤트, 세션, 원본 HTML, 로그
   - 백업 보관 개수
2. RTO·RPO 목표와 문서 백업 방식(T144와 함께)
3. AI 월 예산, 모델·단가 확정(T110)
4. Staging 실측 승인
   - 읽기 전용 `measure`
   - 디스크 용량 확인
   - 실제 데이터 크기로 하는 복원 훈련
5. 디스크·비용 경보를 T113 규칙에 넣을지 여부
