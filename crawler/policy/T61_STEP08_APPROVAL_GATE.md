# T61 STEP 08 — 수집 승인·범위 검사기 (합성 정책만 검증)

> **SOURCE=JOBKOREA / REAL_APPROVAL=HOLD / LIVE_FETCH=NOT_RUN**  
> 이 모듈은 수집 승인을 만들거나 외부에 접속하지 않는다.

## 범위

`crawler/policy/source_approval_gate.py`의 `check_collection_permission(approval, intent)`는 외부 접근 실행 전에 **제공된** 승인 기록을 검증하는 순수 함수다.

- `approval_status != APPROVED`, `enabled != True`, 담당자·근거 부재 → 차단
- 승인 개시 전·승인 검토 기한 도달/초과·시간대 누락 → 차단
- 허용된 잡코리아 HTTPS 상세 URL 이외의 다른 공고·도메인·쿼리 파라미터 → 차단
- 허용된 웹 수집 방법·목적·호출량 범위 이탈 → 차단
- 수집량·보존일·차단신호 중단 정책 부재 → 차단
- 유일한 ALLOWED 테스트는 **가상의 synthetic approval** 객체를 인위적으로 생성한 경우임. 실제 허가가 아니라 정책 함수의 논리 테스트.

### 핵심 제한

1. `APPROVED` 문자열과 `evidence_ref`는 **호출자가 입력한 값일 뿐, 권리자 회신이나 법적 이용권한의 진위를 입증하지 않는다.** 진위와 적용 범위는 T61 검토 책임자가 별도 확인해야 한다.
2. 이 검사는 네트워크 어댑터·Worker에 연결되지 않았다. 현재 Worker는 `synthetic_fixture_only` 모드로 **외부 요청 0회**다. 운영 연계 시 T61 정책 기록의 신뢰 경계, 유효기간, 대상 URL, 중단/로그 방식을 추가 설계·검증해야 한다.
3. 실제 사용하는 User-agent별 robots 규칙, 사이트 이용약관, 접근통제, 권리/저장·가공/삭제 규칙을 이 함수만으로 검사하지 않는다. 이 입력값들의 충족을 외부 정책 검수자가 확인해야 한다.
4. PM/제공자 승인 없는 상태에서는 어떠한 실제 `APPROVED` 정책 객체도 만들지 않는다. `candidate_jobkorea=HOLD`, `enabled=false`는 그대로 유지한다.
5. 허용 URL은 명시된 단일 URL에 정확히 일치하도록 제한하며, 목적도 명시된 범위에서만 허용한다.
6. 이 모듈은 DB 스키마, 저장 데이터, 운영 스케줄, 실제 URL 접근을 변경하지 않는다.

## 테스트

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 225 + 신규 정책 검사 26 = **251개 예상**. CI 및 Windows 로컬 테스트 통과 전에는 완료로 보고하지 않는다.

## 관련 문서

- [출처 레지스트리](../../docs/data/SOURCE_REGISTRY.md)
- [T61 STEP07 공식 문의 초안](../../docs/data/T61_STEP07_JOBKOREA_PERMISSION_INQUIRY.md)
- [T62 STEP09 실제 정확도 검증 준비](../../docs/data/T62_STEP09_LIVE_ACCURACY_READINESS.md)

**판정: POLICY_GATE_IMPLEMENTED_FOR_OFFLINE_TEST_ONLY / LIVE_COLLECTION=HOLD / T62_REAL_ACCURACY=NOT_VERIFIED.**
