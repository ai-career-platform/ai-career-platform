# T144 검증 보고서 — 스토리지 문서 암호화·키 관리·접근 회귀

## 1. 작업 목적
문서 저장·전송 보안의 현재 상태를 사실대로 확인하고, 접근 제어 회귀 시험과 키 관리 계약(봉투 암호화·회전)을 코드와 시험으로 고정합니다.

## 2. 기존 구현·PR 재사용
- **T49(#159, 병합)**
  - 대상: `document_storage.py`, `documents.py`, `routers/documents.py`
  - 이 코드는 수정하지 않았고, 회귀 시험만 추가했습니다.
- **T111(병합)**: `env_contract.py`에서 `DOCUMENT_STORAGE_ROOT`가 비밀이 아님을 확인했습니다. 키 변수는 추가하지 않았습니다.
- **T15 인증**: 시험은 실제 `signup`/Bearer 흐름을 씁니다(`tests/conftest.py`).
- **T141**: 아직 PR 단계입니다. 개인정보 요청 정책과의 연결은 후속 작업입니다.

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록합니다(커밋 뒤 확정).

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `backend/app/services/document_keys.py` | 봉투 암호화 계약: KeyRing(active/decrypt_only/retired), `EncryptedDocumentStorage`, rewrap, 평문 이행. **미연결** |
| `backend/app/services/document_download_token.py` | 만료형 다운로드 토큰(HMAC, 최대 15분). **미연결** |
| `backend/tests/test_t144_document_storage_security.py` | 43건 |
| `docs/security/DOCUMENT_STORAGE_SECURITY_RUNBOOK.md` | 현재 상태표, 키 회전·긴급 절차, 결정 필요 |
| `docs/testing/T144_VALIDATION_REPORT.md` | 이 문서 |

`config.py`, `main.py`, `env_contract.py`, `.env.example`은 **변경하지 않았습니다**.

## 5. 선행조건
| 선행 | 상태 |
|---|---|
| T49 문서 API | MERGED |
| T53 RAG 색인·권한 동기화 | **NOT_STARTED**. 파생물(chunk·색인) 암호화·삭제 전파는 확인할 수 없습니다. `DocumentDerivativePurger` 계약만 있습니다. |
| T111 환경·Secret 계약 | MERGED |
| T141 개인정보 요청 정책 | 이번 묶음에서 별도 PR |

## 6. 실제 실행 명령
```bash
cd backend
PYTHONUTF8=1 python -m pytest -q tests/test_t144_document_storage_security.py
# 전체(일회용 PostgreSQL 18.6, 공유 잠금 아래)
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<admin>@127.0.0.1:55496/t16_profile_test \
  python -m pytest -q
```

## 7. 정상·오류·권한 검증
| 구분 | 시험 | 결과(로컬 Windows) |
|---|---|---|
| ACL | 다른 사용자: 조회·다운로드·삭제 404, 목록 비어 있음, 남의 삭제 시도 뒤에도 소유자 정상 | PASS |
| 인증 | 비로그인·잘못된 토큰: 다운로드·업로드 401 | PASS |
| 삭제 후 접근 | 삭제 요청 즉시 409(DOCUMENT_NOT_READY), purge 뒤 404이며 저장 객체 삭제 | PASS |
| 변조·바꿔치기 | 저장 객체 변조 503(내용 미노출), 암호화본끼리 바꿔치기도 DB SHA-256으로 503 | PASS |
| 공개 버킷·URL | 문서 경로 전부 401 선언, 응답 모델에 url·storage_key·checksum 없음 | PASS |
| 응답 헤더 | `private, no-store`, `nosniff`, `attachment` | PASS |
| 잘못된 저장 경로 | `../`, 절대경로, NUL, 대문자, 길이 위반 등 10종 거부 | PASS |
| 설정 누락 | 저장 경로 없음 → 503 fail-closed | PASS |
| 저장 시 암호화 | **현재 평문**(F-1) 사실 고정 | Windows SKIP(POSIX 전용) → **Linux CI에서 실행** |
| 키 회전 시뮬레이션 | 아래 항목 모두 확인 | PASS(합성 키) |
| 다운로드 토큰 | 만료(TOKEN_EXPIRED), 다른 소유자·문서·변조·다른 키·비정규 표기 → NOT_FOUND, TTL 범위, 키 분리 | PASS |

키 회전 시뮬레이션에서 확인한 항목:
- v1→v2 회전, 옛 객체 읽기
- 본문을 다시 암호화하지 않는 rewrap
- 참조가 남은 KEK·active KEK의 폐기 거부
- 폐기 뒤 복구 불가, id 재사용 거부
- 평문 이행

단위 결과: **42 passed, 1 skipped**(F-1, POSIX 전용).

전체 Backend(일회용 PG 포함): **1682 passed, 102 skipped, 1 failed, 31 errors**.
- 실패·오류 32건은 모두 `tests/test_documents.py`(20)와 `tests/security/test_security_upload.py`(12)입니다.
- Windows에 `os.O_DIRECTORY`가 없어 생기는 **사전 실패**입니다.
- 같은 명령을 main(`822fa16`)에서 돌려도 1 failed / 31 errors로 같았습니다. Linux CI 결과는 9절에 기록합니다.

## 8. PostgreSQL / Mock / 실제 API 구분
| 항목 | 값 |
|---|---|
| UNIT_TESTS | PASS (42, 1 SKIP) |
| POSTGRESQL_TESTS | 이번 변경은 PG를 쓰지 않습니다. 기존 PG 시험은 전체 실행에서 회귀 없음 |
| MOCK_VALIDATION | PASS: 메모리 저장소, 시험 전용 암호(SimulationCipher, 합성 키) |
| REAL_API_VALIDATION | PASS(범위 한정): 실제 FastAPI 라우터·T15 인증·SQLite 저장소. 실제 디스크 저장 경로는 Linux CI |
| STAGING_VALIDATION | NOT_RUN. Staging 저장소·볼륨 암호화는 확인하지 않았습니다(접근 없음). |
| 실제 키 | 생성·조회·교체 0건 |

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- **F-1(High)**: 문서가 평문으로 저장됩니다. 연결하려면 PM·보안 승인이 필요합니다.
  - `cryptography`(AES-256-GCM) 의존성: T118 공급망 게이트
  - KEK 보관 위치·환경변수 결정
  - 기존 평문 객체 이행 계획
- 호스트 볼륨 암호화, 전송 구간 TLS: NOT_VERIFIED(호스트 운영자 확인 필요)
- T53 미착수: 파생물(chunk·색인) 보안은 확인할 수 없습니다.

## 11. 후속 작업
1. 승인 뒤 `AesGcmCipher` 구현 → `get_document_storage`에 `EncryptedDocumentStorage` 연결(기능 플래그) → T111 계약에 키 변수 추가
2. 평문 → 암호화 이행 배치, 재감싸기 배치(T145 작업 계약 사용)
3. F-1 시험을 "암호문 저장" 시험으로 뒤집기
4. 서명 다운로드 링크 도입 여부 결정
