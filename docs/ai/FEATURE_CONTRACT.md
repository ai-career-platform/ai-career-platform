# AI·ML 공통 데이터·Feature 계약 초안 (T25)

상태: **설계·합성 테스트 기준선 ACCEPTED / 실제 연동 HOLD**. PR #26은 2026-11-09 병합됐다. T04 PR #13은 병합됐으나 요구사항 문서는 PM 승인 전이며, T05 PR #17은 main에 병합됐고 데이터 사전은 DRAFT이며, T06 PR #29는 병합됐으며 해당 API 구현·CI 검증은 별도다. 아래는 검토를 돕는 제안이며 운영 DB, API, 개인정보 처리 정책을 확정하지 않는다. 원본: [T25](../work-orders/initial-30/T25.md), [AI 구조](../AI_SYSTEM_ARCHITECTURE.md), [API 초안](../API_CONTRACT.md), [DB 초안](../../database/FULL_DATABASE_MODEL.md). 담당자 및 PM의 검토가 필요하다.

## 1. 목적과 용어

Feature(피처)는 계산이나 모델에 넣는 정보다. 예를 들어 `Python 요구 수준 3`과 `사용자 자기평가 1`은 Skill Gap의 입력 후보이다. 이 문서는 입력의 의미·출처·사용 가능 시각·버전과 검증 방법을 일관되게 정리한다. 실사용자 정보가 아닌 합성 예제만 사용한다.

- 기준 시각(`decision_time`): 결과를 계산한다고 가정하는 시점.
- 발생 시각(`event_time`): 입력의 원인이 된 일이 실제로 일어난 시각.
- 사용 가능 시각(`available_at`): 시스템이 그 입력을 실제로 사용할 수 있게 된 시각. 발생 시각만으로 접근 가능했다고 가정하지 않는다.
- 누수: 판단 시점에 알 수 없었던 정보를 미리 사용하는 등 평가 결과를 왜곡하는 일.
- 라벨: 모델이 학습·평가에서 맞혀야 하는 정답. 규칙 기반 계산에 학습용 라벨이 반드시 필요한 것은 아니다.

## 2. 일곱 기능의 입력 후보

명칭과 범위는 `docs/AI_SYSTEM_ARCHITECTURE.md`의 ML01~07 후보를 따른다. 실제 모델이나 데이터셋이 존재한다는 뜻은 아니다.

| 후보 | 입력 후보 | 출력 후보 | 평가·미결 항목 |
|---|---|---|---|
| ML01 직무·공고 적합도 | 사용자 기술, 직무·공고 요구 기술 | 설명 가능한 적합도 | 점수 의미와 정답 확보 여부 |
| ML02 개인화 랭킹 | 허용된 행동, 구직 의도, 공고 특징 | 추천 목록·순위 | 동의 범위, 시간 분할과 평가 기준 |
| ML03 Skill Gap | 사용자 기술 수준, 직무 요구 수준 | 부족 기술과 수준 차이 | 미입력·필수/선택 처리, 전문가 기준 |
| ML04 사용자·직무 군집 | 허용된 기술 벡터·집계 특징 | 군집 코드 | 동의, 안정성·공정성 및 의미 |
| ML05 시장 추세 예측 | 출처가 허용된 기간별 관측 지표 | 미래 기간별 예측 | 사용권, 관측 시점, 시간순 평가 |
| ML06 행동 기반 추천 | 동의된 조회·저장 이벤트 | 개인화 후보·점수 | 동의 철회, 보존, 콜드스타트 |
| ML07 이상 탐지 | 허용된 접속·데이터 품질·행동 집계 | 이상 점수·표시 | 정답 확보, 오탐 처리, 보존 정책 |

## 3. 공통 메타데이터 후보

아래 예제 형식은 **검토용**이다. 실제 필수성·이름·자료형은 T05/T06 및 PM 결정 후 확정한다.

| 항목 | 예시 의미 | 확인 사항 |
|---|---|---|
| `entity_id` | 가상 사용자 또는 대상 식별자 | 개인 데이터 식별·접근 정책 |
| `feature_id` | 합성 예제의 피처 식별자 | 실제 식별 체계·버전과 연결 방식 미확정 |
| `event_time` | 입력의 사건 발생 시각 | UTC 등 시간대·정밀도 |
| `available_at` | 입력이 사용 가능해진 시각 | 지연 수집 및 수정 이력 |
| `decision_time` | 계산을 수행하는 기준 시각 | 기능별 기준과 저장 위치 |
| `source_id` | 가상 데이터 출처 식별자 | 이용 허가·라이선스·버전 |
| `feature_version` | 입력 규칙의 버전 | 변경·호환·승인 담당 |
| `dataset_version`, `split` | 합성 학습/검증 데이터 버전·구분 | 추론에는 불필요할 수 있음 |
| `usage_basis` | 데이터 사용 권한 근거의 예시 | 동의 필요성·철회·법적 근거는 팀 정책 결정 |

## 4. Skill Gap 예시와 결정 필요 항목

직무의 Python 요구 수준 3, 사용자의 자기평가 수준 1이라는 **가상 예시**에서 차이는 2다. 병합된 T04 문서 `FR-PRF-001`과 `FR-ANL-002`는 1~5 척도, 미입력 시 계산에 0 사용 및 화면에 미입력 표시를 제안한다. 병합된 T05 데이터 사전은 `user_skills.proficiency`의 NULL을 보존하고, `skill_gap_items.observed_level`에는 계산용 0을 기록하는 안이다. 데이터 사전에는 DRAFT·PM/DB 리뷰 대기 상태가 표시되어 있다. PM 결정에 따라 원본 `미입력` NULL과 계산 시 변환된 0은 구분해 보존한다. 실제 이력·화면 표시 방식은 별도 검토한다. 실제 구현은 필수·선택 기술, 범위, 누락 값, 점수/설명, 이력과 동의에 대한 합의가 필요하다.

## 5. 시점·분할·출처·개인정보

검토용 기본 원칙: `event_time <= available_at <= decision_time`. 이 순서는 예제 검증 규칙이며 모든 데이터에 보편적으로 적용되는 확정 정책이 아니다. 예외(예정 이벤트 등)는 도메인별로 정한다. ML 학습에서는 train/validation/test 구분을 버전별로 기록하고, 시간 역전과 동일 사용자·공고 및 유사 항목 중복을 점검한다. 정확한 분할 단위·기준일·레이블 확보 시점은 미결이다.

출처별 수집·학습·표시 허용 범위, 개인정보 최소화, 접근권, 보존 및 동의 철회·삭제의 파생 데이터 전파는 관련 담당자와 확정한다. 동의 여부의 단순 문자열은 실제 권한 검증을 대체하지 않는다. 실데이터, 비밀, 이력서 원문을 예제에 넣지 않는다.

## 6. 모델·평가 기록과 미결 질문

DB 초안의 `model_versions` 및 `model_evaluations`와 모델 코드/버전, 데이터 버전, 평가 시점·지표·결과를 연결하는 방안을 검토한다. 규칙 기반 버전 표현, 해시, 보존·삭제 및 DB/API 매핑은 T05/T06 담당자 확인 전 미확정이다.

1. T05 데이터 사전의 미결 정책 및 T06 API 계약의 최종 승인 버전은 무엇인가?
2. 1~5의 의미와 요구 수준의 출처는? 원본 NULL과 계산 결과 0을 화면·이력에서 어떻게 구분할 것인가?
3. 일곱 후보의 실제 범위, 입력별 필수 여부와 권한·동의 근거는?
4. 각 모델의 기준 시각, 라벨 정의·확보 시점, 분할 기준과 평가 지표는?
5. 삭제·동의 철회 시 파생 피처, 학습 데이터, 모델 및 결과의 처리 책임은?

## 7. 검증 및 한계

`python -m unittest discover -s tests/t25 -v`는 합성 fixture에 대한 시간 순서, 필수 메타데이터, 출처 식별 및 결정적 검증 결과를 확인한다. 이것은 **예시 검증**이며 T25 전체 스키마·권한·실제 데이터 누수·모델 성능을 검증하지 않는다. PR #26은 설계·합성 테스트 기준선으로 병합됐다. 해당 HEAD `28f1c5a`의 전용 CI는 24건을 통과했다. 실제 연동 검증은 별도다.

추가 합성 데이터 실험에서는 같은 가상 사용자 ID가 학습과 시험 양쪽에 등장하면 경고한다. 이는 중복으로 평가가 부풀려지는 상황을 이해하기 위한 **검토용 예시**다. 실제로 사용자·직무·공고 중 무엇을 분리할지와 시간 기준은 모델 및 데이터 특성에 따라 팀이 결정해야 한다. 단순 ID 비교는 유사 항목, 전체 기간 순서, 라벨 누수 또는 모든 형태의 중복을 찾아내지 못한다.

## 8. 선행 상태 재확인 (2026-11-06)

- T04 PR #13과 T05 PR #17은 병합됐다. T05 데이터 사전은 DRAFT / PM·DB 리뷰 대기 / DDL 미적용 상태를 명시한다. PR 설명에는 PostgreSQL 대상 버전 재검증 및 CI 연결이 남아 있다.
- T06 PR #29는 OpenAPI 문서를 병합했다. 실제 API 구현 및 T06 검사 CI 연결은 별도다.
- 기준 `origin/main` 0f34dd6. 선행 문서 내용과 상태는 변할 수 있으므로 실제 확정·구현·통합 전 최신 버전을 재확인한다.

## 9. T04 요구사항과 T25 입력 후보 연결 (검토용)

| T04 문서 | 요구사항 초안 | T25에서 확인할 데이터 | 결정·검증 상태 |
|---|---|---|---|
| [FR-PRF-001](../requirements/functional/PROFILE.md#fr-prf-001-보유-기술-관리) | 표준 기술과 자기평가 수준 1~5 또는 미입력 | 기술 코드, 입력 수준, 미입력 여부, 입력 시점 | 척도 세부 의미와 원본/계산값 분리 확인 |
| [FR-JOB-002](../requirements/functional/JOB.md#fr-job-002-직무-상세) | 직무별 기술과 요구 수준 1~5 | 직무·기술 코드, 요구 수준, 기준 버전·출처 | 출처 및 변경 이력 확인 |
| [FR-ANL-002](../requirements/functional/ANALYSIS.md#fr-anl-002-skill-gap-분석) | 차이 계산, 미입력 안내, 결과 시점 기록 | 기준 시각, 입력 스냅샷, 계산 규칙 버전 | T05·T06의 필드 및 보존 방법 검토 |
| [FR-ANL-001](../requirements/functional/ANALYSIS.md#fr-anl-001-적합도-확인) | 점수와 계산 근거, 합격 확률 아님 | 입력과 산출물, 규칙 버전 및 한계 | 점수 공식·평가·인증 계약 확인 |

`tests/t25/skill_gap_example.json`은 정보 출처와 미입력 표시를 설명하는 합성 예다. 숫자는 임의이며 실제 DB 또는 API 구조라고 가정하지 않는다. T04 병합이 PM 승인이나 T05·T06 완료를 뜻하지 않는다.

## 10. 시점 기준 선택 및 평가 기록 연결 예시 (검토용)

`select_available_example`은 합성 관측값 가운데 기준 시각까지 이용 가능했던 가장 최근 항목을 고르는 예시다. 늦게 들어온 값은 제외하고, 가장 최근 시각이 같은 항목이 둘 이상이면 임의로 고르지 않고 오류를 낸다. 입력 순서를 바꿔도 결과가 같으며, 이용 가능한 항목이 없으면 `None`이다. 합성 feature_id를 포함해 같은 대상·피처·feature_version·dataset_version·split만 허용한다. 이 예제는 실제 저장소 조회·권한·수정 이력·시간대 정책을 구현하지 않는다. 이 규칙은 팀 합의 전 제안이다.

평가 재현성 검토 시 DB 초안의 `model_versions.model_version_id`와 `model_evaluations.model_version_id` 연결, `dataset_ref`, 지표 및 평가 시각을 확인한다. 데이터셋/피처 버전, 분할 방법, 기준 시각, 코드 버전 및 출처/사용 권한은 별도 기록 후보이며 기존 DB 컬럼에 이미 있다고 가정하지 않는다. 실제 스키마·저장 위치와 보존 기간은 T05/T06 및 담당자와 협의한다. 삭제·동의 철회 시 데이터와 파생 산출물 처리도 미결이다.

## 11. 병합된 T05 사전과 대응 (2026-11-06 확인)

근거: [T05 데이터 사전 v0.2](../../database/DATA_DICTIONARY.md), main 병합 `a004efb`. 이 링크는 PR 기준 main 병합 후 확인 가능하다. 사전은 DRAFT이며 실제 DDL 적용이나 개인정보 처리 검증을 의미하지 않는다.

| 대상 | T05 사전의 후보 | T25/후속 작업에서의 주의 |
|---|---|---|
| 입력 | `user_skills.proficiency`: NULL 또는 1~5; `job_role_skills.required_level`: 1~5 | 원본 NULL은 미입력으로 유지하고 계산에만 0 사용 |
| 결과 | `skill_gap_items.observed_level`: 0~5, `gap = greatest(required_level - observed_level, 0)` | 계산 시점 복사값이다. 미입력임을 결과에 어떻게 표시할지 DTO·화면에서 확인 |
| 모델 | `model_versions`: `kind`는 rule/ml/llm, `approved_at` NULL은 서비스 사용 금지 | T26/T27도 rule 버전 후보. 초안 버전을 승인된 서비스 모델로 간주하지 않음 |
| 평가 | `model_evaluations`: 필수 `dataset_ref`, `metric_code`, `metric_value`, `leakage_checked`, `evaluated_at` | boolean 하나로 누수 부재를 증명할 수 없다. 데이터/피처 버전, 분할·검사 방법·증빙 저장 위치는 별도 협의 |
| 삭제 | 사용자 원본·관련 행의 삭제 규칙과 문서 원본·인덱스 정리는 별도 책임 | 데이터셋·파생 feature·학습된 모델의 삭제/재학습 정책은 미확정 |

T06 [PR #29](https://github.com/ai-career-platform/ai-career-platform/pull/29)의 OpenAPI는 병합된 계약 문서다. 그 형식에 맞춘 실제 API 연결은 승인·담당자 협의 후 검증한다. 과거 `d82a29d` CI는 job 없이 종료됐으나 이후 `28f1c5a`의 T25 전용 CI가 24건 통과했다. 각 후속 변경의 CI는 해당 커밋에서 별도 확인한다.

## 12. 병합된 T06 계약과 후속 확인 (2026-11-06)

T06 [PR #29](https://github.com/ai-career-platform/ai-career-platform/pull/29)는 `d1fae3a`에 병합됐지만 문서·검증 도구이며 실제 API 구현이 아니다. PR 작성자는 해당 검사의 CI 미연결로 PARTIAL을 보고했다. SkillGapItem의 observed_level 0은 미입력 표시를 위한 계산값이며 원본 user_skills.proficiency NULL과 구분한다. DTO에는 미등록/미기재 구분 필드가 없으므로 별도 구분이 필요한지 협의한다. model_version은 응답에 필요하지만 T25의 가상 문자열이 승인된 모델 ID를 대신하지 않는다. RecommendationRunRequest는 limit 1~50, 기본 20이며 항목별 reason이 필요하다.


## 13. PR #26 리뷰 보완: 합성 Feature 입력 계약 표 (2026-11-09)

> **DRAFT / HOLD for integration.** 아래는 `tests/t25/fixtures.json`의 합성 예제에 대한 검증 규칙이지, 실제 사용자 데이터의 승인된 스키마가 아니다. 실제 운영 필수성·소유권·보존·권한은 T05/T06·PM 결정이 우선한다.

| 필드 | 합성 예제 필수 여부 | 형식·NULL | 입력·출력/버전·출처 규칙 | 미확정 사항 |
|---|---|---|---|---|
| `entity_id` | 필수 | 공백 아닌 문자열; NULL 불가 | 동일 가상 대상 식별 및 split 교차 확인; 원본 사용자 ID라고 보장하지 않음 | 운영 식별자/가명처리 및 접근 권한 |
| `feature_id` | 필수 | 공백 아닌 문자열; NULL 불가 | Feature 종류를 식별. 입력별 버전과 함께 관리 후보 | 실제 코드 체계 및 변경이력 |
| `event_time` | 필수 | 타임존 포함 ISO 8601 문자열 | 사건 발생 시각; 합성 예제에서 `available_at`보다 늦으면 거부 | 현실의 예약·예정 이벤트 예외 |
| `available_at` | 필수 | 타임존 포함 ISO 8601 문자열 | 관측값이 사용 가능해진 시각; 판단시점 이후 값은 Feature로 금지 | 백필·수정 이력의 실제 보존 방법 |
| `decision_time` | 필수 | 타임존 포함 ISO 8601 문자열 | 가상 판단 시점. 결과 계산에 쓰인 시점의 증빙 후보 | 사용자별/모델별 실제 기준시각 |
| `source_id` | 필수 | 문자열; 합성 테스트는 `synthetic-fixture`만 허용 | 원본 출처·사용 범위를 참조하는 후보. 실데이터 권한 검사 아님 | T61/T05 `data_sources` 연계·사용 허가 |
| `usage_basis` | 필수 | 문자열; 합성 테스트는 `synthetic-only`만 허용 | 예제에 실데이터가 섞이지 않게 제한 | 개인정보 동의·철회·권리 근거/범위 |
| `feature_version` | 필수 | 공백 아닌 문자열; NULL 불가 | 같은 계산 규칙을 재현하기 위한 가상 버전 | 배포·마이그레이션·승인 버전 방식 |
| `dataset_version` | 필수 | 공백 아닌 문자열; NULL 불가 | 합성 분할을 함께 재현하기 위한 식별자 | 평가 데이터 등록·보존·재학습 정책 |
| `split` | 필수(합성 학습 예제만) | `train` / `validation` / `test`; NULL 불가 | 데이터 누수 방지 검증용 구분; 일반 추론 요청에는 요구하지 않음 | 그룹·시간 분할의 모델별 정책 |
| `label_available_at` | 선택(추가 합성 감사 테스트) | 타임존 포함 ISO 8601 또는 NULL | 라벨이 생긴 시각. 라벨이 **정답(target)** 이면 판단시점 이후도 가능하지만, **Feature 입력**으로 사용하려면 당시 이용 가능해야 함 | 라벨 의미·예측 기간·라벨 수집 경로 |
| `label_used_as_feature` | 선택(추가 합성 감사 테스트) | boolean, 기본 false | true일 때 미래 라벨·누락 라벨 사용을 거부하는 테스트용 표시 | 실제 입력 라인리지 자동 확인 방법 |
| `group_id`, `content_fingerprint` | 선택(추가 합성 감사 테스트) | 공백 아닌 문자열 또는 NULL | 같은 그룹/표준화된 지문이 서로 다른 분할에 있으면 경고 | 유사문서 그룹화 알고리즘·검토 책임 |

**도메인 입력 별도 규칙:** `job_role_skills.required_level`은 1~5 정수이며, `user_skills.proficiency`는 1~5 또는 NULL(미입력)이다. 이들은 위 공통 메타데이터에 곧바로 추가되는 필드가 아니다. 계산 스냅샷에서만 미입력 NULL을 0으로 바꾸는 안이며, 실제 입력된 0으로 원본을 덮어쓰지 않는다. `feature_id`, `dataset_version`, `available_at` 등을 실제 DB에 이미 저장하고 있다고 가정하면 안 된다.

## 14. PR #26 리뷰 보완: 합성 데이터 누수 검사와 한계

기존 `test_contract_example.py` 12건은 필수 메타데이터·시점·동일 entity 분할·기준시점 선택을 검증한다. 신규 `test_leakage_guard.py` 12건은 다음을 추가로 검토한다.

1. 사건·사용 가능·판단 시각이 잘못됐거나 타임존이 없으면 오류를 기록한다.
2. 미래에 이용 가능해진 관측값을 입력으로 사용하는 예제를 검출한다.
3. 판단 당시 이용할 수 없던 라벨을 **입력 Feature**로 쓰면 검출한다. 단, 판단 후 확정되는 학습용 정답 라벨 자체를 금지하지는 않는다.
4. 동일 가상 entity, 그룹 ID 또는 표준화 지문이 학습·검증·시험을 넘나들면 검출한다.
5. 합성 분할의 결정시각 범위가 겹치거나 역전되면 검출한다(보수적 시간 분할 예제).
6. 잘못된 split·플래그·날짜·입력 형식의 거부 사례를 검사한다.

`content_fingerprint` 검사는 대소문자·공백 정규화 수준에 그치므로 의미가 유사한 문서/공고의 중복을 발견하지 못한다. `group_id`도 사전에 올바르게 배정됐다는 가정이 필요하다. 이 테스트는 **실제 데이터 누수 없음, 편향 없음, 개인정보 보호 완료를 증명하지 않는다.** 학습 데이터의 라벨링 시점, 전처리 학습 범위, 재수집·변경 시점, 모델별 그룹/시간 분할과 데이터 접근 권한은 별도 검토가 필요하다.

로컬 추가 테스트: `python -B -m unittest discover -s tests/t25 -p 'test_leakage_guard.py' -v` → 신규 12건 PASS(합성 테스트 코드 자체 검증). 전체 테스트와 GitHub Actions는 새 커밋·실제 CI 실행 결과를 별도 확인한다. 이 PR에는 `.github/workflows/t25-feature-contract.yml`을 추가해 Python 3.12에서 **T25 전용 테스트**를 독립 실행하도록 했다. GitHub 워크플로 실행/승인 정책 때문에 실행되지 않았다면 CI PASS로 보고하지 않는다.

## 15. T05·T06 필드 매핑 및 불일치 (재검토용)

| 입력·산출 | T05 데이터 사전 | T06 OpenAPI | T25 판단/추가 협의 |
|---|---|---|---|
| 사용자 기술 | `user_skills.user_id`, `skill_id`, `proficiency`(NULL 또는 1~5) | Skill Gap은 사용자의 보유 기술을 기반으로 산출 | NULL 원본은 보존; 원본 부재와 미입력 NULL 구분 여부는 DB/Backend 담당자 확인 |
| 직무 필요 기술 | `job_role_skills.job_role_id`, `skill_id`, `required_level`(1~5) | `SkillGapRequest.job_role_id`, SkillGapItem의 required_level | ID→코드 변환, 기준 시점의 요구 수준 이력 미확정 |
| 계산 결과 | `skill_gap_items.required_level`, `observed_level`(0~5), `gap` | `SkillGapItem` 필수 `skill`, `required_level`, `observed_level`, `gap` | 원본 NULL은 계산용 0으로만 변환; DTO에 원본 미입력 여부 별도 필드 없음. 화면 표시 정책 결정 필요 |
| 실행 버전 | `model_versions.model_version_id`, `model_code`, `version`, `kind`, `approved_at` | `SkillGap.model_version`은 ModelVersionRef | 규칙 `kind=rule`도 등록 대상. 승인 전의 합성 버전 문자열을 실제 승인 모델처럼 반환하지 않음 |
| 평가 | `model_evaluations.model_version_id`, `dataset_ref`, `metric_code`, `metric_value`, `leakage_checked`, `evaluated_at` | 별도 관리자 평가 조회 DTO | 검사 범위·데이터셋/스플릿·라벨 시점 증빙이 `leakage_checked` 하나로 확보되지는 않음 |
| 출처·기준 시각 | 합성 메타데이터의 `source_id`, `available_at`, `decision_time`과 직접 동일한 DB 컬럼 계약 미확인 | 모든 AI 응답에 이 메타데이터가 동일하게 실리는 계약 아님 | 별도 lineage/snapshot 저장 위치·출처 권리·동의/삭제 전파 책임 결정을 요구 |
| RAG 접근·삭제 | 사용자 문서·청크·검색 결과의 실제 인가/정리 동작 미검증 | `askKnowledge` 설명은 검색을 Q&A 내부에서만 사용 | PM 결정: 별도 외부 검색 API 없이 askKnowledge 내부 검색. T15 인증 재사용 및 조회 전·반환 전 검사. 인가 구현과 색인 정리 지연·재시도 검증은 HOLD |

## 16. 리뷰 결정 대기 목록 및 작업 경계

| 우선 | 결정 요청 | 결정 필요 역할 | 상태 |
|---|---|---|---|
| P0 | T25 필드별 운영 필수성, `available_at`/version/출처 저장 위치와 API 공개 여부 | PM·DB(T05)·API(T06)·AI 담당 | OPEN / DRAFT |
| P0 | 모델별 라벨 가용 시각, 그룹·시간 분할, 중복/유사도 검사 기준 | AI/데이터 담당·PM | OPEN / DRAFT |
| P0 | 실제 동의 철회·삭제 시 파생 feature·데이터셋·모델·색인 전파와 중단 조건 | 개인정보/보안·DB·AI·PM | OPEN / HOLD |
| P1 | 미입력 원본 NULL과 계산값 0의 API/화면 표시·이력 의미 | DB·Backend(T26/T43)·Frontend(T44) | OPEN / DRAFT |
| P1 | 내부 검색에서 권한 변경·삭제·동의 철회 시 fail-closed와 색인 정리 지연·재시도 검증 | T15/T49/T53/T54·Backend | 원칙 결정 / 구현·검증 HOLD |

**현 상태:** `T25_DOCUMENT_BASELINE=ACCEPTED`, `T25_REAL_INTEGRATION=HOLD`. 이 보완은 계약 문서와 합성 테스트·CI 정의에 한정하며, 운영 DB/Schema/Seed, 실제 API, 인증, 실제 사용자 데이터, Staging, 배포는 변경하지 않았다. CI가 실제 실행돼 PASS하고 미결 결정을 담당자가 승인하기 전에는 '완료'로 표시하지 않는다.


## 17. PM 결정 반영 (2026-11-09)

근거: [PR #26 PM 결정](https://github.com/ai-career-platform/ai-career-platform/pull/26#issuecomment-6730998767). 설계·합성 테스트 기준선은 수용됐으며 실제 PostgreSQL·API·권한·Staging 구현 승인을 의미하지 않는다.

- 1차 구현 순서: **Skill Gap(ML03) 먼저**, 직무·공고 적합도(ML01) 다음. ML02/ML06 개인화·행동 추천은 후속 단계, ML04/ML05/ML07은 연구·확장 후보다.
- T05/T06을 재사용하고 이번 범위에 새 테이블이나 별도 Feature Store를 만들지 않는다. 출처·버전과 event_time/available_at/decision_time을 검증 가능한 최소 메타데이터로 정의하되, 운영 DB의 필수 컬럼·저장 위치는 후속 단계에서 DB 담당과 확정한다.
- 사용자 원본 `user_skills.proficiency=NULL`은 보존하고 계산 결과의 `observed_level=0`과 구분한다. 실제 데이터 기반 API의 완료 기준에는 PostgreSQL 연동 검증이 필요하다.
- RAG 검색은 1차에서 별도 외부 API를 신설하지 않고 기존 `askKnowledge` 내부에서 사용한다. 기존 T15 인증을 재사용하며 조회 전과 결과 반환 전 문서 접근권을 확인한다. 권한 미확인·해제·삭제·동의 철회 문서는 제외한다(fail-closed).
- 인덱스 정리의 이벤트·지연·재시도·검증 방법은 T53/T54 및 Backend 담당과 협의한다. 정리가 늦더라도 접근 차단이 우선이다. 실제 인가·삭제 전파·DB/API 구현은 여전히 HOLD다.
