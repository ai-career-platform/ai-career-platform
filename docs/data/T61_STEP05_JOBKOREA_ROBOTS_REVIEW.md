# T61 STEP 05 — 잡코리아 공개 robots.txt 검토 기록 (승인 판정 아님)

> 확인일: 2026-11-07 · 기준 URL: https://www.jobkorea.co.kr/robots.txt  
> 문서 상태: **RESEARCH_ONLY / APPROVAL=HOLD / LIVE_FETCH=NOT_RUN**  
> 실제 공고 URL `https://www.jobkorea.co.kr/Recruit/GI_Read/50246410`에 대한 이 문서의 판단은 정적 robots 텍스트 패턴 확인일 뿐이다. 본 작업 중 해당 URL을 크롤러로 요청하지 않았다.

## 공개 robots 텍스트에서 확인한 사항

- 문서 상단에 `Version: 3.0 / Desktop`, `Last updated: 2026-08-21`로 표시됨.
- `User-agent: *` 일반 규칙에는 로그인, 개인계정, 기업 관리 화면, `/Recruit/JobList/SpaceClick` 등에 대한 `Disallow`가 있으나 **`/Recruit/GI_Read/` 직접 차단 항목은 확인되지 않음**.
- 반면 **AI Training Crawlers** 그룹(GPTBot 등)은 `Disallow: /`로 전체 차단됨.
- **Known Web Scrapers** 그룹에는 `Scrapy`, `CCBot`, `Diffbot` 등이 포함되고 `Disallow: /`로 전체 차단됨.
- 검색·인용용으로 구분된 일부 User-agent는 별도 허용/제한 규칙을 가짐. 이를 프로젝트 임의 User-agent의 허가 근거로 사용하지 않는다.
- 이 검토는 해당 파일을 열람한 시점의 공개 텍스트 해석이다. 특정 UA의 유효한 robots 룰은 해당 User-agent 그룹 매칭까지 별도로 확인해야 한다.

## 중요한 판단 경계

1. **일반 규칙에 `GI_Read`의 명시적 Disallow가 없다는 것과 무조건 수집 허용은 다르다.**
2. Scrapy 등 명시적으로 전체 차단된 User-agent를 다른 UA로 위장해 차단을 회피해서는 안 된다.
3. 자동 수집이 가능한지 판단하려면 *실제 사용할 User-agent*, 웹사이트 약관, 접근 제한, 데이터 저작권/저장·가공·재표시 조건, 개인정보 보호, 호출 주기를 함께 검토해야 한다.
4. 잡코리아 API 별도 약관을 일반 웹페이지 자동 접근에 그대로 적용할 수 있는지 단정하지 않는다. 웹페이지 이용 조건은 별도 검토가 필요하다.
5. `robots.txt` 자체는 접근 통제·계약상 허가·재배포 라이선스를 부여하는 문서가 아니다.
6. 현재 프로젝트의 T61 `candidate_jobkorea=HOLD`, `enabled=false` 상태를 **변경하지 않는다**. PM 승인, 활용 범위 확정, 관련 법률·약관 검토 전에 실제 웹 수집/HTML 저장/주기 수집을 실행하지 않는다.

## T62 STEP 09 정확도 검증과의 연결

- 공고 `50246410`의 실제 HTML·SHA-256·취득 시간·Golden Truth는 미확보 상태.
- T62 STEP 07 구조화 데이터 파서는 합성 JSON-LD 전용으로 실제 잡코리아 DOM/JSON-LD 호환성이 검증되지 않았다.
- T62 STEP 08의 225개 오프라인 테스트 통과를 실제 공고 정확도 성능으로 보고하면 안 된다.
- 접근·보존 승인과 시험 범위가 충족되면 허용된 **단일 HTML 샘플**로 파서와 Golden Truth를 비교한다. 허용 여부가 불명확한 경우 MOCK 테스트와 접근 방법 조사만 가능하다.

## 다음 승인 체크리스트

- [ ] 잡코리아 **웹사이트** 이용약관에서 자동 접근·콘텐츠 저장·가공·분석·서비스 표시 조건과 적용 범위를 검토·증빙
- [ ] 실제 사용할 User-agent 및 페이지 경로의 robots 규칙을 승인 당시 다시 확인
- [ ] 이용 목적(비상업적 내부 학습 vs 서비스 운영), 허용된 URL 패턴/필드/요청수/보존/폐기 기준 기록
- [ ] 필요한 계약·허가·사내법무 검토가 있다면 문서화
- [ ] PM이 지정 URL `50246410`에 대한 소량 접근·HTML 이용 여부를 근거와 함께 판정
- [ ] 모든 조건이 충족되기 전까지 `APPROVED` 전환·운영 스케줄러 시작 금지

## 출처

- 공개 robots: https://www.jobkorea.co.kr/robots.txt (확인일 2026-11-07; 현행 파일은 추후 변경될 수 있음)
- 레지스트리: [SOURCE_REGISTRY.md](SOURCE_REGISTRY.md)
- 권한/필드 계약: [JOBKOREA_FIELD_AND_RIGHTS_CONTRACT.md](JOBKOREA_FIELD_AND_RIGHTS_CONTRACT.md)
- 실제 정확도 검증 인수 기준: [T62_STEP09_LIVE_ACCURACY_READINESS.md](T62_STEP09_LIVE_ACCURACY_READINESS.md)

**최종 판정:** `T61_STEP05=RESEARCH_ONLY`; `LIVE_COLLECTION=HOLD`; `T62_REAL_ACCURACY=NOT_VERIFIED`.
