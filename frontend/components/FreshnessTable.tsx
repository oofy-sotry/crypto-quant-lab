import type { AssetSummary } from "@/lib/api";
import { daysBetween, expectedLastFinalDate } from "@/lib/runs";

/**
 * 종목별 최신 확정일과 밀린 일수. 확정돼 있어야 할 날짜(어제, 업비트 기준 KST 09시 경계)보다
 * 마지막 확정 봉이 며칠 늦은지 보여 준다. 수집이 일부 종목만 실패해도 여기서 드러난다.
 */
export function FreshnessTable({ assets, now }: { assets: AssetSummary[]; now: number }) {
  const expected = expectedLastFinalDate(now);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">종목</th>
            <th className="px-2 py-2 font-normal">최신 확정일</th>
            <th className="py-2 pl-2 text-right font-normal">밀린 일수</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => {
            const lag = a.last_final_date ? daysBetween(a.last_final_date, expected) : null;
            return (
              <tr key={a.symbol} className="border-b border-border last:border-0">
                <td className="py-2 pr-2">
                  {a.name} <span className="text-xs text-muted">{a.symbol}</span>
                </td>
                <td className="num px-2 py-2">{a.last_final_date ?? "-"}</td>
                <td className="num py-2 pl-2 text-right">
                  {lag === null ? (
                    <span className="text-error">데이터 없음</span>
                  ) : lag <= 0 ? (
                    <span className="text-ok">최신</span>
                  ) : (
                    <span className={lag >= 2 ? "text-error" : "text-warn"}>{lag}일</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">기준: {expected}까지 확정돼 있어야 함 (업비트 일봉은 KST 09:00에 마감)</p>
    </div>
  );
}
