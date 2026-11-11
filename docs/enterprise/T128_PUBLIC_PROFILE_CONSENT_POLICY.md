# 후보자 공개 프로필·동의 범위 정책 (T128)

> 상태: **PROPOSED**(PM·법무 승인 전)이며, 구현과 DB 변경은 없습니다.
> - 원본: [`t128_public_profile_fields.json`](t128_public_profile_fields.json)
> - 시험: `backend/tests/test_t128_public_profile_policy.py`. 필드 원천이 실제 스키마 열과 맞는지 확인합니다.
> - 선행: T31(동의·탈퇴)·T37(경력·프로젝트)은 main에 있고, T121은 #210(미병합)입니다. 이 PR은 T121 위에 쌓여 있습니다.

## 1. 원칙

1. **비공개가 기본**입니다. 모든 항목은 사용자가 고르기 전에는 공개되지 않습니다. 새로 추가한 경력·프로젝트도 비공개로 시작합니다.
2. **선택 동의**입니다. `public_profile`(선택 동의 코드, 신규 제안)을 동의해야 공개할 수 있습니다. 동의하지 않아도 서비스 이용에는 영향이 없습니다.
3. **링크로만 공유**합니다. 다음은 하지 않습니다(T121 INV-4).
   - 검색엔진 색인(`noindex, nofollow, noarchive`)
   - 기업 인재 검색
   - 공개 목록·디렉터리
4. **철회는 즉시**입니다. 동의를 철회하면 모든 링크가 바로 404가 되고, 선택은 초기화(비공개)됩니다.
5. **삭제가 전파**됩니다.
   - 공개 화면은 저장된 사본이 아니라 **현재 데이터를 그립니다**. 그래서 항목을 지우면 즉시 사라집니다.
   - 계정을 삭제하면 선택과 링크도 함께 삭제됩니다(CASCADE).

## 2. 항목별 공개 범위

| 항목 | 원천 | 선택 단위 | 공개 가능 | 위험 | 비고 |
|---|---|---|---|---|---|
| `display_name` | `users.display_name` | 필드 | 가능(기본 비공개) | medium | 실명일 수 있음 — 공개 시 별칭 입력 선택 제공(제안) |
| `headline` | `user_profiles.headline` | 필드 | 가능(기본 비공개) | low | 한 줄 소개 |
| `bio` | `user_profiles.bio` | 필드 | 가능(기본 비공개) | medium | 자유 문장 — 연락처·민감정보 입력 경고 |
| `location_text` | `user_profiles.location_text` | 필드 | 가능(기본 비공개) | medium | 시·군·구 수준 권장, 상세 주소 입력 경고 |
| `experience.organization` | `user_experiences.organization` | 항목별 | 가능(기본 비공개) | medium | 항목별 선택, 새 항목은 비공개 |
| `experience.title` | `user_experiences.title` | 항목별 | 가능(기본 비공개) | low |  |
| `experience.period` | `user_experiences.start_date,end_date` | 항목별 | 가능(기본 비공개) | low | 연·월 단위로만 표시 |
| `experience.description` | `user_experiences.description` | 항목별 | 가능(기본 비공개) | medium | 자유 문장 |
| `project.title` | `user_projects.title` | 항목별 | 가능(기본 비공개) | low | 항목별 선택 |
| `project.summary` | `user_projects.summary` | 항목별 | 가능(기본 비공개) | medium |  |
| `project.period` | `user_projects.start_date,end_date` | 항목별 | 가능(기본 비공개) | low |  |
| `skills` | `user_skills.skill_id,proficiency` | 필드 | 가능(기본 비공개) | low | 기술 이름과 숙련도 |
| `target_roles` | `user_target_roles.job_role_id` | 필드 | 가능(기본 비공개) | low | 희망 직무 |
| `email` | `users.email` | 필드 | **불가** | high | 연락은 플랫폼 밖 — 공개 프로필에 이메일·전화 없음 |
| `documents` | `user_documents.*` | 필드 | **불가** | high | 이력서 등 원본 파일 — 1차 공개 대상 아님(개인정보 다수) |
| `analysis_results` | `document_analyses.*, skill gap, matches, recommendation_runs` | 필드 | **불가** | high | AI 분석·적합도 점수 — 오해·차별 위험, 공개 안 함 |
| `job_applications` | `job_applications.* (T101)` | 필드 | **불가** | high | 개인 지원 기록 — 공개 안 함 |
| `behavior_events` | `behavior_events.*` | 필드 | **불가** | high | 행동 데이터 — 공개 안 함 |
| `consents_and_account` | `user_consents.*, auth_*` | 필드 | **불가** | high | 계정·동의 정보 — 공개 안 함 |

- 경력·프로젝트는 **항목별로** 고릅니다. 예를 들어 "A사 경력은 공개, B사 경력은 비공개"가 가능합니다.
- 기간은 연·월 단위로만 표시합니다.
- 자유 문장(소개, 경력 설명 등)에는 입력 화면에서 경고합니다. "주민등록번호·연락처·건강 정보 같은 민감한 내용은 적지 마세요"(T103과 같은 문구).

## 3. 공유 링크 (T129 구현 기준)

| 항목 | 규칙 |
|---|---|
| 토큰 | 128비트 이상 임의값(추측 불가). 서버는 해시만 저장 |
| 기간 | 기본 30일, 최대 90일 |
| 개수 | 동시에 유효한 링크 최대 3개. 링크별 회수 가능 |
| 응답 | 만료·회수·없는 링크를 모두 같은 404로 응답 |
| 캐시 | `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow, noarchive` |
| 열람 기록 | 링크별 열람 횟수만 셉니다. 열람자 신원·IP는 공개 프로필 기능에서 저장하지 않습니다(제안) |

## 4. URL 공유 위험과 대응

| 위험 | 설명 | 대응 | 남는 위험 |
|---|---|---|---|
| 재배포 | 링크를 받은 사람이 다른 사람에게 전달 | 기간 제한, 링크별 회수, 화면에 "공유 시점·만료일" 표시 | 기간 안에는 누구나 볼 수 있음. 미리보기 화면에서 경고 |
| 캡처·복사 | 화면을 저장 | 막을 수 없음 | **철회해도 이미 복사된 내용은 회수할 수 없다**고 공개 전에 확인받음 |
| 추측·열거 | 토큰을 대입해 찾기 | 128비트 토큰, 같은 404, 요청 한도 | — |
| 검색 노출 | 검색엔진이 색인 | noindex 헤더·메타, 목록 없음 | 링크를 공개 게시판에 올리면 크롤러가 방문할 수 있음(색인은 거부) |
| 캐시 재사용 | 프록시·브라우저가 철회 후에도 보여 줌 | `no-store`, CDN 미사용 | 이미 열어 둔 탭 |
| Referer 유출 | 공개 페이지에서 외부 링크를 누를 때 토큰이 Referer로 나감 | `no-referrer` | — |
| 접근 로그 | 토큰이 경로에 있어 접근 로그에 남음 | T112 `safe_path`가 40자 이상 토큰 구간을 `:token`으로 가림. Nginx 제안 설정 | Nginx 기본 로그(제안 미적용) |

## 5. 동의 기록

- 공개 범위를 바꿀 때마다 **미리보기로 확인**한 뒤 `user_consents`에 새 기록(`public_profile`, 버전, granted)을 남깁니다(PP-INV-7).
- 선택 항목 목록은 별도 표(T129 제안)에 저장하고, 동의 기록과 시각으로 연결합니다.
- 철회도 `granted=false` 기록으로 남깁니다. 이력은 기존 동의 이력 보존 정책을 따릅니다.

## 6. 불변 조건 (시험으로 고정)

| ID | 조건 |
|---|---|
| PP-INV-1 | 모든 항목의 기본값은 비공개다 |
| PP-INV-2 | 연락처·문서·AI 분석·지원 기록·행동 데이터·계정 정보는 공개할 수 없다(1차) |
| PP-INV-3 | 공개에는 `public_profile` 선택 동의가 필요하고, 동의 철회는 모든 링크를 즉시 무효로 한다 |
| PP-INV-4 | 검색엔진 색인·기업 검색·목록 노출은 없다. 접근은 공유 링크로만 한다 |
| PP-INV-5 | 만료·철회·없는 링크는 같은 404로 응답한다 |
| PP-INV-6 | 공개 화면은 현재 데이터를 그린다(삭제 즉시 반영). 새 항목은 비공개다 |
| PP-INV-7 | 공개 범위를 바꾸면 미리보기 확인 후 새 동의 기록을 남긴다 |

## 7. 결정 필요 (PM·법무)

| ID | 항목 | 제안 |
|---|---|---|
| D-1 | 동의 코드·문구 | `public_profile`(선택). **문구 법무 검토** |
| D-2 | 표시 이름 | 실명 대신 별칭 입력 선택 제공 |
| D-3 | 링크 기간·개수 | 30일 기본, 90일 최대, 3개 |
| D-4 | 열람 기록 | 횟수만(신원 미저장) |
| D-5 | 미성년자 | 생년월일을 수집하지 않으므로 확인 수단이 없음. 약관으로 처리할지 법무 결정 |
| D-6 | 문서(이력서) 공개 | 1차 제외. 필요하면 별도 일감 |
