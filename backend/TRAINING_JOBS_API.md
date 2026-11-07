# 학습용 합성 채용공고 FastAPI 조회 (정식 서비스 API와 독립)

> **EDUCATION_ONLY / SYNTHETIC_ONLY / READ_ONLY**  
> 기존 정식 `backend/app/main.py`, `/api/v1`, `docs/API_CONTRACT.md` 수정 없음.

## 설계

- 파일: `backend/training_jobs_api.py` (독립 FastAPI 앱)
- 엔드포인트: `GET /jobs?limit=20` (1~100)
- DB: 기존 격리 `ai_career_crawler_training.crawler_training.postings`
- DB 검증: `crawler.storage.postgres.validate_local_dsn()` 재사용
- 접근: `SELECT`만 실행하며 `source_code='jobkorea'` 및 합성 ID `SYNTH-%`만 포함
- 노출: 공고 ID·제목·가상 회사·지역·고용형태만; 원문 URL/기타 payload/DB 비밀값 제외
- 실패: 자세한 연결 오류 대신 503 반환
- 변경하지 않음: 실제 잡코리아 접근, 기존 공고 데이터, 운영 DB, 정식 Backend 라우터

## Windows 11 (repository root에서)

의존 패키지: `fastapi==0.115.12`, `uvicorn==0.34.2`, `psycopg[binary]==3.3.4`.
테스트 클라이언트를 사용하는 단위 테스트는 `httpx==0.28.1`도 필요.

이미 PowerShell 세션에 `CRAWLER_LOCAL_DATABASE_URL`이 설정되어 있어야 하며, 계정은 `crawler_student` 같은 비관리자 전용 학습 계정이어야 한다. 비밀번호는 `PGPASSWORD` 등 비공개 방법으로 제공하며 채팅·GitHub·명령에 적지 않는다.

```powershell
py -3.12 -m unittest discover -s backend/training_tests -v
py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001
```

브라우저에서 http://127.0.0.1:8001/docs 를 열어 `GET /jobs` → Try it out → Execute.
기대값: `200`, `SYNTH-AX-001` 및 `SYNTH-AX-002` 합성 공고(기존 학습 DB 상태에 따라 다름).
`127.0.0.1`에만 바인딩하며 포트를 외부에 노출하지 않는다.

이 실습 앱은 인증/권한/운영 보안 기능을 갖춘 정식 서비스가 아니다. 로컬 학습 전용이며 본番 배포 금지.
