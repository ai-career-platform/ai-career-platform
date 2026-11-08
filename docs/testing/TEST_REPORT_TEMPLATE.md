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

## 5. main 병합 후 필수 Auto-CD 및 Staging QA

- `main` Squash Merge SHA: [40자리 SHA / NOT_MERGED]
- 실제 기능의 배포 이미지 포함: [YES / NO / N/A, 경로·근거]
- 자동 Publish Actions Run URL / 결과: [URL, SUCCESS/FAIL/HOLD]
- Ubuntu Pull/Compose 배포 실행 로그 / 시각: [증빙 위치, KST]
- Manifest source SHA / 이미지 Digest: [값/NOT_VERIFIED]
- Staging 실제 실행 SHA / Version: [값/NOT_VERIFIED]
- Staging 기능 URL 및 테스트 방법: [URL, 시나리오]
- Staging API/DB/Frontend 정상·오류: [영역별 PASS/FAIL/NOT_VERIFIED/N/A, 증빙 링크]
- 기존 서비스/DB 변경 영향: [없음/승인 근거/발견 문제]
- `DEPLOY`: [PASS/HOLD/N/A]
- `STAGING_QA`: [PASS/HOLD/N/A]
- PM/JM 검수자·일시 및 Redmine Evidence 댓글 URL: [값]
- `REDMINE`: [CLOSED / REVIEW / BLOCKED]

**`PR MERGED`와 `CI SUCCESS`만으로 Redmine CLOSED 금지.** 실행된 기능의 스테이징 검증이 완료되어야 합니다. 상세 기준: [공통 종료 게이트](../WORK_ITEM_CLOSURE_GATE.md). 배포 대상 없는 문서 전용 작업의 N/A는 PM/JM 승인 및 대체 검증이 필요합니다.
