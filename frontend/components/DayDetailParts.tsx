import type { DayDetail, DayValues } from "@/lib/api";

/** 시간대별(UTC 0~23시) 집계에 들어간 분봉 수. 60이면 꽉 참, 0이면 집계 없음. */
export function HourlyBars({ hourly }: { hourly: DayDetail["hourly"] }) {
  return (
    <div>
      <div className="flex h-24 items-end gap-0.5" role="img" aria-label="시간대별 분봉 수">
        {hourly.map((h) => {
          const hour = new Date(h.hour).getUTCHours();
          const ratio = Math.min(h.minute_count / 60, 1);
          return (
            <div
              key={h.hour}
              title={`${hour}시(UTC) 분봉 ${h.minute_count}개`}
              className={`flex-1 rounded-t-sm ${h.minute_count === 0 ? "bg-error/40" : ratio < 0.5 ? "bg-warn" : "bg-accent"}`}
              style={{ height: `${Math.max(ratio, 0.04) * 100}%` }}
            />
          );
        })}
      </div>
      <div className="num mt-1 flex justify-between text-xs text-muted">
        <span>0시</span>
        <span>6시</span>
        <span>12시</span>
        <span>18시</span>
        <span>23시 (UTC)</span>
      </div>
    </div>
  );
}

const FIELDS: { key: keyof DayValues; label: string }[] = [
  { key: "open", label: "시가" },
  { key: "high", label: "고가" },
  { key: "low", label: "저가" },
  { key: "close", label: "종가" },
  { key: "volume", label: "거래량" },
  { key: "value", label: "거래대금" },
];

/** 분봉으로 만든 일봉 vs 업비트 일봉. 값은 문자열(Decimal) 그대로 비교·표시한다. */
export function DayCompare({ agg, candle }: { agg: DayValues | null; candle: DayValues | null }) {
  if (!agg && !candle) {
    return <p className="py-4 text-center text-sm text-muted">이 날은 집계도 업비트 일봉도 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">항목</th>
            <th className="px-2 py-2 text-right font-normal">분봉 집계</th>
            <th className="px-2 py-2 text-right font-normal">업비트 일봉{candle && !candle.is_final && " (마감 전)"}</th>
            <th className="py-2 pl-2 font-normal" />
          </tr>
        </thead>
        <tbody>
          {FIELDS.map(({ key, label }) => {
            const a = agg?.[key];
            const c = candle?.[key];
            // 문자열 자릿수가 달라도 같은 값이면 같다고 본다(100 vs 100.00000000).
            const differs = a !== undefined && c !== undefined && Number(a) !== Number(c);
            return (
              <tr key={key} className="border-b border-border last:border-0">
                <td className="py-2 pr-2 text-muted">{label}</td>
                <td className="num px-2 py-2 text-right">{a ?? "-"}</td>
                <td className="num px-2 py-2 text-right">{c ?? "-"}</td>
                <td className={`py-2 pl-2 text-xs ${differs ? "text-error" : "text-muted"}`}>{differs ? "다름" : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
