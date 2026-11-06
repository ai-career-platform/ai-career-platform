# 시스템 아키텍처 및 API 계약 가이드

## 서비스 구상
- 사용자 화면 약 72개: 확정 UI별 요구사항 목록은 별도 설계 자료로 관리.
- Frontend → API Gateway/Nginx → FastAPI Backend → PostgreSQL.
- Backend 책임 계층: Router(API/HTTP) → Service(업무 규칙) → Repository(영속성) → DB.
- AI/ML 서비스는 업무 API와 분리 가능하도록 구성하고, 오류 시 비AI 주요 기능 유지.
- 개발자별 최소 1개 **DB → Repository → Service → Router → Frontend** Vertical Slice를 구현.

## 기본 계약
- API 경로, HTTP 메서드, Pydantic Request/Response DTO, 상태코드, 오류 포맷을 PR 전에 문서화.
- 예: 입력 오류 422, 미존재 404, 중복 409 등은 API별 계약에 맞춰 정의.
- 인증/인가(사용자 역할), 페이지네이션, 정렬, 필터, 입력 제한, 타임존/시간 포맷을 통일.
- 공개 API와 내부 관리 API 분리; 프런트엔드에서는 DB에 직접 접근하지 않음.
- CORS는 브라우저 Origin 접근 제어이며 인증/인가를 대체하지 않음.
- 사용자 정보, 모델 입력/출력 및 추천 근거는 필요한 최소 범위로 제한.

## DB 계약
- 핵심 ERD, PK/FK, UNIQUE, NULL/NOT NULL, Index·Migration 계획을 승인 후 적용.
- 공통 Seed와 각 Vertical Slice의 테스트 데이터 구분.
- 개발자 임의 Staging DDL/DML 금지. [DB 정책](DATABASE.md) 준수.

## 각 기능 PR 완료조건
1. 화면/API/DB 계약 일치.
2. 성공·실패·경계값 테스트.
3. 보안/인증/권한 테스트.
4. Swagger 또는 API 결과 및 UI Preview 증빙.
5. CI 통과 및 리뷰 후 Merge.
6. Staging 동작 확인 후 Redmine Closed.

## 미확정 사항
기능별 실제 엔드포인트, 화면 72개 목록, DB ERD, API 스키마와 서비스 분리는 후속 구현 PR에서 확정합니다. 본 문서는 구조 원칙이며 구현 완료 선언이 아닙니다.
