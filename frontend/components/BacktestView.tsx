"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RatioChart, type RatioSeries } from "@/components/charts/RatioChart";
import { MetricsCompare } from "@/components/MetricsCompare";
import { runBacktest, type AssetSummary, type BacktestParams, type BacktestResult } from "@/lib/api";
import { drawdowns } from "@/lib/indicators";

const DEFAULT_START = "2021-01-01";

type Form = {
  symbol: string;
  strategy: BacktestParams["strategy"];
  short: string;
  long: string;
  start: string;
  end: string;
  feePercent: string;
};

/** 입력 값을 API 요청으로 바꾼다. 화면에서 먼저 막을 수 있는 오류는 메시지로 돌려준다. */
function toParams(f: Form): BacktestParams | string {
  if (!f.start || !f.end || f.start >= f.end) return "시작일은 종료일보다 앞이어야 합니다.";
  const fee = Number(f.feePercent) / 100;
  if (!(fee >= 0 && fee <= 0.01)) return "수수료는 0~1% 사이로 입력해 주세요.";
  const params: BacktestParams = { symbol: f.symbol, strategy: f.strategy, start: f.start, end: f.end, fee };
  if (f.strategy === "ma_cross") {
    const short = Number(f.short);
    const long = Number(f.long);
    if (!Number.isInteger(short) || !Number.isInteger(long) || short < 1 || long < 2) {
      return "이동평균 기간은 자연수로 입력해 주세요.";
    }
    if (short >= long) return "단기 이동평균은 장기보다 짧아야 합니다.";
    Object.assign(params, { short, long });
  }
  return params;
}

export function BacktestView({ assets }: { assets: AssetSummary[] }) {
  const first = assets.find((a) => a.symbol === "KRW-BTC") ?? assets[0];
  const [form, setForm] = useState<Form>({
    symbol: first.symbol,
    strategy: "ma_cross",
    short: "20",
    long: "60",
    start: DEFAULT_START,
    end: first.last_final_date ?? "",
    feePercent: "0.05",
  });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  async function submit(f: Form) {
    const params = toParams(f);
    if (typeof params === "string") {
      setError(params);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setResult(await runBacktest(params));
    } catch (e) {
      setError(e instanceof Error ? e.message : "백테스트를 실행하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  // 화면에 들어오면 기본 설정으로 한 번 돌려서 빈 화면 대신 예시 결과를 보여 준다.
  const ranOnce = useRef(false);
  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;
    void submit(form);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만 실행
  }, []);

  const asset = assets.find((a) => a.symbol === form.symbol);
  const strategyLabel = result?.params.strategy === "ma_cross" ? `MA 교차 (${result.params.short}/${result.params.long})` : "매수 후 보유";

  const charts = useMemo(() => {
    if (!result) return null;
    const curve = result.equity_curve;
    const benchDd = drawdowns(curve.map((p) => p.benchmark));
    const returns: RatioSeries[] = [
      { label: strategyLabel, color: "accent", data: curve.map((p) => ({ time: p.date, value: p.equity - 1 })) },
      { label: "매수 후 보유", color: "muted", data: curve.map((p) => ({ time: p.date, value: p.benchmark - 1 })) },
    ];
    const dd: RatioSeries[] = [
      { label: strategyLabel, color: "accent", data: curve.map((p) => ({ time: p.date, value: p.drawdown })) },
      { label: "매수 후 보유", color: "muted", data: curve.map((p, i) => ({ time: p.date, value: benchDd[i] })) },
    ];
    return { returns, dd };
  }, [result, strategyLabel]);

  const input = "w-full rounded-md border border-border bg-background px-2.5 py-1.5";

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <form
        className="flex h-fit flex-col gap-3 rounded-xl border border-border bg-panel p-4 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(form);
        }}
      >
        <h2 className="font-semibold">설정</h2>
        <label className="flex flex-col gap-1">
          <span className="text-muted">종목</span>
          <select
            className={input}
            value={form.symbol}
            onChange={(e) => {
              const next = assets.find((a) => a.symbol === e.target.value);
              set({ symbol: e.target.value, end: next?.last_final_date ?? form.end });
            }}
          >
            {assets.map((a) => (
              <option key={a.symbol} value={a.symbol}>
                {a.name} ({a.symbol})
              </option>
            ))}
          </select>
        </label>

        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1 text-muted">전략</legend>
          <div className="grid grid-cols-2 gap-1 rounded-md bg-background p-1">
            {(
              [
                ["ma_cross", "이동평균 교차"],
                ["buy_and_hold", "매수 후 보유"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={form.strategy === value}
                onClick={() => set({ strategy: value })}
                className={`rounded px-2 py-1.5 ${form.strategy === value ? "bg-panel font-semibold shadow-sm" : "text-muted"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        {form.strategy === "ma_cross" && (
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-muted">단기 MA(일)</span>
              <input className={`${input} num`} type="number" min={1} max={200} value={form.short} onChange={(e) => set({ short: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-muted">장기 MA(일)</span>
              <input className={`${input} num`} type="number" min={2} max={400} value={form.long} onChange={(e) => set({ long: e.target.value })} />
            </label>
            <p className="col-span-2 text-xs text-muted">단기선이 장기선 위에 있으면 보유, 아래면 현금. 신호는 다음 날부터 적용됩니다.</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-muted">시작일</span>
            <input className={`${input} num`} type="date" min={asset?.first_date ?? undefined} max={asset?.last_final_date ?? undefined} value={form.start} onChange={(e) => set({ start: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted">종료일</span>
            <input className={`${input} num`} type="date" min={asset?.first_date ?? undefined} max={asset?.last_final_date ?? undefined} value={form.end} onChange={(e) => set({ end: e.target.value })} />
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-muted">수수료(%, 매매할 때마다)</span>
          <input className={`${input} num`} type="number" step="0.01" min={0} max={1} value={form.feePercent} onChange={(e) => set({ feePercent: e.target.value })} />
        </label>

        <button
          type="submit"
          disabled={loading}
          className="mt-1 rounded-md bg-accent px-3 py-2 font-semibold text-white disabled:opacity-60"
        >
          {loading ? "계산 중…" : "백테스트 실행"}
        </button>
        {error && (
          <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-error">
            {error}
          </p>
        )}
      </form>

      <div className="flex min-w-0 flex-col gap-4">
        {!result && !error && (
          <div className="rounded-xl border border-border bg-panel p-6 text-sm text-muted">결과를 계산하고 있습니다…</div>
        )}
        {result && charts && (
          <>
            <section className={`rounded-xl border border-border bg-panel p-4 transition-opacity ${loading ? "opacity-50" : ""}`}>
              <h2 className="font-semibold">누적 수익률</h2>
              <p className="mb-3 text-xs text-muted">
                {result.params.symbol} · {result.params.start} ~ {result.params.end} · 수수료 {((result.params.fee ?? 0) * 100).toFixed(2)}%
              </p>
              <RatioChart series={charts.returns} />
            </section>
            <section className={`rounded-xl border border-border bg-panel p-4 transition-opacity ${loading ? "opacity-50" : ""}`}>
              <h2 className="mb-3 font-semibold">고점 대비 하락률 (드로다운)</h2>
              <RatioChart series={charts.dd} kind="area" height={220} />
            </section>
            <section className="rounded-xl border border-border bg-panel p-4">
              <h2 className="mb-2 font-semibold">성과 지표</h2>
              <MetricsCompare strategy={result.metrics} benchmark={result.benchmark} strategyLabel={strategyLabel} />
              <p className="mt-3 text-xs text-muted">
                한 종목·한 기간·한 설정의 결과입니다. 설정을 바꿔 가며 가장 좋은 값을 고르면 과거에만 맞춘 결과(과최적화)가 될 수 있습니다.
              </p>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
