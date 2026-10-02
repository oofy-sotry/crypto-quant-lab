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
4. 매일 끝에 `docs/NOTES.md`에 그날 내린 설계 결정과 이유를 직접 적는다(면접 대비).

## 4. 우선순위 (밀리면 아래부터 자른다)

| 등급 | 항목 |
|---|---|
| Must | 수집·백필, upsert, 무결성 검사, 백테스트(MA 교차 + Buy&Hold), DRF API, Redis 캐시, Vercel 배포 + Cron, README |
| Should | Next.js 대시보드(차트·백테스트 폼·무결성 화면), Sentry, CI의 MySQL + pytest, Swagger |
| Could | Celery 그리드 탐색 + 히트맵, 다음날 시가 체결 옵션, 데모 GIF |

## 5. 아키텍처

| 구분 | 로컬 (docker compose) | 배포 |
|---|---|---|
| 백엔드 | Django + DRF | Vercel 프로젝트 ① (Root: `backend`) |
| 프론트 | Next.js | Vercel 프로젝트 ② (Root: `frontend`) |
| DB | MySQL 컨테이너 | Aiven MySQL (SSL) |
| 캐시 | Redis 컨테이너 | Upstash Redis |
| 정기 수집 | Celery beat | Vercel Cron → `/api/cron/collect` |
| 비동기 작업 | Celery worker | 동기 실행(`BACKTEST_EXECUTOR=sync`) |
| 모니터링 | 로그 | Sentry |

Vercel은 서버리스라 상시 실행되는 worker/beat를 띄울 수 없다. 그래서 정기 수집은 Cron으로, 무거운 작업은 로컬 Celery로 나눴다. 이 트레이드오프를 README에 적는다.

```
crypto-quant-lab/
├── backend/        config/, market/, backtest/, tests/, pyproject.toml, vercel.json
├── frontend/       Next.js
├── docs/           PLAN.md, NOTES.md
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

## 6. 설계

### 6.1 데이터 소스 (업비트)

- `GET https://api.upbit.com/v1/candles/days?market=KRW-BTC&count=200&to=<ISO8601>`
- 한 번에 최대 200개라 `to`를 과거로 옮기며 페이지를 넘긴다.
- 요청 간격은 약 0.15초로 두고, 429 응답이면 지수 백오프로 재시도한다. `Remaining-Req` 헤더를 로그에 남긴다.
- 일봉 경계는 KST 09:00(= UTC 00:00)이고, `date`는 KST 거래일로 정의한다.
- 대상 종목: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE

### 6.2 모델

```text
Asset          symbol(unique), name, listed_on, is_active
DailyCandle    asset, date, open/high/low/close Decimal(24,8), volume, value,
               is_final, collected_at — unique(asset, date)
CollectionRun  trigger(cron/manual/beat/backfill), started_at, finished_at,
               status(running/success/partial/failed), upserted_count, error_message
IntegrityIssue asset, date, type, severity(error/warning), detail(JSON),
               detected_run, resolved_at — unique(asset, date, type)
BacktestRun    params(JSON), params_hash, data_version, status, metrics(JSON),
               equity_curve(JSON), created_at
```

- upsert는 `bulk_create(update_conflicts=True)`로 처리한다. MySQL에서는 `ON DUPLICATE KEY UPDATE`로 변환된다.
- 매번 최근 7일을 다시 받아 덮어써서 미완성 봉과 정정된 값을 보정한다.
- 오늘 봉(아직 마감 안 된 봉)은 `is_final=False`로 저장하고 백테스트에서 제외한다.

### 6.3 무결성 규칙

| 규칙 | 조건 | 심각도 |
|---|---|---|
| MISSING | `listed_on`부터 어제까지 중 빠진 날짜 | error |
| OHLC_INVALID | `low ≤ min(open, close)`, `max(open, close) ≤ high` 위반 | error |
| NON_POSITIVE | 가격 ≤ 0 | error |
| ZERO_VOLUME | 거래량 0 | warning |
| SPIKE | \|일간 수익률\| > 30% (설정값) | warning |
| STALE | 최신 확정 봉이 2일 이상 지남 | error |

요청 기간 안에 해결되지 않은 error 이슈가 있으면 백테스트를 422로 거부한다(빈 날짜를 forward-fill로 메우지 않는다).

### 6.4 백테스트

- 전략: `ma_cross(short, long)`, `buy_and_hold`. 모두 `prices → position` 인터페이스를 따른다.
- 미래참조 방지: `position = signal.shift(1)`. (Could) `execution="next_open"` 옵션.
- 워밍업: `start - long`일부터 데이터를 조회한다.
- 비용: 수수료 0.05% 기본값, 슬리피지(bp)는 파라미터. 포지션이 바뀐 날에만 차감한다.
- 지표: 누적수익률, CAGR(365일), MDD, 샤프(365일, 무위험수익률 0), 거래 횟수, 승률, 노출 비율
- 테스트: 손계산 비교, 상수 가격이면 수익률 0, 미래 데이터를 바꿔도 과거 포지션이 그대로인지 확인(look-ahead 회귀 테스트)

### 6.5 API

| 메서드 | 경로 | 비고 |
|---|---|---|
| GET | `/api/health/` | DB·Redis 연결 확인 |
| GET | `/api/assets/` | |
| GET | `/api/candles/?symbol=&from=&to=` | 페이지네이션, 기간 상한 |
| GET | `/api/integrity/summary/` | 종목별 이슈 수, 마지막 수집 시각 |
| GET | `/api/integrity/issues/` | symbol, type, resolved 필터 |
| GET | `/api/collection-runs/` | |
| POST | `/api/backtests/` | 캐시 히트면 200, 새로 계산하면 201, throttle |
| GET | `/api/backtests/{id}/` | |
| POST | `/api/backtests/grid/` | (Could) 로컬에서는 Celery로 202 응답 |
| GET | `/api/cron/collect` | `Authorization: Bearer $CRON_SECRET` 검증 |
| GET | `/api/docs/` | drf-spectacular |

캐시 키는 `bt:{sha256(정렬된 파라미터)}:{data_version}`이다. 새 데이터가 들어오면 키가 바뀌므로 따로 지울 필요가 없다.

### 6.6 인프라 체크리스트

- 서버리스 환경의 커넥션 누수를 막기 위해 `CONN_MAX_AGE=0`
- 정적 파일은 WhiteNoise로 서빙
- 번들 크기·함수 실행 시간 제한은 D1에 확인
- Cron `30 0 * * *`(UTC, KST 09:30). production 배포에서만 실행된다.
- 백필은 Cron이 아니라 로컬 `manage.py backfill`로 운영 DB에 직접 실행한다.

## 7. 일정 (7일, 하루 7~9시간)

| 일차 | 작업 | 완료 기준 |
|---|---|---|
| **D1** 셋업·배포 | 외부 계정 가입(Vercel·Aiven·Upstash·Sentry), Django+DRF, settings 분리, docker compose, ruff, CI(lint), `/api/health/`, pandas 포함해 Vercel 배포 | 배포 URL의 health가 200 응답 |
| **D2** 수집·무결성 | 모델·마이그레이션, 업비트 클라이언트(재시도·백오프), backfill 커맨드, upsert, 무결성 검사기, CollectionRun, 테스트(`responses` 모킹) | 같은 수집을 두 번 돌려도 행·이슈 수가 같음 |
| **D3** 백테스트·API | 백테스트 엔진·지표, 손계산·look-ahead 테스트, serializer 검증, 필터·페이지네이션, Redis 캐시, throttle, Swagger | pytest 통과, 두 번째 호출이 캐시 히트 |
| **D4** 운영 배포 | Vercel 환경변수, Cron + CRON_SECRET, Sentry, 운영 DB 백필, README 1차 | **지원 가능 시점.** 배포 API로 백테스트 성공 |
| **D5** 대시보드 ① | Cron 실행 확인, Next.js 셋업, 두 번째 Vercel 프로젝트, CORS, 캔들+MA 차트, 백테스트 폼, 누적수익 곡선 vs Buy&Hold, 드로다운 | 배포된 대시보드에서 백테스트 실행 |
| **D6** 대시보드 ②·완성도 | 무결성 대시보드, CI에 MySQL + pytest, (Could) Celery 그리드 탐색 + 히트맵 | CI 녹색 |
| **D7** 마무리 | README 완성(아키텍처 그림, 설계 이유, 트러블슈팅, 한계), 데모 GIF, 전체 코드 리뷰, 면접 예상 질문 정리 | 모든 모듈을 말로 설명 가능 |

공고 마감이 가까우면 D4 끝에 지원하고, 여유가 있으면 D7 이후 지원한다.

## 8. 면접 포인트

1. 미래참조 편향 방지: shift(1), 체결 시점 가정, 회귀 테스트
2. 미완성 봉 처리: `is_final`과 최근 7일 재수집
3. 가격은 Decimal(저장 정확도), 수익률은 float(벡터 연산)
4. 멱등성: unique 제약과 upsert, 이슈 테이블의 unique 제약
5. 캐시 무효화: 데이터 버전을 키에 포함
6. 서버리스 제약: Cron vs beat, 커넥션 관리, 긴 작업 분리, sync/celery 실행 방식 전환
7. 연율화를 365일로 한 이유, forward-fill 대신 거부를 택한 이유
8. 한계: 생존 편향(현재 상장 종목만), 일봉 해상도, 단일 거래소
