# T49 개인 문서 업로드·보관

사용자 요청에 따라 업로드 파일은 객체 스토리지 대신 **전용 디렉터리**에 보관합니다.
T04·T05는 병합된 요구사항·스키마를 기준으로 사용합니다. `career.user_documents`는
기존 `database/migrations/0001_initial_schema.sql`에 있으며 이번 변경은 DDL을 추가하지 않습니다.

## 설정 및 실행

`DOCUMENT_STORAGE_ROOT`를 저장소·웹 루트 밖의 절대 경로로 설정하세요.
예: 로컬 테스트 `/tmp/ai-career-documents`, 서비스 환경 `/var/lib/ai-career/documents`.
API와 워커는 같은 디렉터리와 DB를 사용해야 합니다. 경로가 없으면 0700으로 생성하며,
기존 경로는 0700 권한이어야 합니다. 파일은 원래 이름과 무관한 256비트 무작위 이름·0600으로 생성합니다.
설정하지 않으면 파일 읽기·쓰기는 503입니다. `.env`는 자동으로 읽지 않습니다.

배포 시 디렉터리를 전용 볼륨으로 마운트하고 `noexec,nodev,nosuid`를 적용하세요.
애플리케이션은 파일을 실행하지 않으며 저장 디렉터리를 정적 웹 경로로 제공하지 않습니다.
파일명·내용·저장 키는 로그에 기록하지 않습니다.

```bash
export DOCUMENT_STORAGE_ROOT=/tmp/ai-career-documents
# DATABASE_URL, JWT_SECRET 등 기존 Backend 설정도 필요
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## API

| 메서드 | 경로 | 결과 |
|---|---|---|
| POST | `/api/v1/documents` | multipart `file`, `kind=resume/portfolio` → 202 scanning |
| GET | `/api/v1/documents` | 소유 문서만, limit 1–100, 서명된 사용자별 cursor |
| GET | `/api/v1/documents/{id}` | 상태·표시 메타데이터 |
| GET | `/api/v1/documents/{id}/file` | ready만 attachment, nosniff, no-store |
| DELETE | `/api/v1/documents/{id}` | 202 deleting, 반복 요청 허용, 완료 후 404 |

업로드·삭제는 Location/Retry-After를 반환합니다. 소유자는 인증 토큰으로만 결정합니다.
다른 사람 문서·존재하지 않는 문서는 모두 404입니다. 응답에는 저장 키·체크섬·소유자 ID가 없습니다.
PDF/DOCX만 허용하고 MIME·확장자·내용을 함께 검증합니다. 파일은 최대 10MiB이며,
전체 multipart 요청은 여기에 64KiB를 더한 크기로 제한합니다. 인증 후 제한된 메모리 안에서
파싱하므로 업로드 파서가 임시 파일을 별도 위치에 쓰지 않습니다.
DOCX의 경로 이동·중복 엔트리·암호화·매크로 바이너리·과도한 압축 해제를 거부합니다.
구조 검증은 악성 검사를 대체하지 않습니다.

## 형식·무결성 검증 및 삭제 워커

사용자 지정에 따라 ClamAV 및 외부 악성 검사기는 연동하지 않습니다.
기존 상태 이름 `scanning`은 형식·무결성 검증 대기를 뜻하며, 악성 코드 검사 완료를 의미하지 않습니다.
다음 단발성 워커는 저장 파일의 형식·크기·SHA-256을 다시 확인하고 ready/rejected로 전환합니다.

```bash
python -m app.document_worker
```

워커는 최대 100건의 scanning/deleting 행을 처리합니다. 주기 실행은 외부 스케줄러에서 구성하며,
API 시작 시 자동 실행하지 않습니다. 파일을 셸·인터프리터·외부 검사 프로세스로 실행하지 않습니다.
저장소 장애는 scanning을 유지하고 재시도합니다. 다운로드 때도 크기·SHA-256을 재확인합니다.

삭제는 즉시 다운로드를 차단하고, 파생 데이터 정리 → 파일 제거 → DB 메타데이터 제거 순으로 수행합니다.
DB의 기존 CASCADE가 분석·청크·인용을 제거합니다. 외부 색인(`index_ref`)이 있으면 삭제 완료로
처리하지 않고 T53의 실제 색인 삭제 어댑터 연결까지 deleting으로 둡니다.
개별 문서를 행 잠금으로 보호하여 검사 완료가 삭제 요청을 되돌리지 않습니다.
오류 시 DB 상태를 롤백하며 파일 삭제·파생 데이터 정리는 재시도 가능합니다.

## 검증·한계

```bash
python -m pytest -q tests/test_documents.py
python -m pytest -q
```

기본 테스트는 실제 인증 의존성, SQLAlchemy repository(격리 SQLite), 임시 전용 디렉터리를 사용합니다.
추가 E2E는 실제 HTTP 서버·PostgreSQL 18.1·전용 디렉터리를 사용하며 의존성을 대체하지 않습니다.
파일 업로드 공격·웹셸·명령 삽입 및 실행 표식/로컬 콜백 검증은
[실제 E2E 테스트](tests/test_documents_e2e.py)와 [증빙](../docs/work-orders/next-30/T49_EVIDENCE.md)을 참고하세요.
`.github/workflows/t49-upload-e2e.yml`에서 동일한 검증을 실행하고 JUnit 결과를 보관합니다.
외부 색인 연동·보존기간 정책 및 PR 리뷰가 남아 있어 상태는 PARTIAL입니다.
Staging DB·배포 설정은 변경하지 않았습니다.

자동 보존기간 삭제는 적용하지 않습니다. 업로드 파일 생성과 DB 커밋 사이의 프로세스 강제 종료로
고아 파일이 생길 수 있으므로, 실제 운영 전 보존기간·DB 대조 정리·백업 삭제 정책을 확정해야 합니다.
이번 디렉터리 방식은 사용자 지정 단기 구현이며 별도 저장 서비스로의 전환은 저장 어댑터로 수행합니다.
