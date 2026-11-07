# T61 STEP 10 — 외부 문의 증빙 인수·검토 상태 흐름 (오프라인)

> 기준: 잡코리아 단일 공고 `50246410`의 HTML 정확도 검증 허용 여부 문의  
> **CURRENT_STAGE=DRAFT_NOT_SENT / SOURCE_APPROVAL=HOLD / LIVE_CRAWLER=DISABLED**

## 목적

공식 회신이 오기 전에 승인 사실을 만들어 내지 않고, 나중에 답변을 받은 경우에도 **문의 발송, 회신 수신, 실무 검토, PM 승인**을 혼동하지 않도록 절차를 분리한다.

`crawler/policy/inquiry_evidence.py`는 다음 오프라인 상태를 지원한다.

| 상태 | 의미 | 실사이트 수집 허용? |
|---|---|---|
| `DRAFT_NOT_SENT` | 발송 증빙 없음 | 아니오 |
| `SENT` | 실제 발송 시각 및 비공개 발송 증빙 ID 기록 | 아니오 |
| `RESPONSE_RECEIVED` | 수신 시각 및 비공개 회신 증빙 ID 기록 | 아니오 |
| `NEEDS_CLARIFICATION` | 모호한 회신, 추가 확인 필요 | 아니오 |
| `REVIEW_COMPLETE` | 응답 검토 완료(거절 또는 PM 검토 후보) | 아니오 |

검토 결과: `HOLD` / `DENIED` / `CANDIDATE_FOR_PM_REVIEW`의 세 값만 가능하다. **`APPROVED` 전환은 제공하지 않는다.** 공식 승인과 내부 PM 승인/수집 범위·접근 방법의 독립 검토는 T61 SOURCE_REGISTRY의 **별도 절차**를 통해서만 가능하다. 이 모듈의 `collection_approved`는 항상 `False`다.

## 증빙 기록 정책

- 송신/수신 증거 ID는 비공개 저장소의 **불투명 참조 ID**만 받는다.
- 발송·수신 날짜는 UTC 시간대 정보가 있는 시각만 허용한다.
- 발송 전 회신 등록, 회신 없이 검토, 수신 전 검토, 승인 상태 오용을 거절한다.
- 응답·검수 문서 원문, 이메일 주소, 담당자 이름 등은 GitHub에 쓰지 않는다.
- `public_summary()`에는 상태와 승인 불가 여부만 기록한다.
- 회신이 없다는 이유로 상태를 자동 승격하지 않는다.

## 현재 상황

- T61 STEP07 문의 초안: `docs/data/T61_STEP07_JOBKOREA_PERMISSION_INQUIRY.md`
- **문의 발송 증빙 없음:** `DRAFT_NOT_SENT`
- **공식 회신 증빙 없음:** `NOT_RECEIVED`
- T61 잡코리아 사용승인: `HOLD`
- T62 STEP09 실공고 HTML/Golden Truth: `NOT_AVAILABLE` / `NOT_VERIFIED`
- 운영 실행: `HOLD`

## 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 261개 + 신규 17개 = **278개 예상**. 실사이트 HTTP, 메일 발송, 파일 입출력, DB 변경 없음.

**본 단계는 승인증빙 메타데이터 처리 규칙의 테스트일 뿐, 실제 문의를 발송하거나 이용권한을 취득한 사실을 뜻하지 않는다.**
