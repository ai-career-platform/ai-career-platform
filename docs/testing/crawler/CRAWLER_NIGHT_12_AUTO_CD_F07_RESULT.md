# Auto-CD F-07 서버 반영 결과 (CRAWLER_NIGHT_12)

> 2026-11-12 22:53 KST · Staging 호스트 `automation/deploy.py` 를 main(#256) 판으로 교체했습니다.
> 서비스 재시작 0 건, Timer·Compose·config 변경 없음.

## 1. F-07 원인

- 두 PR 이 연달아 병합되면 오래된 커밋의 CI 가 나중에 끝날 수 있습니다.
- 그때 생긴 게시 run 은 workflow 의 `head_sha` 조건에 따라 **skipped** 됩니다. 이것은 정상입니다.
- 그런데 서버 배포기 `candidate()` 는 최신 run 1개(`per_page=1`)만 보았습니다. 그래서 다음 병합까지 매분 `HOLD: PUBLISH_NOT_SUCCESS` 로 멈췄습니다(2026-11-12 관찰).
- 수정(#256 `c0ad758`): `select_publish_run()` 이 최근 20개 중 **skipped run 만** 건너뜁니다. 더 새로운 failure·cancelled·진행 중 run 은 계속 배포를 막습니다.

## 2. 변경 전후

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| `automation/deploy.py` sha256 | `b1e7a56f8ed407ce…` (#3 원본, 2026-11-06) | `9edba1f84714c69a…` (main `e92b34d` 와 동일) |
| 권한 | 600 kant:kant | 600 kant:kant |
| 차이 | — | #256 diff 그대로(`select_publish_run` 추가, `per_page=20`) |

서버 사본은 #256 직전 판과 바이트 단위로 같았으므로, 다른 변경이 섞이지 않았습니다. 기대 해시가 다르면 중단하도록 해 두었습니다.

## 3. 적용 절차

1. 현재 해시가 #256 직전 판(`b1e7a56f…`)인지 확인했습니다. 다르면 중단합니다.
2. 백업: `cp -p deploy.py deploy.py.bak-f07-20261112135301`
3. main 판을 `.deploy.py.new` 로 올리고 sha256 이 `9edba1f8…` 인지 확인했습니다.
4. 서버 `/usr/bin/python3`(3.14.4) 로 문법을 검사했습니다(`ast.parse`, `__pycache__` 생성 없음).
5. 권한·소유자를 원본과 맞춘 뒤 원자적으로 교체했습니다(`mv -f`).
6. 교체한 파일로 순수 함수를 점검했습니다.
   - skipped 최신 run 은 그 아래 success run 으로 넘어갑니다.
   - 더 새로운 failure run 은 그대로 선택됩니다(배포 차단 유지).
   - skipped 만 있으면 `HOLD NO_PUBLISHED_RELEASE`.

**백업 경로:** `/home/kant/ai-career-staging-poc/automation/deploy.py.bak-f07-20261112135301`

**롤백:** `mv -f deploy.py.bak-f07-20261112135301 deploy.py`

## 4. Auto-CD 검증

| 항목 | 결과 |
|---|---|
| 교체 후 실제 systemd 실행 | 13:53:05Z, 13:54:05Z, 13:55Z: `decision: UNCHANGED` 3회, HOLD 0 |
| 서비스 결과 | `Result=success`, `ExecMainStatus=0` |
| Timer | `ai-career-staging-deploy.timer` enabled/active (변경 없음) |

드라이런 옵션이 없어서, 같은 SHA 에서 실제 Timer 실행이 `UNCHANGED` 로 끝나는지로 확인했습니다. skipped 게시 run 상황 자체는 서버에서 재현하지 않았습니다. 그 동작은 순수 함수 점검과 `poc/staging/automation/tests` 45/45 로 확인했습니다.

## 5. 기존 서비스 영향

| 항목 | 결과 |
|---|---|
| 컨테이너 시작 시각 (교체 전 = 후) | backend 13:36:19Z, frontend 13:36:50Z, db 2026-11-05: **재시작 없음** |
| 실행 이미지 | backend `sha256:77435f81…` 그대로 |
| Compose·`config.json`·overlay·`.env` | 변경 없음 |
| Dispatcher Timer·03:00 Fixture | 변경 없음 |
| Production | 해당 없음 |
