import type { Metrics } from "@/lib/api";
import { formatNumber, formatPercent } from "@/lib/format";

type Row = {
  label: string;
  hint: string;
  value: (m: Metrics) => number;
  format: (v: number) => string;
  /** 클수록 좋은 지표인지 (MDD는 0에 가까울수록 = 클수록 좋음) */
  higherIsBetter: boolean | null;
};

const ROWS: Row[] = [
  { label: "총수익률", hint: "기간 전체 수익", value: (m) => m.total_return, format: (v) => formatPercent(v, true), higherIsBetter: true },
  { label: "연평균 수익률(CAGR)", hint: "1년 평균으로 환산", value: (m) => m.cagr, format: (v) => formatPercent(v, true), higherIsBetter: true },
  { label: "최대 낙폭(MDD)", hint: "고점 대비 가장 크게 떨어진 폭", value: (m) => m.max_drawdown, format: (v) => formatPercent(v), higherIsBetter: true },
  { label: "샤프 지수", hint: "변동성 대비 수익 (365일 기준)", value: (m) => m.sharpe, format: (v) => formatNumber(v), higherIsBetter: true },
  { label: "거래 횟수", hint: "매수·매도 전환 횟수", value: (m) => m.trades, format: (v) => String(v), higherIsBetter: null },
  { label: "승률", hint: "이익으로 끝난 거래 비율", value: (m) => m.win_rate, format: (v) => formatPercent(v), higherIsBetter: null },
  { label: "보유 비율", hint: "기간 중 코인을 들고 있던 비율", value: (m) => m.exposure, format: (v) => formatPercent(v), higherIsBetter: null },
];

/** 전략 vs 매수 후 보유(Buy&Hold) 지표 비교표. 더 나은 쪽을 굵게 표시한다. */
export function MetricsCompare({ strategy, benchmark, strategyLabel }: { strategy: Metrics; benchmark: Metrics; strategyLabel: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">지표</th>
            <th className="px-2 py-2 text-right font-normal">{strategyLabel}</th>
            <th className="py-2 pl-2 text-right font-normal">매수 후 보유</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const a = row.value(strategy);
            const b = row.value(benchmark);
            const better = row.higherIsBetter === null || a === b ? null : a > b === row.higherIsBetter ? "a" : "b";
            return (
              <tr key={row.label} className="border-b border-border last:border-0">
                <td className="py-2 pr-2">
                  <div>{row.label}</div>
                  <div className="text-xs text-muted">{row.hint}</div>
                </td>
                <td className={`num px-2 py-2 text-right ${better === "a" ? "font-semibold" : ""}`}>{row.format(a)}</td>
                <td className={`num py-2 pl-2 text-right ${better === "b" ? "font-semibold" : ""}`}>{row.format(b)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
