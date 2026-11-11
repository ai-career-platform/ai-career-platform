# 문서 스토리지 보안·키 관리 Runbook (T144)

> 상태: **PROPOSED**. 암호화 키 관리 계약과 시험만 있고, 운영 경로에는 연결하지 않았습니다.
> - 실제 키를 만들거나 바꾸지 않았습니다. 시험은 실행마다 새로 만드는 합성 키만 씁니다.
> - Staging·운영 저장소, Secret, Docker Compose는 변경하지 않았습니다.
> - 대상 코드: T49 `backend/app/services/document_storage.py`, `documents.py`, `routers/documents.py`

## 1. 현재 상태 (사실 확인)

| 항목 | 현재 | 판정 | 근거 |
|---|---|---|---|
| 저장 시 암호화 | **없음. 평문 파일**(`DirectoryDocumentStorage`) | **FINDING F-1 (High)** | `test_finding_f1_directory_storage_is_plaintext_at_rest`(Linux CI) |
| 디스크·볼륨 암호화 | 확인 안 함(호스트 접근 없음) | NOT_VERIFIED | — |
| 전송 구간 | Backend 응답 자체는 TLS 종단 뒤. Proxy TLS 설정은 T90·T112 범위 | NOT_VERIFIED | — |
| 저장 디렉터리 권한 | 디렉터리 0700, 파일 0600, 절대경로·symlink 거부 | PASS(Linux CI) | T49 시험, T144 경로 시험 |
| 객체 이름 | 무작위 64 hex. 업로드 파일명과 무관 | PASS | `_key` 정규식, 경로 조작 10종 거부 |
| 공개 버킷·공개 URL | **없음.** 문서 경로는 모두 인증 필요, 응답에 URL·저장 키 필드 없음 | PASS | `test_no_public_url_surface` |
| 다운로드 ACL | 다른 사용자는 조회·다운로드·삭제 모두 404, 목록에 안 보임 | PASS | `test_other_user_gets_404_on_every_document_route` |
| 삭제 후 접근 | 삭제 요청 즉시 다운로드 409, purge 뒤 404이며 객체가 삭제됨 | PASS | `test_deleted_document_cannot_be_downloaded_and_purge_removes_object` |
| 변조·바꿔치기 | DB의 크기·SHA-256과 다르면 503(내용 미노출) | PASS | 변조·바꿔치기 시험 |
| 서명(만료) URL | **기능 없음.** 계약 모듈만 추가(미연결) | PROPOSED | `document_download_token.py` |
| 저장소 설정 누락 | 503으로 fail-closed | PASS | `test_missing_storage_root_fails_closed` |

## 2. 키 관리 계약 (봉투 암호화)

모듈: `backend/app/services/document_keys.py` (라우터·설정 미연결)

```
저장 객체 = "AICPENC1" | header_len(2) | header JSON | 본문 암호문
header = { v, kek_id, object_id, alg, dek(KEK로 감싼 DEK) }
본문 AAD = object_id   ·   DEK AAD = kek_id + object_id
```

| 개념 | 규칙 |
|---|---|
| KEK | `kek_id`로 식별. 상태는 active → decrypt_only → retired. active는 하나뿐이고, id는 재사용하지 않습니다. 원본은 KMS·Secret 저장소에 두며 코드·Git·로그에 두지 않습니다. |
| DEK | 객체마다 새 32바이트. KEK로 감싸 객체 머리에 저장합니다. |
| 알고리즘 | 운영 승인 목록 `APPROVED_ALGORITHMS = {AES-256-GCM}`. 시험용 구현은 `allow_simulation=True`가 있어야만 받습니다. |
| 오류 | 키 없음·폐기·변조·알고리즘 불일치는 모두 503(DEPENDENCY_UNAVAILABLE). 키 id·저장 키·내용은 응답과 로그에 남기지 않습니다. |
| 기존 평문 객체 | 기본 거부. 이행 기간에만 `allow_legacy_plaintext=True`로 읽고, `migrate_plaintext`로 암호화본을 만듭니다. |

### 키 회전 절차 (시뮬레이션 PASS, 운영 미실행)
1. 새 KEK를 KMS에 만들고 `add_active("kek-YYYY-NN")`. 이전 KEK는 decrypt_only가 됩니다.
2. 새 업로드는 새 KEK로만 감싸집니다. 옛 객체는 계속 읽힙니다.
3. 재감싸기 배치(copy-on-rewrap): `rewrap_to(old_key, new_key)` → DB `storage_key` 교체 → 옛 객체 삭제.
   - 본문 암호문은 다시 암호화하지 않습니다(DEK만 다시 감쌈).
   - 저장소는 덮어쓰기를 허용하지 않으므로 새 키에 씁니다. 중간에 실패해도 옛 객체가 남아 있어 읽을 수 있습니다.
4. `kek_of`로 옛 KEK 참조 수를 집계합니다. 0일 때만 `retire`가 성공합니다. active KEK는 폐기할 수 없습니다.
5. 폐기 후 키 원본은 버립니다. 남아 있던 객체는 복구할 수 없습니다(crypto-shredding). 그래서 4단계 집계가 필수입니다.

### 긴급 절차 (KEK 유출 의심)
- 즉시 새 KEK로 회전하고 전량 재감싸기를 실행합니다. 유출 KEK는 참조 0 확인 뒤 폐기합니다.
- DEK가 함께 유출된 경우 재감싸기로는 부족합니다. 본문을 다시 암호화해야 하며, 이 절차는 미구현입니다.

## 3. 만료형 다운로드 토큰 계약

모듈: `backend/app/services/document_download_token.py` (라우터 미연결)

- HMAC-SHA256으로 (소유자, 문서, 만료, nonce)를 묶습니다.
  - 키는 `derive_key(JWT_SECRET, "t144-document-download-v1")`로 파생하므로 새 Secret이 필요 없고, JWT·cursor 키와 분리됩니다.
- 기본 5분, 최대 15분입니다.
- 실패 응답
  - 만료만 `TOKEN_EXPIRED`로 구분합니다.
  - 다른 소유자, 다른 문서, 변조, 다른 키, 비정규 표기는 모두 `NOT_FOUND`로 같게 응답합니다.
- **토큰은 권한이 아닙니다.**
  - 사용 시 DB에서 소유와 `ready` 상태를 다시 확인해야 합니다.
  - 그래서 삭제 요청 뒤 남은 토큰은 쓸 수 없습니다.
- 공개 버킷 사전서명 URL(S3 등)은 쓰지 않습니다. 쓰게 되면 별도 승인이 필요합니다.

## 4. 연결 전 결정 필요 (PM·보안)

1. **암호 라이브러리**: `cryptography`(AES-256-GCM)를 의존성으로 추가할지. T118 공급망 게이트·SBOM 반영 필요.
2. **KEK 보관 위치**: KMS, Vault 또는 Secret 파일 중 선택. 환경변수 이름(제안: `DOCUMENT_KEK_ID`, `DOCUMENT_KEK_SOURCE`)을 정한 뒤 T111 계약과 `.env.example`에 추가합니다(이번에는 추가하지 않음).
3. **기존 평문 객체 이행**: 대상 수와 기간, 이행 중 `allow_legacy_plaintext` 허용 기간을 정합니다.
4. **회전 주기**: 제안은 연 1회와 유출 의심 시입니다. 재감싸기 배치 실행 승인 주체도 정해야 합니다.
5. **서명 다운로드 링크** 도입 여부(현재 Bearer 다운로드로 충분하다면 도입하지 않음).
6. **호스트 볼륨 암호화** 확인: 호스트 운영자가 확인해야 합니다.

## 5. 재현

```bash
cd backend
python -m pytest -q tests/test_t144_document_storage_security.py
```

평문 저장 확인 시험(F-1)은 POSIX에서만 실행됩니다. Windows에서는 SKIP되고, Linux CI에서 실행됩니다.
