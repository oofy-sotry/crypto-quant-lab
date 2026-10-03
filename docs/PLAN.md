# crypto-quant-lab 프로젝트 계획

솔루션퀀트 지원용 미니 프로젝트. Claude Code와 페어 프로그래밍(바이브 코딩)으로 **7일** 안에 완성한다.

## 1. 목표

공고 스택(Python, DRF, MySQL, Redis, Celery, pandas)과 업무(금융 데이터 수집·무결성, 백테스팅, REST API, 대시보드)를 한 레포에서 보여준다.

```
업비트 공개 API → 일봉 수집 → 무결성 검증 → pandas 백테스트 → DRF API → Next.js 대시보드
```

- 코인은 우대사항(가상화폐 도메인)과 연결된다.
- 24시간 거래라 "모든 날짜가 있어야 한다"는 무결성 규칙이 명확하다.

## 2. 기간을 7일로 잡은 이유

Claude Code로 코드를 작성하면 구현 자체는 며칠이면 끝난다. 그래서 기간은 AI로 줄어들지 않는 아래 병목을 기준으로 잡았고, 이를 감안하면 7일이 적당하다.

| 병목 | 대응 |
|---|---|
| 외부 계정 가입·설정(Vercel, Aiven, Upstash, Sentry) | D1에 한꺼번에 처리 |
| 배포 환경 디버깅(번들 크기, SSL, 환경변수) | D1에 빈 API + pandas로 먼저 배포 |
| 백필 실행 시간, Cron 검증(다음 날 실행돼야 확인 가능) | Cron은 D4에 걸어 두고 D5 아침에 확인 |
| **모든 코드를 직접 설명할 수 있어야 함** | 매일 마지막 1시간을 "이해 시간"으로 고정 |
| 최소 단위 커밋 | 기능 하나 끝날 때마다 바로 커밋(몰아서 하지 않음) |

## 3. 작업 방식 (Claude Code 협업 규칙)

1. Claude가 최소 단위(함수 하나·기능 하나) 변경을 제안하고 작성한다.
2. 사용자가 diff를 읽고 이해가 안 되는 부분은 바로 질문한다.
3. 테스트·lint 통과를 확인하고 커밋한다. 형식: `타입(스코프): 대상 — 변경 내용`
4. 개발과 동시에 개인 설계 노트(`docs/private/`, 커밋 제외)에 설계 이유·트러블슈팅·면접 예상 질문을 갱신한다.

## 4. 우선순위 (밀리면 아래부터 자른다)

| 등급 | 항목 |
|---|---|
| Must | 수집·백필, upsert, 무결성 검사, 백테스트(MA 교차 + Buy&Hold), DRF API, Redis 캐시, Vercel 배포 + Cron, README |
| Should | Next.js 대시보드(홈·차트·백테스트·데이터 품질·운영 상태 화면, 6.7절), Sentry, CI의 MySQL + pytest, Swagger |
| Could | Celery 그리드 탐색 + 히트맵, 다음날 시가 체결 옵션, 데모 GIF |

## 5. 아키텍처

| 구분 | 로컬 (docker compose) | 배포 |
|---|---|---|
| 백엔드 | Django + DRF | Vercel 프로젝트 ① (Root: `backend`) |
| 프론트 | Next.js | Vercel 프로젝트 ② (Root: `frontend`) |
| DB | MySQL 컨테이너 | Aiven MySQL (싱가포르, 무료 플랜, SSL) |
| 캐시 | Redis 컨테이너 | Upstash Redis (싱가포르 primary) |
| 정기 수집 | Celery beat | Vercel Cron → `/api/cron/collect/` |
| 비동기 작업 | Celery worker | 동기 실행(`BACKTEST_EXECUTOR=sync`) |
| 모니터링 | 로그 | Sentry |

Vercel은 서버리스라 상시 실행되는 worker/beat를 띄울 수 없다. 그래서 정기 수집은 Cron으로, 무거운 작업은 로컬 Celery로 나눴다. 이 트레이드오프를 README에 적는다.

```
crypto-quant-lab/
├── backend/        config/, market/, backtest/, tests/, requirements.txt, ruff.toml, pytest.ini, vercel.json
├── frontend/       Next.js
├── docs/           PLAN.md (private/ 는 커밋 제외)
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

## 6. 설계

### 6.1 데이터 소스 (업비트)

- `GET https://api.upbit.com/v1/candles/days?market=KRW-BTC&count=200&to=<ISO8601>`
- 한 번에 최대 200개라 `to`를 과거로 옮기며 페이지를 넘긴다.
- 요청 간격은 0.15초로 두고, 429·5xx·네트워크 오류는 지수 백오프(0.5→1→2…초)로 최대 5번 재시도한다. 404 등 4xx는 재시도하지 않는다.
- 응답 JSON은 `parse_float=Decimal`로 읽어 가격 정밀도를 보존한다.
- 일봉 경계는 KST 09:00(= UTC 00:00)이고, `date`는 KST 거래일로 정의한다. 진행 중인 일봉의 날짜는 현재 UTC 날짜다(`current_trading_day`).
- 대상 종목: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE

### 6.2 모델

```text
Asset          symbol(unique), name, listed_on, is_active
DailyCandle    asset, date, open/high/low/close Decimal(24,8), volume, value,
               is_final, collected_at — unique(asset, date)
CollectionRun  trigger(cron/manual/beat/backfill), started_at, finished_at,
               status(running/success/partial/failed), upserted_count, error_message
IntegrityIssue asset, date, type, severity(error/warning), detail(JSON),
               detected_run, resolved_at, note — unique(asset, date, type)
BacktestRun    asset, params(JSON), params_hash, data_version, metrics(JSON),
               benchmark(JSON), equity_curve(JSON), created_at — unique(params_hash, data_version)
```

- upsert는 `bulk_create(update_conflicts=True)`로 처리한다. MySQL에서는 `ON DUPLICATE KEY UPDATE`로 변환된다.
- 매번 최근 7일을 다시 받아 덮어써서 미완성 봉과 정정된 값을 보정한다.
- 진행 중인 봉(아직 마감 안 된 봉)은 `is_final=False`로 저장하고 백테스트에서 제외한다.
- 이슈는 다시 발견되지 않으면 자동 해결되고, 사람이 사유(`note`)를 남겨 해결한 이슈는 재검사해도 다시 열리지 않는다.

### 6.3 무결성 규칙

| 규칙 | 조건 | 심각도 |
|---|---|---|
| MISSING | `listed_on`부터 진행 중인 일봉 전날까지 중 빠진 날짜 | error |
| OHLC_INVALID | `low ≤ min(open, close)`, `max(open, close) ≤ high` 위반 | error |
| NON_POSITIVE | 가격 ≤ 0 | error |
| ZERO_VOLUME | 거래량 0 | warning |
| SPIKE | \|일간 수익률\| > 30% (설정값) | warning |
| STALE | 최신 확정 봉이 2일 이상 지남 | error |

요청 기간 안에 해결되지 않은 error 이슈가 있으면 백테스트를 422로 거부한다(빈 날짜를 forward-fill로 메우지 않는다).

### 6.4 백테스트

- 전략: `ma_cross(short, long)`, `buy_and_hold`. 모두 `종가 → signal(목표 비중 0/1)` 인터페이스를 따르고, 엔진이 하루 늦춰 position으로 적용한다.
- 미래참조 방지: `position = signal.shift(1)`. (Could) `execution="next_open"` 옵션.
- 워밍업: `start - long - 1`일부터 데이터를 조회한다(-1일은 시작일 수익률 계산용). 데이터가 모자라면 422.
- 비용: `fee` 하나로 수수료(+슬리피지)를 표현한다. 기본 0.05%, 0~1% 범위. 포지션이 바뀐 날에만 차감하고, 시작일 직전은 현금으로 보아 진입 비용도 낸다.
- 지표: 누적수익률, CAGR(365일), MDD, 샤프(365일, 무위험수익률 0), 거래 횟수, 승률, 노출 비율
- 같은 기간·같은 수수료의 Buy&Hold 지표를 항상 함께 돌려준다(벤치마크).
- 테스트: 신호·시뮬레이션·지표 손계산 비교, 거래가 없으면 지표 0, 미래 데이터를 바꿔도 과거 포지션이 그대로인지 확인(look-ahead 회귀 테스트)

### 6.5 API

| 메서드 | 경로 | 비고 |
|---|---|---|
| GET | `/api/health/` | DB·Redis 연결 확인 + 서비스별 소요 시간(`latency_ms`), throttle 제외 |
| GET | `/api/assets/` | |
| GET | `/api/candles/?symbol=&from=&to=` | 페이지당 500개(최대 5000, `page_size`) |
| GET | `/api/integrity/summary/` | 종목별 이슈 수, 마지막 수집 시각 |
| GET | `/api/integrity/issues/` | symbol, type, severity, resolved 필터 |
| GET | `/api/collection-runs/` | |
| POST | `/api/backtests/` | 새로 계산 201 / 기존 결과 200 / 입력 오류 400 / 데이터 오류 422 / 분당 20회 초과 429 |
| GET | `/api/backtests/{id}/` | |
| POST | `/api/backtests/grid/` | (Could) 로컬에서는 Celery로 202 응답 |
| GET | `/api/cron/collect/` | `Authorization: Bearer $CRON_SECRET` 검증(비어 있으면 전부 거부), throttle 제외. 끝의 `/` 필수(Cron은 리다이렉트를 따라가지 않음) |
| GET | `/api/schema/`, `/api/docs/` | OpenAPI 스키마, Swagger UI (drf-spectacular) |

캐시 키는 `bt:{sha256(정렬된 파라미터)}:{data_version}`이다. 새 데이터가 들어오면 키가 바뀌므로 따로 지울 필요가 없다.

### 6.6 인프라 체크리스트

- 서버리스 환경의 커넥션 누수를 막기 위해 `CONN_MAX_AGE=0`
- 정적 파일은 Vercel이 빌드 때 collectstatic 후 CDN으로 서빙(WhiteNoise는 로컬용)
- 번들 크기·함수 실행 시간 제한은 D1에 확인
- 함수·DB·캐시는 같은 리전(싱가포르)에 둔다. 함수 리전은 `backend/vercel.json`의 `regions`로 고정
- Cron `30 0 * * *`(UTC, KST 09:30). production 배포에서만 실행된다.
- 백필은 Cron이 아니라 로컬 `manage.py collect --all`로 운영 DB에 직접 실행한다. 정기 수집은 `collect`(최근 7일)와 같은 함수를 쓴다.

### 6.7 대시보드 화면 구성

API 응답(JSON)은 사람이 읽기 어렵다. 링크 하나로 데이터 → 품질 → 백테스트 → 운영 상태를 눈으로 확인할 수 있게 화면을 나눈다. **첫 화면은 대시보드 홈**이고, API 서버의 `/`는 대시보드로 리다이렉트한다(지금은 404).

| 경로 | 화면 | 보여 줄 것 | 쓰는 API |
|---|---|---|---|
| `/` | 홈 | 상태 요약 띠(서버 정상·마지막 수집·열린 error 수), 종목 카드 5개(최근 종가, 30일 수익률, 미니 추세선), 각 화면 바로가기 | health, integrity/summary, candles |
| `/assets/[symbol]` | 가격 차트 | 캔들 + 이동평균선(짧은/긴 기간 조절), 기간 선택 | candles |
| `/backtest` | 백테스트 | 입력 폼 → 지표 카드(전략 vs Buy&Hold), 누적수익 곡선, 드로다운 차트 | backtests |
| `/integrity` | 데이터 품질 | 종목별 데이터 범위·열린 이슈 수 표, 이슈 목록(종목·유형·심각도·해결 여부 필터) | integrity/summary, integrity/issues |
| `/status` | 운영 상태 | 서버 상태(DB·Redis 정상 여부와 응답 시간), 마지막 Cron 실행 후 경과 시간(26시간 넘으면 경고), 수집 기록 타임라인(성공/일부 실패/실패 색 구분, Cron·수동 구분), 날짜별 저장 건수 막대, 종목별 최신 확정일과 밀린 일수 | health, collection-runs, integrity/summary |

- 모든 화면에 로딩·빈 데이터·오류 상태를 둔다. API가 죽어도 화면이 깨지지 않고 "API 응답 없음"을 보여 준다.
- 운영 상태 화면이 README 한계의 "Cron이 아예 안 돌면 Sentry로 알 수 없다"를 보완한다.
- 휴대폰 너비에서도 볼 수 있게 만든다(면접관이 링크를 폰으로 열 수 있음).

## 7. 일정 (7일, 하루 7~9시간)

| 일차 | 작업 | 완료 기준 |
|---|---|---|
| **D1** 셋업·배포 | 외부 계정 가입(Vercel·Aiven·Upstash·Sentry), Django+DRF, settings 분리, docker compose, ruff, CI(lint), `/api/health/`, pandas 포함해 Vercel 배포 | 배포 URL의 health가 200 응답 |
| **D2** 수집·무결성 | 모델·마이그레이션, 업비트 클라이언트(재시도·백오프), collect 커맨드(--all 백필), upsert, 무결성 검사기, CollectionRun, 테스트(`responses` 모킹) | 같은 수집을 두 번 돌려도 행·이슈 수가 같음 |
| **D3** 백테스트·API | 백테스트 엔진·지표, 손계산·look-ahead 테스트, serializer 검증, 필터·페이지네이션, Redis 캐시, throttle, Swagger | pytest 통과, 두 번째 호출이 캐시 히트 |
| **D4** 운영 배포 | Vercel 환경변수, Cron + CRON_SECRET, Sentry, 운영 DB 백필, README 1차 | **지원 가능 시점.** 배포 API로 백테스트 성공 |
| **D5** 대시보드 ① | Cron 자동 실행 확인, Next.js 셋업, 두 번째 Vercel 프로젝트, CORS, 홈(상태 요약·종목 카드), 가격 차트(캔들+MA), 백테스트 화면(폼·누적수익 곡선 vs Buy&Hold·드로다운), API 서버 `/` → 대시보드 리다이렉트 | 대시보드 주소 첫 화면에서 상태·종목이 보이고 백테스트 실행 |
| **D6** 대시보드 ②·완성도 | 데이터 품질 화면, 운영 상태 화면(서버·Cron·수집 기록 차트), CI에 MySQL + pytest, (Could) Celery 그리드 탐색 + 히트맵 | 운영 상태 화면에서 매일 Cron 기록 확인, CI 녹색 |
| **D7** 마무리 | README 완성(아키텍처 그림, 설계 이유, 트러블슈팅, 한계), 데모 GIF, 전체 코드 리뷰, 면접 예상 질문 정리 | 모든 모듈을 말로 설명 가능 |

공고 마감이 가까우면 D4 끝에 지원하고, 여유가 있으면 D7 이후 지원한다.

## 8. 진행 현황

| 일차 | 상태 | 결과 |
|---|---|---|
| D1 | ✅ 완료 | Vercel 배포, 공개 URL의 `/api/health/`에서 DB·Redis 정상 확인 |
| D2 | ✅ 완료 | 5종목 13,740행 백필(로컬·운영), 재수집 시 중복 0건, 테스트 37개. ETH·XRP 2017-10-21~23 결측은 업비트 원본에도 없음을 확인하고 해결 처리 |
| D3 | ✅ 완료 | 백테스트 엔진(신호 하루 지연·수수료·지표), 조회·백테스트 API, Redis 캐시(파라미터 해시+데이터 버전), throttle, Swagger(`/api/docs/`), 관리자 화면, 테스트 85개. 운영: 함수·Redis를 DB와 같은 싱가포르로 옮겨 응답 4.2초 → 0.46초 |
| D4 | ✅ 완료 | Vercel Cron(매일 KST 09:30) + `CRON_SECRET` 인증, Sentry(운영 오류 수신 확인), README 1차, 테스트 93개. 운영에서 Cron 엔드포인트 수동 호출로 5종목 35건 수집, 배포 API 백테스트 성공. Cron 자동 실행은 D5 아침에 확인 |
| D5 | ⏳ 다음 | Cron 자동 실행 확인, 대시보드 ①(홈·가격 차트·백테스트), `/` → 대시보드 |

## 9. 면접 포인트

1. 미래참조 편향 방지: shift(1), 체결 시점 가정, 회귀 테스트
2. 미완성 봉 처리: `is_final`과 최근 7일 재수집
3. 가격은 Decimal(저장 정확도), 수익률은 float(벡터 연산)
4. 멱등성: unique 제약과 upsert, 이슈 테이블의 unique 제약
5. 캐시 무효화: 데이터 버전을 키에 포함
6. 서버리스 제약: Cron vs beat, 커넥션 관리, 긴 작업 분리, sync/celery 실행 방식 전환
7. 연율화를 365일로 한 이유, forward-fill 대신 거부를 택한 이유
8. 한계: 생존 편향(현재 상장 종목만), 일봉 해상도, 단일 거래소
