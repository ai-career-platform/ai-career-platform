# T151 STEP 05B — 최신 크롤러 DB 전체 백업·격리 복원 검증

> Feature #1578 · Task T151 · 기준 SHA `eef81573411ab4fb3fd5e8778fa66079de2aaf52`  
> **사용자 제공 로컬 Codex 검증 결과의 기록**이며 원본 백업 및 로컬 Evidence의 실제 바이트를 GitHub 코디네이터가 열람한 것은 아님.

## 판정: PASS (이번 백업·복원 범위)

| 항목 | 결과 |
|---|---|
| main / staging | `eef81573411ab4fb3fd5e8778fa66079de2aaf52` / 일치 |
| Fresh crawler full backup | PASS |
| SHA-256 | `a2840beae219caf4050e172f1de88aad5b9eee31872fd1f3862979dd5f1ce0c0` |
| 포함 범위 | DB 스키마·데이터·시퀀스·제약·권한 |
| 격리 PostgreSQL 실제 복원 | PASS |
| 복원 행 수 | `postings=7, schedules=1, runs=1, run_events=3` |
| 게시물 지문 | `e842f12aec1cde3804813074c64a5080` (원본과 일치) |
| 스키마 제약 검증 | PASS |
| Scheduler | `enabled=false, mode=fixture` |
| Timer | `DISABLED/INACTIVE` |
| 0003/0004 적용 | NO / NO |
| 원본 DB·서비스 변경 | NO |
| Live 수집 | HOLD |
| 테스트 데이터 폴더 정리 | 기존 `HOLD_POLICY_BLOCKED` 유지 |

Windows/Linux 정렬 차이는 개별 행 지문과 공통 `COLLATE C`로 대조. 격리 복원 중 소유자만 테스트 관리자에 매핑; 원본 DB 소유권·권한은 변경하지 않은 것으로 보고됨. 테스트 인스턴스 종료됨.

## 백업과 Evidence 위치 (민감 데이터: GitHub 업로드 금지)

- 원본 보관 위치: `/home/kant/ai-career-staging-poc/backups/t151-full-20261108T083828Z-85fe74f1/crawler-full.dump`
- 로컬 백업 복제본: `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05b-crawler-full-a2840beae219.dump`
- 복원 증빙: `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05b-restore-evidence.json`
- 백업 검증 로그: `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05b-backup.log`
- 원본 보존 검사: `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05b-source-final.log`

백업 파일은 DB 원본 데이터를 포함하므로 GitHub 저장소에 커밋하지 않는다. 백업·로그 경로는 사용자 제공값이며, 경로 유무나 해시를 여기에서 직접 재계산하지 않았다.

## 다음 단계

STEP05C의 사전 조건인 **최신 DB 백업과 격리 복원 시험 PASS**를 충족한 것으로 보고됨. 스테이징 수동 Migration은 STEP05C 별도 검증 단계이며, 적용 전 main/배포/DB의 상태와 백업 해시를 다시 확인한다. 변경 대상은 `0003`의 신규 3테이블 및 `0004`의 감사 1테이블뿐이다. 기존 앱 DB 51테이블 및 crawler 4테이블·7개 게시물·T64 이력·스케줄·Timer는 보존. Live HOLD.

```
FEATURE=1578
TASK=T151
STEP=05B
MAIN_SHA=eef81573411ab4fb3fd5e8778fa66079de2aaf52
FRESH_CRAWLER_BACKUP=PASS_USER_REPORTED
ISOLATED_RESTORE=PASS_USER_REPORTED
RESTORED_COUNTS=7/1/1/3
POSTINGS_FINGERPRINT=e842f12aec1cde3804813074c64a5080
STAGING_CHANGED=NO
LIVE_COLLECTION=HOLD
RESULT=PASS
NEXT=STEP05C_STAGING_MIGRATION_FIXTURE
```
