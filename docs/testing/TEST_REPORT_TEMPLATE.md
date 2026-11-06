# 테스트 실행 보고서 (복사용 양식)

> 각 개발자는 실행 후 대괄호 값을 교체합니다. **기대 결과를 실제 PASS로 쓰지 마세요.**

## 1. 기본 정보

- Redmine Issue: [URL]
- 담당 개발자 / 리뷰어: [이름 또는 GitHub ID]
- PR URL: [URL]
- 브랜치 / HEAD SHA: [branch] / [40자리 SHA]
- 실행일시(시간대): [YYYY-MM-DD HH:mm KST]
- 환경: [OS, Python/Node/PostgreSQL/브라우저 버전]
- 변경 범위: [한두 문장]

## 2. 테스트 실행 결과

| 영역 | 실행 명령 | PASS | FAIL | SKIP | 판정 | 증빙 |
|---|---|---:|---:|---:|---|---|
| Backend pytest | [명령/경로] | [-] | [-] | [-] | NOT_RUN | [URL/파일] |
| Frontend Vitest | [명령/경로] | [-] | [-] | [-] | NOT_RUN | [URL/파일] |
| Playwright E2E | [미설치 시 NOT_INSTALLED] | [-] | [-] | [-] | NOT_RUN | [URL/파일] |
| DB 격리 테스트 | [명령/경로] | [-] | [-] | [-] | NOT_RUN | [URL/파일] |
| 수동 Swagger/브라우저 | [경로/시나리오] | [-] | [-] | [-] | NOT_RUN | [URL/파일] |

- 종료 코드: [0/비0/미확인]
- CI Workflow/Run URL: [URL 또는 NOT_RUN]
- 실패 원인 및 재현 절차: [없으면 해당 없음]
- SKIP/HOLD 이유 및 담당자: [없으면 해당 없음]

## 3. 보안·변경 영향

- 비밀번호·토큰·실제 개인정보 첨부: NO / **검토 필요**
- Staging DB 변경: NO / YES(승인 링크 필요)
- Schema/Seed/Migration 변경: NO / YES(승인 링크 필요)
- 로컬 격리 데이터 사용 여부: YES / NO(사유)

## 4. 결론 및 인계

- 해당 범위 판정: PASS / FAIL / HOLD / NOT_RUN
- 미검증 범위와 후속 Issue: [...]
- PR 리뷰 요청일/승인자: [...]
- Merge SHA(병합 이후): [...]
- Redmine 완료 처리 근거: [...]
