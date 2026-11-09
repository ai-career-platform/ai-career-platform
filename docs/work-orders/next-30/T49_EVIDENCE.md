# T49 검증 기록 — 2026-11-09

T49_STATUS=PARTIAL · BRANCH=task/t49-document-api

## 최종 범위

T04·T05는 사용자 확인에 따라 병합된 결과물을 사용합니다. 파일은 전용 디렉터리에 격리 보관하고
경로는 `DOCUMENT_STORAGE_ROOT` 환경변수로 지정합니다. 사용자 지시에 따라 **ClamAV 연동과 관련
실행 설정·CI 컨테이너를 제거**했습니다. 형식·크기·SHA-256 검증만 수행하며 바이러스 검사를 의미하지 않습니다.

기존 `career.user_documents`를 사용하며 DB Migration·공용 Staging·배포 설정을 변경하지 않았습니다.
실제 E2E는 Uvicorn HTTP 서버, PostgreSQL 18.1, 최소 CRUD 권한 계정, 임시 전용 디렉터리,
별도 프로세스의 실제 검증·삭제 워커를 사용합니다. 의존성 override나 DB·스토리지 mock을 쓰지 않습니다.

## 요청한 보안 항목

| 항목 | 구현 및 실제 확인 결과 |
|---|---|
| 파일 실행 권한 | 파일 모드 `0600`, `mode & 0111 == 0` 확인 |
| 디렉터리 권한 | `0700`; `0755`로 잘못 설정한 경우 업로드 503, 파일 생성 없음 |
| 경로 설정 | `DOCUMENT_STORAGE_ROOT`의 절대 경로 사용, 미설정은 파일 I/O 503 |
| 디렉터리 트레버셜 | POSIX `../`·Windows 역슬래시 파일명 422; 내부 저장 키는 32–64자리 소문자 16진수만 허용 |
| ZIP Slip | DOCX 엔트리의 상위 경로·절대 경로 거부; 압축을 파일 시스템에 풀지 않음 |
| 심볼릭 링크 | 디렉터리 fd와 O_NOFOLLOW 사용; 외부 파일 symlink 다운로드 503, 삭제도 외부 대상 보존 |
| 저장명 예측 방지 | `secrets.token_hex(32)`로 256비트 난수 사용. 원본 이름·내용 해시·문서 ID로 만들지 않음 |
| 저장명 충돌·덮어쓰기 | 같은 원본 이름·내용 12회 업로드에서 모두 다른 64자리 저장명; O_EXCL로 기존 파일 덮어쓰기 금지 |
| 저장명·경로 비노출 | 생성·목록·상태 응답과 헤더·다운로드 헤더에 저장명/경로 없음. 실제 저장명으로 직접 URL 접근 불가 |
| 권한 검사 | 타인 문서 조회·다운로드·삭제 404, 미인증 401; 소유자는 토큰으로만 결정 |
| 기본 입력·자원 제한 | 확장자/MIME/내용 위장 415, 빈 파일·NUL 이름·중복 파일 필드 422, 과대 파일·chunked 과대 본문 413 |
| DOCX | 손상 ZIP·매크로 바이너리·ZIP 폭탄·XML 외부 엔티티 415 |
| 다운로드 | ready만 첨부 파일, attachment·nosniff·private/no-store, 크기·SHA-256 재확인 |
| 삭제 | 다운로드 즉시 차단, 파일 삭제 및 PostgreSQL 분석/청크/인용 CASCADE 확인 |
| 검증·삭제 동시 요청 | 삭제 대기 또는 이미 삭제된 404로 끝나며 ready로 복구되지 않음 |

실행 권한은 파일 생성 시부터 적용합니다. 업로드한 파일을 실행하거나 셸 명령의 인자로 전달하는
코드가 없으며 저장 파일은 정적 웹 경로에 연결하지 않습니다.

## 쉘 실행 시도

격리된 로컬 대상에서 PHP 웹셸·셸 스크립트 업로드, PHP 위장 확장자, `$()`·세미콜론을 포함한
파일명 명령 삽입, PDF 안 PHP 문자열, `cmd` 쿼리 및 직접 파일 URL 접근을 시도했습니다.
원본 스크립트는 거부되며 허용된 PDF 바이트는 attachment로만 반환됩니다.
실행 여부는 격리된 표식 파일과 127.0.0.1 전용 콜백 listener로 확인했습니다.
**표식 생성과 콜백 접속 모두 없었습니다.** 실제 대화형 셸·외부 reverse shell은 열지 않았습니다.
이 결과는 시험한 경로의 실행 차단 증빙이며 모든 종류의 취약점 부재를 보증하지는 않습니다.

## 실행 결과

Python 3.14.4 로컬 실행:

```text
전체 Backend: 333 passed, 98 skipped, 0 failed (21.18초)
문서 기능 테스트: 20 PASS
실제 HTTP 파일 업로드 E2E: 24 PASS
최종 E2E 단독 재검증: 24 passed (8.61초)
```

생략 98건은 기존 다른 기능의 환경 의존 테스트입니다. 위 실행에서 T49 E2E는 생략하지 않았습니다.
Python 3.14 관련 기존 FastAPI/Starlette deprecated API 경고가 있으며 테스트 실패는 없습니다.

개별 검사 결과와 권한·저장명·실행 관측값은 [정리된 실행 결과](../../testing/T49_UPLOAD_E2E_20261109.json)에 보관합니다.
로컬 JUnit: `/tmp/t49-final-no-av.xml`, `/tmp/t49-upload-final.xml`.
CI는 `.github/workflows/t49-upload-e2e.yml`에서 Python 3.12·PostgreSQL 18.1로 동일한 24건을 실행하고
`t49-upload-e2e` JUnit artifact를 보관합니다. ClamAV 컨테이너나 바이너리를 실행하지 않습니다.

## 재현

```bash
python3 -m venv /tmp/t49-venv
/tmp/t49-venv/bin/pip install -r backend/requirements-dev.txt
# 먼저 로컬 일회성 PostgreSQL DB를 준비합니다.
export T49_E2E_DATABASE_URL=postgresql://t49_e2e:synthetic-local-only@127.0.0.1:55449/t49_e2e
export T49_E2E_ALLOW_RESET=YES
cd backend
/tmp/t49-venv/bin/python -m pytest -q tests/test_documents_e2e.py --junitxml=t49-upload-e2e.xml
/tmp/t49-venv/bin/python -m pytest -q
```

E2E는 지정한 일회성 로컬 DB의 career 스키마를 재생성합니다. localhost·DB명 `t49_e2e*`·명시적 동의를
모두 확인합니다. 기본 실행에서는 E2E 환경변수가 없으면 생략합니다. 실제 API는 127.0.0.1의 임시 포트로
띄우고 종료 시 중단합니다. 실제 사용자 개인정보·비밀정보는 fixture·증빙에 사용하지 않았습니다.

## 남은 작업

외부 색인(T53) 삭제 어댑터·보존기간 자동 삭제·강제 종료 시 고아 파일 정리는 후속 정책 및 구현 대상입니다.
외부 색인이 있으면 워커는 삭제 완료로 처리하지 않습니다. PR 리뷰 완료 전까지 T49_STATUS=PARTIAL입니다.
