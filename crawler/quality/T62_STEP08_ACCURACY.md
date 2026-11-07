# T62 STEP 08 — 증빙 기반 공고 추출 정확도 평가 (오프라인)

## 이 단계에서 확인 가능한 것

`crawler/quality/offline_accuracy.py`는 STEP 07 파서 출력과 명시적으로 작성된 `GoldCase.expected`를 필드별로 비교한다. 사이트 HTTP 호출, DB, 브라우저, 파일 쓰기는 하지 않는다.

- `MATCH`: 사람이 확인한 참조값과 정확히 일치
- `MISMATCH`: 두 값이 있으나 일치하지 않음
- `MISSING`: 참조값이 있으나 파서 추출값이 없음. **정확도 분모에 포함**
- `NOT_VERIFIED`: 정답 데이터가 없거나 `None`으로 선언됨. 일치로 간주하지 않음
- `NOT_SUPPORTED`: 학력·경력·급여·지원 상태 등 현재 STEP07 스키마에서 지원하지 않는 필드. 추출 성공으로 계산하지 않음

현재 비교 대상 필드는 공고번호·제목·회사명·근무지·고용형태·게시일·마감일 등 7개이며, 지원하지 않는 4개 필드는 보고서에 남긴다. `status='published'`는 STEP07 임시 기본값이므로 **실제 접수 중 여부에 대한 정답으로 평가하지 않는다**.

## 계산식

- `compared = MATCH + MISMATCH + MISSING` (정답이 명시된 지원 필드만)
- `exact_match_rate = MATCH / compared`
- `coverage_rate = (MATCH + MISMATCH) / compared`
- `mismatch_rate`는 필요 시 `MISMATCH / compared`로 계산 가능하며, 근거 없는 필드는 분모에서 제외
- `compared=0`이면 정확도는 **null / NOT_MEASURABLE**, 100%가 아님
- 다중 케이스는 정확히 검증 가능한 필드 수를 기준으로 micro-average. 합성·실제 증빙을 섞어서 집계하면 오류
- 보고서는 필드 판정과 건수만 출력하고 원문 공고·원시 추출값·비밀번호를 담지 않는다.

## 공고 50246410 처리 원칙

`https://www.jobkorea.co.kr/Recruit/GI_Read/50246410`은 향후 실제 정확도 검증의 지정 대상이다. **현재 저장소에 승인된 이 공고의 실제 HTML 사본이나 사람이 검증한 Golden Truth가 없다.** STEP07/STEP08 테스트의 동일 공고번호는 URL 형식 시험용이며, 제목 `합성 공고`, 회사 `가상회사`는 실제 공고 내용이 아니다.

아직 실제 정답/HTML이 없으면 `GoldCase`를 임의로 생성해 실제 정확도 수치를 보고하지 않는다. 실제 HTML 확보 전에는 `REAL_NOT_VERIFIED` 상태를 유지한다.

실제 사이트 정확도 검증을 진행하려면 아래 증빙이 필요하다.

1. T61의 HTML 획득·이용·보존 권한에 대한 승인 근거
2. 특정 시점에 허용된 방식으로 확보한 HTML (시각·SHA·출처 URL·공고번호 기록)
3. 사람이 확인한 필드별 정답, 출처 근거, 검수자, 검수 시각, 미확인 필드는 `None`
4. 동일 시점 또는 변경 이력을 고려한 정답과 추출값 비교
5. 필드별 오류 사례 보완과 독립 재검증

`provenance=real_authorized` 및 `evidence_ref`는 **호출자가 제공한 기록**일 뿐 법적 허가 사실을 검증하지 않는다. 보고서 `real_site_accuracy_verified`는 보수적으로 **항상 false**이며, 실제 사용 권한·출처·원본/정답의 진위를 별도로 확인하기 전에는 PASS로 격상하지 않는다.

## 테스트 / 병합

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 204개 + STEP08 신규 21개 = **총 225개 예상**. Windows 로컬 PASS 및 최신 GitHub CI SUCCESS 이후 병합. 실제 사이트 검증은 T61 승인 뒤 STEP09에서 별도 확인.

## HOLD

실제 잡코리아 네트워크 수집, 로그인/차단 우회, 운영 스케줄, DB 마이그레이션, 관리자 API와 운영 연동은 이번 단계에서 수행하지 않는다.
