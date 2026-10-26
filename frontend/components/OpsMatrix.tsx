import Link from "next/link";
import type { DayCell, DayMatrix, DayStatus } from "@/lib/api";
import { DAY_STATUS_BG, DAY_STATUS_HELP, DAY_STATUS_TEXT } from "@/lib/ops";

const STATUS_ORDER: DayStatus[] = ["error", "no_minutes", "not_aggregated", "warning", "ok"];

function cellTitle(symbol: string, cell: DayCell): string {
  const parts = [
    `${symbol} ${cell.date} (UTC)`,
    DAY_STATUS_TEXT[cell.status],
    `분봉 ${cell.minute_count.toLocaleString("ko-KR")}개`,
    cell.aggregated_minutes === null ? "집계 없음" : `집계 ${cell.aggregated_minutes.toLocaleString("ko-KR")}개`,
  ];
  if (cell.open_errors) parts.push(`오류 ${cell.open_errors}`);
  if (cell.open_warnings) parts.push(`경고 ${cell.open_warnings}`);
  if (cell.reprocess_runs) parts.push(`재처리 ${cell.reprocess_runs}회`);
  return parts.join(" · ");
}

/** 종목×날짜 상태 표. 칸을 누르면 그날 상세로 간다. 재처리 이력이 있는 칸은 테두리를 두른다. */
export function OpsMatrix({ matrix }: { matrix: DayMatrix }) {
  const dates = matrix.rows[0]?.cells.map((c) => c.date) ?? [];
  const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<DayStatus, number>;
  for (const row of matrix.rows) for (const cell of row.cells) counts[cell.status] += 1;

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 bg-panel pr-2 text-left font-normal text-muted">종목</th>
              {dates.map((d) => (
                // 칸 폭을 고정하려고 일(日)만 쓴다. 기간은 제목 옆에, 월이 바뀌는 날은 강조색으로 표시한다.
                <th key={d} className={`num w-5 font-normal ${d.endsWith("-01") ? "text-accent" : "text-muted"}`} title={d}>
                  {Number(d.slice(8))}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.rows.map((row) => (
              <tr key={row.symbol}>
                <th className="sticky left-0 bg-panel pr-2 text-left font-medium whitespace-nowrap">
                  {row.symbol.replace("KRW-", "")}
                </th>
                {row.cells.map((cell) => (
                  <td key={cell.date} className="p-0">
                    <Link
                      href={`/ops/${row.symbol}/${cell.date}`}
                      title={cellTitle(row.symbol, cell)}
                      aria-label={cellTitle(row.symbol, cell)}
                      className={`block size-5 rounded-sm ${DAY_STATUS_BG[cell.status]} ${
                        cell.reprocess_runs ? "ring-2 ring-foreground/60 ring-inset" : ""
                      } hover:opacity-70`}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {STATUS_ORDER.map((s) => (
          <li key={s} className="flex items-center gap-1.5" title={DAY_STATUS_HELP[s]}>
            <span className={`inline-block size-3 rounded-sm ${DAY_STATUS_BG[s]}`} aria-hidden />
            {DAY_STATUS_TEXT[s]} <span className="num">{counts[s]}</span>
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm ring-2 ring-foreground/60 ring-inset" aria-hidden />
          재처리 이력 있음
        </li>
      </ul>
    </div>
  );
}
