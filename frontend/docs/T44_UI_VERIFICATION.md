# T44 결과 UI 검증

## 제출 코드 범위

사용자 요청에 따라 미리보기 상태 선택 메뉴, 가상 데이터 안내, 별도 미리보기
페이지·HTML·진입점·CSS를 제거했다. 합성 데이터는 테스트 파일에만 있다.

SkillGapPage는 기존 Button/DataTable/StatePanel을 재사용하는 결과 화면이다.
SkillGapResultPage는 `useApi().skillGaps`(로그인 토큰·401 처리는 AuthProvider 클라이언트)와 `useQuery`로 실제 API를 호출하는 컨테이너다.
공통 라우터 파일은 수정하지 않았다. 기존 AuthProvider 내부에 등록해야 하며,
선택한 jobRoleId 또는 assessmentId를 props로 전달할 수 있다.
ID가 없으면 본인 최신 이력을 조회하고, 이력이 없으면 목표 직무 선택을 안내한다.

## 자동 상태 전환

| 상황 | 화면 |
|---|---|
| 세션 확인·조회 요청 진행 | 로딩 |
| 비로그인 또는 401 | 인증 필요, 이전 결과 숨김 |
| 이력 items=[] | 분석 결과 없음, 선택 직무가 있으면 분석 가능 |
| 목록·상세 조회 실패 또는 지정 결과 404 | 조회 실패 및 재시도 |
| 상세 응답 성공 | 실제 결과 표·직무·분석 시각·모델 버전 |
| is_stale=true | 재분석 필요 안내 |
| 첫 분석·재분석 요청 중 | 버튼 disabled 및 진행 안내 |
| 분석 POST 성공 | 반환한 새 결과로 갱신 |
| 재분석 실패 | 이전 결과 유지 및 실패 안내 |

직무/계정 전환 및 unmount 후 늦게 도착한 이전 응답은 폐기한다.
화면이 사용자 입력을 변경하거나 자동으로 분석 POST를 보내지 않는다.
표는 부족 수준 내림차순이며 동점은 동일 우선순위로 안내한다.
0 숙련도는 미등록/미평가를 구분할 수 없으므로 단정하지 않는다.

사용자의 기존 UI 유지 요청에 따라 T44에서 별도 덧씌운 색상·카드·버튼·포커스
스타일과 장식 문구를 제거했다. 화면 폭·간격·반응형 배치만 T44에 두고,
시각 스타일은 기존 공통 컴포넌트에서 받는다. 지정된 training 화면 자체는 변경하지 않았다.
공통 UI 파일·인증·라우터·설정 및 배포 서버는 변경하지 않았다.

## 검증 명령

```powershell
cd C:\dev\ai-career-platform\frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

API 경계·상태 전환은 mock request로 검증하며 실제 T43 운영 통합 증빙은 아니다.
최신 결과: T44 화면15 + API계약7 + 요청상태10 = **32 PASS**.
전체 **73 PASS / 10 SKIP**, Typecheck·기존 앱 Build PASS.
10 skip은 실제 서버 환경을 설정하지 않은 기존 integration 테스트다.
lint는 기존 Windows Application Control의 oxlint native binding 차단으로 미완료.
브라우저 모바일·키보드·스크린리더 수동 검수, 공통 라우터 등록(사용자 확인 필요),
T34/T36 연결·T43 provider와 실제 통합, CI·리뷰·완료 승인이 남았다.

T44_STATUS=PARTIAL. 커밋·푸시·PR 생성 없음.
