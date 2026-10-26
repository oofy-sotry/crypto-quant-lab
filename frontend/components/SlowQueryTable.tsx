import type { SlowQuery } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/** 최근 느린 쿼리(최신순). SQL은 파라미터 값 없이 모양만 온다. */
export function SlowQueryTable({ queries }: { queries: SlowQuery[] }) {
  if (queries.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">최근 7일 동안 기준을 넘은 쿼리가 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">시각</th>
            <th className="px-2 py-2 font-normal">요청 경로</th>
            <th className="px-2 py-2 text-right font-normal">걸린 시간</th>
            <th className="py-2 pl-2 font-normal">SQL</th>
          </tr>
        </thead>
        <tbody>
          {queries.map((q, i) => (
            <tr key={`${q.at}-${i}`} className="border-b border-border align-top last:border-0">
              <td className="num py-2 pr-2">{formatDateTime(q.at)}</td>
              <td className="px-2 py-2 font-mono text-xs">{q.path}</td>
              <td className="num px-2 py-2 text-right text-warn">{q.ms.toLocaleString("ko-KR")}ms</td>
              <td className="max-w-md truncate py-2 pl-2 font-mono text-xs text-muted" title={q.sql}>
                {q.sql}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
