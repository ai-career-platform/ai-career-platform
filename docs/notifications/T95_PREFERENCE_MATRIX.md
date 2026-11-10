# T95 — 알림 유형·수신 설정 매트릭스 (PROPOSED)

> 상태: **PROPOSED / 미승인.** 알림·수신 설정은 [프로젝트 개요](../requirements/overview/PROJECT_OVERVIEW.md)에서 **1차 범위 제외**(T95~T97)입니다. 아래는 MVP 이후 설계안입니다.
> 계약 본문: [T95_NOTIFICATION_CONTRACT.md](T95_NOTIFICATION_CONTRACT.md) · 표 형식은 시험(`test_t95_notification_contract.py`)이 읽어 일관성을 검사합니다(열 이름·순서를 바꾸면 시험도 함께 고침).

## 알림 유형

| type | 분류 | 필수 | 수신 동의 | 기본 | 사용자 끄기 | 채널 | 조용한 시간 | 중복 방지 창 | 최대 재시도 | 발송 기록 보존 | 템플릿 승인 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| security.password_reset | 계정 보안 | 예 | - | 켬 | 불가 | email | 무시 | 5분 | 3 | 1년 | 미승인 |
| security.password_changed | 계정 보안 | 예 | - | 켬 | 불가 | email | 무시 | 5분 | 5 | 1년 | 미승인 |
| security.new_login | 계정 보안 | 예 | - | 켬 | 불가 | email | 무시 | 60분 | 5 | 1년 | 미승인 |
| account.email_verification | 이메일 인증 | 예 | - | 켬 | 불가 | email | 무시 | 5분 | 3 | 90일 | 미승인 |
| account.recovery_notice | 계정 복구 | 예 | - | 켬 | 불가 | email | 무시 | 5분 | 3 | 1년 | 미승인 |
| account.deletion_receipt | 탈퇴 처리 안내 | 예 | - | 켬 | 불가 | email | 무시 | 24시간 | 5 | 1년 | 미승인 |
| service.policy_change | 서비스 안내 | 예 | - | 켬 | 불가 | email | 적용 | 24시간 | 5 | 1년 | 미승인 |
| service.maintenance | 서비스 안내 | 아니오 | service_updates | 켬 | 가능 | email | 적용 | 24시간 | 3 | 90일 | 미승인 |
| recommendation.new_results | 추천 결과 | 아니오 | recommendation_alerts | 끔 | 가능 | email | 적용 | 24시간 | 3 | 90일 | 미승인 |
| marketing.newsletter | 선택적 마케팅 | 아니오 | marketing_notification | 끔 | 가능 | email | 적용 | 7일 | 2 | 90일 | 미승인 |

용어:
- **필수**: 서비스 이용·보안에 필요해 동의 없이 보냅니다(법률 검토 필요). 수신 동의 철회와 관계없이 발송됩니다.
- **수신 동의**: 선택 알림을 보낼 근거인 동의 코드입니다(`consent_policies.policy_code` 제안값). `-` = 동의 없이 발송(필수).
- **조용한 시간**: 사용자 시간대(기본 Asia/Seoul) 21:00~08:00입니다. "적용"이면 다음 08:00으로 미루고, "무시"면 즉시 보냅니다.
- **중복 방지 창**: 같은 (사용자, type, 대상) 묶음 키는 이 시간 안에 한 번만 보냅니다.

## 동의 코드 (제안)

| policy_code | 필수 | 현재 | 비고 |
|---|---|---|---|
| service_updates | 아니오 | 없음(신규) | 점검·기능 안내 |
| recommendation_alerts | 아니오 | 없음(신규) | 새 추천 결과 |
| marketing_notification | 아니오 | 없음(신규) | 광고성 정보. **정보통신망법상 별도 동의·야간 제한 검토 필요(법무)** |

현재 선택 동의는 `llm_processing`, `behavior_tracking`(T31·T71)뿐입니다. 위 코드를 추가하려면 Seed·`OptionalConsentInput` 변경이 필요합니다(T05·T31 후속, 승인 후).
