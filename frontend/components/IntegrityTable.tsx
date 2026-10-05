import Link from "next/link";
import type { AssetSummary } from "@/lib/api";

function Count({ value, tone }: { value: number; tone: "error" | "warn" }) {
  if (value === 0) return <span className="text-muted">0</span>;
  return <span className={`font-semibold ${tone === "error" ? "text-error" : "text-warn"}`}>{value}</span>;
}

/** 종목별 데이터 범위와 열린(해결 안 된) 이슈 수. 종목을 누르면 그 종목 이슈만 본다. */
export function IntegrityTable({ assets }: { assets: AssetSummary[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">종목</th>
            <th className="px-2 py-2 font-normal">데이터 범위 (확정 봉)</th>
            <th className="px-2 py-2 text-right font-normal">일봉 수</th>
            <th className="px-2 py-2 text-right font-normal">열린 오류</th>
            <th className="py-2 pl-2 text-right font-normal">열린 경고</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.symbol} className="border-b border-border last:border-0">
              <td className="py-2 pr-2">
                <Link href={`/integrity?symbol=${a.symbol}`} className="hover:text-accent">
                  <div className="font-medium">{a.name}</div>
                  <div className="text-xs text-muted">{a.symbol}</div>
                </Link>
              </td>
              <td className="num px-2 py-2 whitespace-nowrap">
                {a.first_date ?? "-"} ~ {a.last_final_date ?? "-"}
              </td>
              <td className="num px-2 py-2 text-right">{a.candle_count.toLocaleString("ko-KR")}</td>
              <td className="num px-2 py-2 text-right">
                <Count value={a.open_errors} tone="error" />
              </td>
              <td className="num py-2 pl-2 text-right">
                <Count value={a.open_warnings} tone="warn" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
