# 학습용 Frontend — 합성 채용공고 카드 목록

> EDUCATION_ONLY / SYNTHETIC_ONLY / READ_ONLY / LOCALHOST_ONLY

## 구성

- `backend/training_frontend/index.html`: HTML·CSS·JavaScript 단일 파일
- `backend/training_jobs_api.py`의 `GET /training`: 로컬 학습 페이지 제공
- 기존 `GET /jobs?limit=20` 호출: 기존 PostgreSQL `crawler_training.postings`의 합성 데이터만 조회
- 화면: 공고 제목, 기업명, 지역, 고용형태, 공고 ID를 반응형 카드로 표시, 다시 조회 버튼
- 안전: 사용자/DB 입력의 HTML 삽입 대신 `textContent` 사용, SQL 쓰기·외부 요청 없음
- 같은 Origin에서 HTML과 API 제공 → CORS 설정 불필요

## 실행 순서 (Windows PowerShell, repository root)

1. GitHub 브랜치 fetch/switch 후 `py -3.12 -m unittest discover -s backend/training_tests -v` (기존 6 + 신규 4 = 총 10)
2. 환경변수 `CRAWLER_LOCAL_DATABASE_URL`과 로컬 인증 비밀 `PGPASSWORD`가 **동일 PowerShell 세션**에 설정되어 있는지 확인. 비밀번호 값은 출력하지 않음.
3. 이미 실행 중인 학습용 Uvicorn을 `Ctrl+C`로 종료하고, 아래 명령으로 **재시작** (코드 수정 후에는 재시작해야 함):

```powershell
py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001
```

4. 브라우저에서 http://127.0.0.1:8001/training 열기.
5. 합성 공고 2건이 카드 형태로 보이고 `다시 조회` 시 목록이 유지되는지 확인.
6. 데이터 조회가 실패하면 화면에 일반 메시지만 표시. 민감한 SQL·DB 오류값을 프런트에 표시하지 않음.

운영 `backend/app/main.py`, 정식 `frontend/` 앱, `/api/v1`, API 계약, 운영 DB, 잡코리아 실제 HTML 등 변경 없음. 본 UI는 인증·권한 관리가 없는 **로컬 학습 전용**임.
