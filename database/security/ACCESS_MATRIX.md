# T07 DB 계정·권한·접근 제한

Redmine #1567 · 검토용 설계 · 대상 스키마 `career`

| 역할 | 허용 | 제한 |
| --- | --- | --- |
| `career_reader` | 스키마 USAGE, 테이블 SELECT | 테이블 INSERT·UPDATE·DELETE 및 스키마 내 CREATE 차단 |
| `career_app` | 스키마 USAGE, 테이블 SELECT·INSERT·UPDATE·DELETE | 스키마 내 CREATE, 테이블 ALTER 등 소유자 DDL 차단 |
| `career_migrator` | 스키마 USAGE·CREATE, 자신이 만든 객체의 소유권 및 DDL | 배포 작업에서만 사용. 런타임 앱 계정과 분리 |
| `career_admin` | `career` 스키마 소유 및 스키마 권한 관리 | 클러스터 SUPERUSER 및 로그인 권한 없음. 개별 테이블 소유권은 Migrator에 있음 |

네 역할은 초안 SQL에서 모두 NOLOGIN·NOSUPERUSER입니다. 실제 로그인 계정과 역할 매핑은 별도 검토 대상입니다. 스키마의 PUBLIC 권한을 회수하고, `career_migrator`가 이후 생성하는 테이블에 Reader와 App 권한을 기본 부여합니다. 기존 테이블 및 다른 스키마 권한은 별도로 점검해야 합니다.

## Staging 읽기 전용 점검

기존 앱의 `ai_career_poc` SUPERUSER 사용은 위험으로 기록합니다. 앱용 비관리자 로그인으로 전환하려면 별도 승인과 연결 영향 검토가 필요합니다. 기존 Staging의 동명 `career_reader` 로그인과 초안의 NOLOGIN 역할은 각각 검증합니다.

1. [DB 개발환경 가이드](../../docs/development/DB_DEVELOPMENT_SETUP.md)의 DBeaver 연결 절차로 `career_reader` 인증을 확인합니다. 승인된 조회 대상에서 SELECT를 실행하고, 계정의 실제 권한은 `has_table_privilege`, `has_schema_privilege`로 점검합니다. 공유 DB에서 DML·DDL을 실행하지 않습니다.
2. 허용된 내부망에서 DB TCP 포트 도달 여부를 확인합니다. 허용 대역·차단 범위는 관리자 방화벽/ACL 설정과 대조합니다. 단일 TCP 연결 성공은 접근 제한이나 인증의 증빙이 아닙니다.
3. 결과에는 PASS/HOLD와 검증 범위만 기록하고 비밀번호나 접속 문자열은 첨부하지 않습니다.

## 격리 PostgreSQL 검증

저장소 루트에서 실행합니다.

```bash
D1_TEST_ONLY=YES bash database/tests/test_role_permissions.sh
```

일회용 PostgreSQL 18.1에서 역할 초안과 초기 스키마를 적용합니다. Reader SELECT 성공 및 INSERT·UPDATE·DELETE·CREATE의 SQLSTATE `42501`, App CRUD 성공 및 CREATE·ALTER 차단, Migrator CREATE·ALTER 성공, 역할 초기화 재실행을 확인합니다.

### 로컬 실행 결과 (2026-11-06)

기준 `main` SHA `704f413`의 역할 및 스키마 초안을 루프백 전용 일회용 PostgreSQL 18.4에 적용했습니다. Docker 엔진을 사용할 수 없어 위 스크립트와 같은 SQL을 Windows `psql`로 실행했습니다.

| 검증 | 결과 |
| --- | --- |
| 네 역할 NOLOGIN·NOSUPERUSER, 초기화 재실행 | PASS |
| Reader SELECT | PASS |
| Reader INSERT·UPDATE·DELETE·CREATE | 모두 `42501`로 차단 |
| App SELECT·INSERT·UPDATE·DELETE | PASS, 트랜잭션 롤백 |
| App CREATE·ALTER | 모두 `42501`로 차단 |
| Migrator CREATE·ALTER | PASS, 트랜잭션 롤백 |

Docker 기동 후 PostgreSQL 18.1에서도 동일 스크립트를 실행해 `D2_ROLE_TEST=PASS`를 확인했습니다. Windows Git Bash에서는 Docker 컨테이너 경로가 변환되지 않도록 `MSYS2_ARG_CONV_EXCL='*'`를 함께 지정했습니다.

현재 PC에서 가이드에 명시된 Staging DB 포트로 TCP 연결에 성공했습니다. DBeaver 인증·실제 조회 권한·TCP 허용 대역 및 App/Migrator 역할 경계 승인은 HOLD입니다.
