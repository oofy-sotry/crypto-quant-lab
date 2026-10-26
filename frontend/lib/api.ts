// 백엔드(Django REST API) 호출과 응답 타입.
// 조회는 서버 컴포넌트에서 캐시해 부르고, 백테스트 실행만 브라우저가 직접 부른다.

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE ?? "https://crypto-quant-lab-oofysotry.vercel.app"
).replace(/\/$/, "");

// 일봉은 하루 한 번 바뀌므로 5분 캐시면 충분하다. API 호출 수와 응답 시간을 함께 줄인다.
const REVALIDATE_SECONDS = 300;

export type Health = {
  status: "ok" | "error";
  checks: Record<string, string>;
  latency_ms: Record<string, number>;
  // 느린 쿼리 기준과 최근 24시간 건수(Redis 장애면 null). 이전 배포의 API엔 없을 수 있다.
  queries?: { slow_threshold_ms: number; slow_24h: number | null };
};

// 가격은 정밀도를 지키려고 API가 문자열(Decimal)로 준다. 차트에 그리기 직전에만 숫자로 바꾼다.
export type Candle = {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  value: string;
  is_final: boolean;
};

export type AssetSummary = {
  symbol: string;
  name: string;
  candle_count: number;
  first_date: string | null;
  last_final_date: string | null;
  open_errors: number;
  open_warnings: number;
};

export type CollectionRun = {
  id: number;
  kind: "daily" | "minutes";
  trigger: "cron" | "beat" | "manual" | "backfill";
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  assets_count: number;
  upserted_count: number;
  error_message: string;
  // 분봉 파이프라인: {range: [시작일, 끝일], timings: {단계: 초}, deleted_minutes, keep_days, checks}
  detail: Record<string, unknown>;
};

export type IntegritySummary = {
  assets: AssetSummary[];
  last_run: CollectionRun | null;
};

export type IssueType =
  | "missing"
  | "ohlc_invalid"
  | "non_positive"
  | "zero_volume"
  | "spike"
  | "stale"
  | "minute_mismatch"
  | "minute_gap";

/** minute_mismatch detail의 필드 하나: 분봉 집계 값과 업비트 일봉 값. */
export type MismatchField = { minute: string; daily: string };

export type IntegrityIssue = {
  id: number;
  symbol: string;
  date: string;
  type: IssueType;
  severity: "error" | "warning";
  // 유형마다 다르다. spike: {change, prev_date}, ohlc_invalid·non_positive: {open, high, low, close}, stale: {lag_days}
  // minute_mismatch: {필드명: {minute, daily}}, minute_gap: {start, end, minutes, count, all_assets}
  detail: Record<string, string | number | boolean | MismatchField>;
  detected_at: string;
  resolved_at: string | null;
  note: string;
};

export type IssueFilters = {
  symbol?: string;
  type?: string;
  severity?: string;
  resolved?: "true" | "false";
};

/** 운영 콘솔 칸 상태. 한 칸에 여러 문제가 있으면 가장 심한 것(앞쪽)이 온다. */
export type DayStatus = "error" | "no_minutes" | "not_aggregated" | "warning" | "ok";

export type DayCell = {
  date: string;
  status: DayStatus;
  minute_count: number;
  aggregated_minutes: number | null;
  daily_final: boolean;
  open_errors: number;
  open_warnings: number;
  reprocess_runs: number;
};

export type DayMatrix = {
  start: string;
  end: string;
  rows: { symbol: string; cells: DayCell[] }[];
};

export type DayValues = {
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  value: string;
  minute_count?: number;
  is_final?: boolean;
};

export type ReprocessTable = { inserted: number; updated: number; deleted: number; dates: Record<string, Record<string, number>> };

export type ReprocessRun = {
  id: number;
  symbol: string;
  target: "minutes" | "aggregates" | "daily";
  start_date: string;
  end_date: string;
  dry_run: boolean;
  reason: string;
  requested_by: string;
  status: "running" | "success" | "failed" | "rejected";
  rows_before: number | null;
  rows_after: number | null;
  changed_rows: number | null;
  // 테이블 이름(minutecandle·hourlybar·dailyagg·dailycandle) → 추가·변경·삭제 수, "checks" → 재검증 결과
  diff: Record<string, ReprocessTable | Record<string, unknown>>;
  started_at: string;
  finished_at: string | null;
  error_message: string;
};

export type DayDetail = {
  symbol: string;
  date: string;
  minute_count: number;
  gaps: { start: string; end: string; minutes: number }[];
  hourly: { hour: string; minute_count: number }[];
  daily_agg: DayValues | null;
  daily_candle: DayValues | null;
  issues: IntegrityIssue[];
  reprocess_runs: ReprocessRun[];
};

export type SlowQuery = { at: string; path: string; ms: number; sql: string };

export type BacktestParams = {
  symbol: string;
  strategy: "ma_cross" | "buy_and_hold";
  start: string;
  end: string;
  short?: number;
  long?: number;
  fee?: number;
};

export type Metrics = {
  total_return: number;
  cagr: number;
  max_drawdown: number;
  sharpe: number;
  trades: number;
  win_rate: number;
  exposure: number;
  days: number;
};

export type EquityPoint = {
  date: string;
  equity: number;
  benchmark: number;
  drawdown: number;
};

export type BacktestResult = {
  id: number;
  params: BacktestParams;
  data_version: string;
  metrics: Metrics;
  benchmark: Metrics;
  equity_curve: EquityPoint[];
  created_at: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// 캐시한 API 응답에 붙이는 태그. 백엔드가 수집을 마치면 /api/revalidate로 이 태그를 바로 만료시킨다.
export const API_CACHE_TAG = "api";

// 시간 기반 캐시는 만료 뒤 첫 요청에 옛 값을 주고 뒤에서 갱신한다(stale-while-revalidate).
// 운영 상태처럼 "지금" 값이 중요한 화면은 fresh=true로 캐시를 쓰지 않는다.
function cacheOption(fresh: boolean, revalidate = REVALIDATE_SECONDS): RequestInit {
  return fresh ? { cache: "no-store" } : { next: { revalidate, tags: [API_CACHE_TAG] } };
}

async function getJSON<T>(path: string, fresh = false): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, cacheOption(fresh));
  if (!res.ok) throw new ApiError(res.status, `${path} 응답 ${res.status}`);
  return res.json() as Promise<T>;
}

/** 서버 상태. 장애면 API가 503과 함께 같은 형식을 주므로 그대로 읽는다. 응답이 없으면 null. */
export async function getHealth(fresh = false): Promise<Health | null> {
  try {
    const res = await fetch(`${API_BASE}/api/health/`, cacheOption(fresh, 60));
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

export function getIntegritySummary(fresh = false) {
  return getJSON<IntegritySummary>("/api/integrity/summary/", fresh);
}

/** 수집 실행 기록(최신순, 최대 100개). kind를 주면 일봉 수집 또는 분봉 파이프라인만. */
export async function getCollectionRuns(fresh = false, kind?: CollectionRun["kind"]) {
  const query = kind ? `?kind=${kind}` : "";
  const page = await getJSON<{ results: CollectionRun[] }>(`/api/collection-runs/${query}`, fresh);
  return page.results;
}

// 운영 콘솔은 "지금" 상태를 보는 화면이라 캐시하지 않는다.

/** 활성 종목 × 최근 days일(마감된 UTC 날) 상태 표 */
export function getOpsDays(days = 30) {
  return getJSON<DayMatrix>(`/api/ops/days/?days=${days}`, true);
}

/** 한 종목·하루 상세 */
export function getOpsDay(symbol: string, date: string) {
  return getJSON<DayDetail>(`/api/ops/days/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/`, true);
}

/** 재처리 이력(최신순, 최대 100개) */
export async function getReprocessRuns() {
  const page = await getJSON<{ results: ReprocessRun[] }>("/api/reprocess/", true);
  return page.results;
}

/** 최근 느린 쿼리(최신순, 최대 50개) */
export function getSlowQueries() {
  return getJSON<SlowQuery[]>("/api/ops/slow-queries/", true);
}

/** 무결성 이슈(최신 날짜순, 최대 100개)와 조건에 맞는 전체 개수. 빈 필터는 보내지 않는다. */
export async function getIntegrityIssues(filters: IssueFilters) {
  const query = new URLSearchParams(
    Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
  return getJSON<{ count: number; results: IntegrityIssue[] }>(`/api/integrity/issues/?${query}`);
}

/** 한 종목의 일봉(날짜 오름차순). from이 없으면 상장일부터 전부(최대 5000개). */
export async function getCandles(symbol: string, from?: string) {
  const query = new URLSearchParams({ symbol, page_size: "5000" });
  if (from) query.set("from", from);
  const page = await getJSON<{ results: Candle[] }>(`/api/candles/?${query}`);
  return page.results;
}

/** 브라우저에서 직접 호출한다(사용자 IP별로 throttle이 적용되도록). */
export async function runBacktest(params: BacktestParams): Promise<BacktestResult> {
  const res = await fetch(`${API_BASE}/api/backtests/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, body));
  return body as BacktestResult;
}

// 400은 {필드: [메시지]}, 422·429는 {detail: 메시지} 형식이다.
function errorMessage(status: number, body: Record<string, unknown>): string {
  if (typeof body.detail === "string") return body.detail;
  const messages = Object.values(body).flat().filter((m) => typeof m === "string");
  if (messages.length > 0) return messages.join(" ");
  return `요청 실패 (${status})`;
}
