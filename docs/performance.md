# 쿼리·인덱스 튜닝 기록 (v2 1단계 D5)

분봉 1년치(260만 행)에서 조회 API와 정합성 검사 쿼리를 측정하고 고친 기록이다.
결론부터: **가장 큰 개선은 인덱스 추가가 아니라 쿼리 모양을 바꾼 것**(GROUP BY → 종목별 LIMIT 1 서브쿼리, OFFSET → keyset)이었다.
새 인덱스 후보 4가지(커버링, 컬럼 순서 반대, BRIN, 부분 인덱스)는 측정 결과 모두 넣지 않았다.

## 1. 측정 환경과 규칙

| 항목 | 값 |
|---|---|
| DB | 로컬 Docker PostgreSQL 18.6, `shared_buffers` 128MB(기본값) |
| 데이터 | 분봉 5종목 × 1년(2025-10-23 ~ 2026-10-22 UTC) 2,579,886행, 테이블 308MB<br>시간봉 43,699행, 일 집계 1,825행, 이슈 57건 |
| 측정 전 | `VACUUM (ANALYZE)` (VM 비정상 종료로 통계가 초기화돼 있었음) |
| 도구 | `manage.py explain_scenarios` — 시나리오를 **실제 코드 경로**(API 뷰, 검사 함수)로 실행하고, 그때 나간 SQL을 그대로 `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF)` |
| 반복 | 워밍업 1회 + 5~7회 중앙값. 모두 warm cache(워밍업으로 데이터가 메모리에 올라간 상태) |
| 요청당 쿼리 수·DB 시간 | `config/querylog.py` — `connection.execute_wrapper`로 측정, 모든 응답에 `Server-Timing: db;dur=…;desc="N queries"` 헤더 |

주의할 점
- **`TIMING OFF`를 쓴 이유:** 노드마다 시계를 읽는 비용 때문에, 행이 많은 쿼리는 EXPLAIN ANALYZE 시간이 실제보다 1.5배 이상 부풀었다(1년 빈 구간: EXPLAIN 794ms, 실제 호출 488ms). 껐는데도 수십만 행을 처리하는 쿼리는 여전히 실제보다 크게 나온다. 그래서 그런 쿼리는 "요청 시간"(코드 호출 시간) 열을 본다.
- **흔들림:** VM이라 같은 코드도 측정마다 ±30% 정도 달라진다(바꾸지 않은 `gaps_year` 요청 시간이 측정마다 506~682ms). 아래 표는 ±30%를 넘는, 수십~수천 배 차이만 개선으로 본다.
- API 요청 시간에는 파이썬 직렬화가 포함된다. 분봉 500행을 JSON으로 만드는 데 약 30~40ms가 들고, 이건 DB와 무관하다.

## 2. 시나리오별 전후

DB 시간 = 그 요청이 실행한 SQL들의 EXPLAIN 실행 시간 합. 요청 시간 = 뷰 호출부터 응답 렌더링까지.

| # | 시나리오 | 쿼리 수 | DB 시간 (ms) | 요청 시간 (ms) | 바꾼 것 |
|---|---|---|---|---|---|
| 1 | 분봉 목록 첫 페이지 (BTC 52만 행 중 500) | 3 → 2 | 134.8 → 0.13 | 167 → 40 | keyset 페이지네이션 |
| 1 | 분봉 목록 깊은 페이지 (249,500번째부터) | 3 → 2 | 164.3 → 0.28 | 213 → 45 | keyset 페이지네이션 |
| 1 | 분봉 목록 최근 30일 첫 페이지 | 3 → 2 | 12.0 → 0.21 | 48 → 55 | keyset (요청 시간은 직렬화가 대부분) |
| 2 | 시간봉 최근 30일 | 3 → 2 | 1.1 → 2.2 | 58 → 55 | keyset (원래 빠름, 차이는 흔들림 범위) |
| 2 | 시간봉 1년 첫 페이지 | 3 → 2 | 0.9 → 0.8 | 63 → 68 | 〃 |
| 3 | 종목별 최신 상태 (분봉·시간봉·일 집계) | 4 → 1 | 469.1 → 0.23 | 613 → 7 | GROUP BY → 종목별 LIMIT 1 서브쿼리 |
| 4 | 빈 구간 탐지 31일 | 1 → 1 | 49 → 59 | 61 → 46 | 그대로 (아래 4절) |
| 4 | 빈 구간 탐지 1년 | 1 → 1 | 495 → 647 | 512 → 506 | 그대로 |
| 5 | 미해결 이슈 목록 | 2 → 2 | 0.1 → 0.1 | 4 → 9 | 그대로 (57건이라 Seq Scan이 맞음) |

### 2.1 종목별 최신 상태: 전체 Seq Scan → 인덱스 끝에서 한 칸

처음 구현은 테이블마다 `GROUP BY asset_id` + `Max(ts)`였다.

```
전: Seq Scan on market_minutecandle  (260만 행 전부, shared hit 9,418 + read 29,970)  444ms
후: 종목마다 Index Only Scan Backward on uniq_minute_asset_ts … LIMIT 1           3개 테이블 합쳐 0.23ms, hit 40
```

- PostgreSQL은 GROUP BY에서 "그룹마다 인덱스의 마지막 값만 건너뛰며 읽기"(loose index scan)를 하지 않아 모든 행을 읽는다.
- `Asset`에 `Subquery(… .order_by("-ts")[:1])`를 붙이면 종목마다 unique(asset_id, ts) 인덱스를 끝에서 한 칸만 읽는다. 세 테이블을 한 쿼리로 합쳐 쿼리 수도 4 → 1.
- 종목 수(5)에 비례하는 비용이라 분봉이 늘어도 시간이 거의 그대로다.

### 2.2 분봉·집계 목록: 페이지 번호(OFFSET) → keyset(CursorPagination)

페이지 번호 방식의 비용 두 가지:
1. **페이지마다 `COUNT(*)`** — BTC 분봉 52만 행을 매번 센다(Index Only Scan 135ms). 첫 페이지도 느린 이유.
2. **OFFSET** — 249,500행을 인덱스에서 읽고 버린 뒤 500행을 준다(68ms, 깊을수록 느려짐).

keyset은 `WHERE ts > 마지막으로 본 시각 ORDER BY ts LIMIT 501`이라 COUNT가 없고 어느 위치든 인덱스에서 바로 찾는다(0.1~0.3ms).

- 대가: 전체 개수와 "N페이지로 바로 가기"가 없다. 시계열을 앞에서부터 차례로 읽는 용도(차트, 내보내기, LLM 도구)라 문제없다고 판단했다.
- 정렬 컬럼이 종목 안에서 유일(unique(asset, ts))해야 keyset이 행을 빠뜨리거나 겹치지 않는다.
- 기존 일봉 API(`/api/candles/`)는 대시보드가 쓰고 5종목 × 수천 행뿐이라 페이지 번호 방식을 그대로 뒀다.
- 위치 값을 직접 고친 커서(`p=yesterday`)는 DRF가 처리하지 못해 500을 냈다 → 404로 바꾸고 테스트를 추가했다.

## 3. 인덱스 실험 (모두 트랜잭션 안에서 만들고 롤백)

대표 쿼리
- **page**: `asset_id = BTC AND ts >= 30일 전 ORDER BY ts LIMIT 501` (분봉 API 한 페이지)
- **range_agg**: `asset_id = BTC AND ts` 30일 범위의 `count(*), sum(volume)` (범위 전체를 힙까지 읽음)
- **all_assets_hour**: `ts` 1시간 범위, 종목 조건 없음

| 인덱스 | 크기 | page | range_agg | all_assets_hour | 판단 |
|---|---|---|---|---|---|
| **기존** unique(asset_id, ts) B-tree | 151MB (새로 만들면 78MB) | 0.14ms | 13.3ms | 0.74ms | 유지 — upsert의 `ON CONFLICT` 대상이라 어차피 필요 |
| 커버링 (asset_id, ts) INCLUDE (가격·거래량 6개) | 214MB | 0.16ms | 11.0ms | — | 넣지 않음: 크기 2.7배, range_agg만 2ms 이득 |
| 순서 반대 (ts, asset_id) | 78MB | 0.24ms | 20.6ms | 0.08ms | 넣지 않음: 앱 쿼리는 모두 종목 조건이 있고 그쪽은 느려짐 |
| BRIN (asset_id, ts), 현재 물리 순서 | 32KB | 71ms | 67ms | — | 넣지 않음: 물리 순서가 섞여 있어 거의 전부 읽음 |
| BRIN (asset_id, ts), (asset_id, ts)로 정렬한 복사본 | 32KB | 16.7ms | 13.2ms | — | 범위 집계는 B-tree와 같지만 ORDER BY … LIMIT엔 느림 |

### 3.1 컬럼 순서: (asset_id, ts)가 맞는 이유

- 앱의 분봉 쿼리는 전부 `asset_id = ?`와 `ts` 범위를 같이 건다(목록, 집계, 빈 구간, 재처리). 같음 조건 컬럼을 앞에 두면 그 종목 구간만 연속으로 읽는다.
- (ts, asset_id)는 범위 조건이 앞이라 그 시간대의 5종목을 다 읽고 거른다 → range_agg 13 → 21ms.
- 종목 조건이 없는 쿼리(예: D6에서 넣을 "30일 지난 분봉 삭제" `ts < X`)도 PostgreSQL 18의 **B-tree skip scan**이 (asset_id, ts) 인덱스를 종목마다 건너뛰며 쓴다. 계획에 `Index Searches: 6`, 하루치 7,183행 3.2ms. 종목이 5개뿐이라 skip scan이 잘 맞는다 → (ts, asset_id) 인덱스를 따로 둘 이유가 없다.

### 3.2 BRIN: 물리 순서(correlation)가 전부

- BRIN은 블록 범위마다 최솟값·최댓값만 저장한다(32KB). 값이 디스크에 정렬돼 있어야 "이 블록은 건너뛴다"가 된다.
- 이 테이블의 `pg_stats.correlation`: ts −0.078, asset_id −0.523. 백필을 200개씩 과거 방향으로 받았고, D2 재실행·D4 재처리의 upsert가 행을 새 위치에 다시 써서 순서가 섞였다. → BRIN이 거의 모든 블록을 후보로 내서 B-tree보다 5배 느림.
- (asset_id, ts)로 정렬한 복사본에서는 범위 집계가 B-tree와 같은 속도(13.2 vs 14.1ms)에 크기는 1/4,800. 하지만 `ORDER BY ts LIMIT 501`은 BRIN이 순서를 주지 못해 범위를 다 읽고 정렬한다(16.7 vs 0.18ms).
- 결론: 순서대로 쌓이기만 하는 테이블(예: 2단계의 분봉 보관용 Parquet 적재 전 단계)이 아니면 쓰지 않는다. 여기선 upsert·재처리로 행이 계속 다시 쓰인다.

### 3.3 커버링 인덱스(INCLUDE)

- page 쿼리는 `SELECT *`라 id까지 필요해서 커버링이어도 힙을 읽는다(Index Scan, 이득 없음).
- range_agg는 Index Only Scan이 돼 13.3 → 11.0ms, 버퍼 917 → 499. 이득 2ms에 136MB(새로 만든 기본 인덱스 78MB 대비 214MB)는 맞지 않는다. 운영 Neon 무료 용량이 0.5GB라 더 그렇다.

### 3.4 부분 인덱스 (미해결 이슈)

- 미해결 이슈 조회는 `resolved_at IS NULL`이라 `WHERE resolved_at IS NULL` 부분 인덱스가 교과서적 후보다.
- 하지만 이슈가 57건(블록 2개)이라 Seq Scan이 0.02ms다. 인덱스로 더 줄일 여지가 없고 쓰기 비용만 는다. 이슈가 수만 건이 되면 다시 잰다.

### 3.5 인덱스 부풀림 (발견)

- 기존 unique 인덱스 151MB, 같은 행으로 새로 만든 B-tree 78MB. REINDEX해 보니(롤백함) unique 151 → 78MB, pkey 111 → 55MB.
- D2 1년치 전체 재실행과 재처리의 `ON CONFLICT DO UPDATE`가 행 버전을 새로 만들면서 인덱스 페이지가 반쯤 빈 채로 남은 것으로 본다.
- 메모리에 다 올라간 상태에서는 속도 차이가 없었다(1년 빈 구간: 버퍼 4,726 → 3,144, 시간은 흔들림 범위). 용량·캐시 효율 문제라, 대량 재적재 뒤에 `REINDEX INDEX CONCURRENTLY`를 하는 것을 운영 절차로 남긴다. 운영 Neon은 최근 30일만 두므로 D6 적재 때 크기를 확인한다.

## 4. 빈 구간 탐지는 그대로 둔 이유

- 현재 구현: 기간의 ts를 `lag(ts)`로 앞 분과 비교. 이미 Index Only Scan(Heap Fetches 0)이고, 기간의 모든 분봉을 한 번씩 읽는 것 자체가 일이다(1년 52만 행 ≈ 0.5초).
- 로드맵 원안이던 `generate_series`로 모든 분을 만들고 `NOT EXISTS`로 대조하는 방식은 31일 기준 112ms로 lag(29ms)보다 3.8배 느렸다(분마다 인덱스를 한 번씩 찾음).
- 1년 검사는 커맨드(`aggregate_minutes --all`)에서만 돌고, 매일 도는 검사는 2일치라 수 ms다.

## 5. 요청당 쿼리 수 고정 (N+1 방지)

`tests/test_query_counts.py`가 조회 API 9개의 쿼리 수를 고정한다. 데이터는 5종목 × 여러 행으로 만들어서, 행마다 쿼리가 늘면 바로 실패한다.
실제로 이슈 목록에서 `select_related("asset")`를 빼면 쿼리 2 → 7개가 돼 테스트가 실패하는 것을 확인했다.

| API | 쿼리 수 | 내용 |
|---|---|---|
| `/api/assets/` | 1 | |
| `/api/candles/` | 3 | 종목 + COUNT + 목록 (페이지 번호 방식) |
| `/api/minutes/`, `/api/bars/` | 2 | 종목 + 목록 (COUNT 없음) |
| `/api/minutes/status/` | 1 | 전 종목 최신 시각을 서브쿼리로 한 번에 |
| `/api/integrity/issues/` | 2 | COUNT + 목록 (종목은 JOIN) |
| `/api/integrity/summary/` | 3 | 이슈 수 + 일봉 범위 + 마지막 수집 |
| `/api/collection-runs/` | 2 | |
| `/api/reprocess/{id}/` | 1 | 종목은 JOIN |

## 6. 다시 재는 법

```bash
cd backend
.venv/bin/python manage.py explain_scenarios                     # 시나리오 9개 전부
.venv/bin/python manage.py explain_scenarios --only minute_status --repeat 7 --out result.json
curl -sI "http://127.0.0.1:8001/api/minutes/?symbol=KRW-BTC" | grep -i server-timing
```

## 7. 남은 후보

- 목록 API 요청 시간의 대부분(30~40ms)은 DRF 직렬화(Decimal 500행)다. DB가 아니라 파이썬 쪽이라 이번 범위에서 뺐다.
- 운영(Neon, 30일치)에서의 수치는 D6 운영 반영 때 같은 커맨드로 잰다(첫 요청은 Neon이 깨어나는 시간이 더해진다).
