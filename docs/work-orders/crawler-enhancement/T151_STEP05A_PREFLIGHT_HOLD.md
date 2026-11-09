# T151 STEP 05A — 스테이징 사전점검 및 백업 복원 준비 HOLD

> Feature #1578 · Task T151 · 2026-11-08 · **로컬 Codex 결과를 사용자가 제공한 보고**, 실제 로컬 Evidence 로그 원문은 이 GitHub 작업에서 미열람.

## 최종 판정

`STEP05A=HOLD`: 기존 서비스·데이터 보존은 PASS이나, 기존 크롤러 백업에 현재 7개 postings 중 2개와 T64 실행 이력이 누락되어 **현재 상태로 복원할 수 없음**. 0003/0004 Migration 금지 상태를 유지한다.

## 점검 결과

| 검증 | 결과 |
|---|---|
| Main/스테이징 SHA | `505b0372275563d5363e4871c41a72e857814a55` / 일치 |
| 앱 DB | 51개 테이블 건수·해시 동일, PASS |
| 크롤러 DB | `postings(7), schedules(1), runs(1), run_events(3)` |
| postings 지문 | `e842f12aec1cde3804813074c64a5080` |
| Scheduler | `enabled=false`, `mode=fixture` |
| Timer | disabled/inactive |
| Migration `0003` / `0004` | 미적용 / 미적용 |
| 기존 백업 | 체크섬·아카이브 해독 PASS, 내용은 postings 5개로 **불완전** |
| 백업 복원 준비 | HOLD |
| 기존 Auto-CD | 사전점검 중 자동 완료, 최종 SHA 일치 및 서비스 healthy 보고 |
| 테스트 클러스터 데이터 정리 | 별도 HOLD_POLICY_BLOCKED (우회 금지) |
| 스테이징 변경 | NO |
| LIVE | HOLD |

원본 Evidence는 사용자 제공 경로 `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05a-evidence.log`에 존재한다고 보고되었으나 이 GitHub 기록은 파일 내용을 직접 검증하지 못했다.

## 다음 게이트: STEP05B 백업·격리 복원 검증

1. **현재 상태의 전용 크롤러 DB**에 대해 현재 시각이 기록된 **새 백업을 별도 고유 파일명으로 생성**. 기존 백업 덮어쓰기/삭제 금지.
2. 저장된 백업이 4개 기존 테이블 + 스키마/시퀀스/설정까지 포함하는지 확인. 민감정보/원본 데이터 로그 노출 금지.
3. 생성 백업의 무결성 해시·목록 검사 후 **별도 격리 복원 DB에서 실제 복원**하여 기존 테이블 건수(7/1/1/3), postings 지문 및 관련 이력/제약을 원본 스냅샷과 비교.
4. 복원 테스트는 원본 크롤러 DB와 기존 앱 DB 모두에 DDL/DML을 수행하지 않음. 복원 테스트가 실제 운영 서버에 영향을 주지 않는 별도 인스턴스인지 확인. 로컬에 기존 테스트 데이터 폴더가 남아 있으므로 새 클러스터 경로 충돌 방지.
5. 생성 백업과 결과 로그 안전 보관. 이전 cleanup 정책 차단은 별도 HOLD 유지.
6. 백업 생성/복원 PASS 확인 전에는 `0003` 및 `0004` Migration, Timer, Live 수집, 서비스 재시작/배포 금지.

## STEP05B 완료 판정

```
FRESH_CRAWLER_BACKUP=PASS
BACKUP_CHECKSUM=PASS
BACKUP_CONTENT=postings(7),schedules(1),runs(1),run_events(3)
ISOLATED_RESTORE=PASS
RESTORED_POSTINGS_FINGERPRINT=e842f12aec1cde3804813074c64a5080
STAGING_CHANGED=NO  # 원본 DB·서비스 설정·배포 변경 금지; 새 백업 파일만 생성
MIGRATION_0003_APPLIED=NO
MIGRATION_0004_APPLIED=NO
LIVE_COLLECTION=HOLD
```

**주의:** 생성된 백업 파일을 보관하면 파일 시스템에는 새 백업이 생긴다. 여기서 `STAGING_CHANGED=NO`는 기존 DB 데이터/서비스 설정/배포에 변경이 없다는 의미로 한정한다.
