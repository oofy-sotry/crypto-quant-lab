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
  trigger: "cron" | "beat" | "manual" | "backfill";
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  assets_count: number;
  upserted_count: number;
  error_message: string;
};

export type IntegritySummary = {
  assets: AssetSummary[];
  last_run: CollectionRun | null;
};

export type IssueType = "missing" | "ohlc_invalid" | "non_positive" | "zero_volume" | "spike" | "stale";

export type IntegrityIssue = {
  id: number;
  symbol: string;
  date: string;
  type: IssueType;
  severity: "error" | "warning";
  // 유형마다 다르다. spike: {change, prev_date}, ohlc_invalid·non_positive: {open, high, low, close}, stale: {lag_days}
  detail: Record<string, string | number>;
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

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { next: { revalidate: REVALIDATE_SECONDS } });
  if (!res.ok) throw new ApiError(res.status, `${path} 응답 ${res.status}`);
  return res.json() as Promise<T>;
}

/** 서버 상태. 장애면 API가 503과 함께 같은 형식을 주므로 그대로 읽는다. 응답이 없으면 null. */
export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API_BASE}/api/health/`, { next: { revalidate: 60 } });
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

export function getIntegritySummary() {
  return getJSON<IntegritySummary>("/api/integrity/summary/");
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
