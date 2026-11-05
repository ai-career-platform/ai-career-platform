# 개발자 온보딩

## 첫날 체크리스트
1. GitHub Organization `ai-career-platform` 및 Repository 접근 권한 확인.
2. Redmine 프로젝트 권한과 Slack 협업 채널 접근 확인.
3. 개인 브랜치 생성; 보호된 `main`에 직접 Push 금지.
4. 담당 기능에 대한 Redmine **상위 일감 및 세부일감** 생성/연결.
5. API 계약, 공통 DB/Seed, 화면 디자인, 테스트·보안 정책 확인.
6. 개발 시작 시 세부일감 상태 **In Progress / 10%**로 변경.

## 개발자의 기본 산출물
- 각자 2~3개 세부일감을 선택하되, 하나 이상은 **DB → Repository → Service → Router → Frontend**의 연결된 Vertical Slice 구현.
- Pull Request에 관련 Redmine 번호, 수정 범위, 실행 방법, 테스트 증빙, UI Preview(해당 시) 기재.
- DB 구조 변경이 필요하면 직접 Staging에 적용하지 말고 요청 Issue 작성.
- 개인 단위 로컬 실습과 공통 Staging 데이터는 구분.

## 권장 폴더·품질 기준
- Backend: API 스키마, Repository, Service, Router의 책임 분리.
- Frontend: 디자인 검토에 필요한 Preview 및 API 오류 처리.
- 자동화: 테스트 재실행 가능성, 로그/결과의 민감정보 배제.
- 프로젝트 디렉터리 구조는 실제 구현 PR에서 확정; 본 문서는 임의의 고정 구조를 강제하지 않음.

## 완료까지
작업 시작 10% → 자체 테스트 완료 후 PR/Slack Merge 요청 90% → PM/JM Merge 및 해당 Staging 검증 후 100% Closed. 리뷰 수정 요청·CI 실패·배포 실패 시 90% 유지.
