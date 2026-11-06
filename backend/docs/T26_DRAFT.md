# T26 Skill Gap 계산 초안

Redmine #1530. `app/services/skill_gap.py`는 외부 API·DB와 연결되지 않은 순수 계산 함수다. T04 FR-ANL-002의 검토 중 요구사항을 기준으로 `max(요구 - 보유, 0)`을 사용하며, 미입력 계산은 0으로 하되 원본 `None`과 미등록/미기재 구분을 결과에 남긴다. 필수·선택은 표기만 하며 가중치에 영향을 주지 않는다. 동점은 코드순으로 정한다. 모두 팀 승인 전 제안이다.

값은 1~5 정수, 코드 중복·빈 코드 등은 거부한다. 결과는 자기평가 기반이며 합격 확률이 아니다. 사용자 인증·권한, 실제 코드 정규화, 직무·사용자 데이터 조회, API·DB·이력 저장, 합의된 DTO 및 CI는 구현하지 않았다. T05/T06/T17/T25의 최신 계약이 필요하다. 예제만으로 전체 기능 완료를 주장하지 않는다.

백엔드 폴더에서 `python -m pytest tests/test_skill_gap.py -q`를 실행한다.

## T05 병합본과 대조 (2026-11-06)

T05 PR #17은 main `a004efb`에 병합됐다. 데이터 사전은 아직 DRAFT/PM·DB 리뷰 대기이며 DDL 미적용이다. `user_skills.proficiency`는 NULL을 허용하고 계산 시 0으로 취급한다. `skill_gap_items.observed_level`은 NULL이 아닌 0~5 계산 스냅샷이다. 현재 함수는 원본 수준을 `None`으로 보존하므로 DB 저장용 0과 직접 동일시하면 안 된다. 저장 변환과 미등록/미입력 표시의 DTO 연결은 미구현·확인 필요다. `model_versions.kind='rule'`이며 `approved_at`이 NULL이면 서비스 사용 금지다. T06 PR #29 역시 리뷰 중인 초안이다.

`to_snapshot_example`은 결과의 미입력 `None`을 계산 스냅샷의 0으로 바꾸는 가상 변환이며 원본은 변경하지 않는다. `skill_code`는 예제 식별자이고 실제 DB의 UUID·assessment_id 매핑, 저장 및 권한 검사는 포함하지 않는다.
