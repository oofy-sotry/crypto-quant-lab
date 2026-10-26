import Link from "next/link";
import type { ReprocessRun, ReprocessTableDiff } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { REPROCESS_STATE_BG, REPROCESS_STATE_TEXT, reprocessState, TABLE_TEXT, TARGET_TEXT } from "@/lib/ops";

/** diff에서 바뀐 테이블만 "분봉 +60 ~0 -0" 형태로 뽑는다(원본 → 집계 순, 재검증 결과 checks는 뺌). */
function diffSummary(run: ReprocessRun): string[] {
  return Object.keys(TABLE_TEXT)
    .filter((table) => table in run.diff)
    .map((table) => [table, run.diff[table] as ReprocessTableDiff] as const)
    .filter(([, t]) => t.inserted + t.updated + t.deleted > 0)
    .map(([table, t]) => `${TABLE_TEXT[table]} +${t.inserted} ~${t.updated} -${t.deleted}`);
}

/** 재처리 이력 표(최신순). dry-run은 "미리 보기"로 표시하고, 바뀐(바뀔) 행을 테이블별로 보여 준다. */
export function ReprocessTable({ runs, now }: { runs: ReprocessRun[]; now: number }) {
  if (runs.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">재처리 이력이 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">시작</th>
            <th className="px-2 py-2 font-normal">종목</th>
            <th className="px-2 py-2 font-normal">대상</th>
            <th className="px-2 py-2 font-normal">기간(UTC)</th>
            <th className="px-2 py-2 font-normal">방식</th>
            <th className="px-2 py-2 font-normal">상태</th>
            <th className="px-2 py-2 text-right font-normal">바뀐 행</th>
            <th className="px-2 py-2 font-normal">테이블별 (+추가 ~변경 -삭제)</th>
            <th className="py-2 pl-2 font-normal">요청자 · 사유</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const state = reprocessState(run, now);
            return (
              <tr key={run.id} className="border-b border-border align-top last:border-0">
                <td className="num py-2 pr-2">{formatDateTime(run.started_at)}</td>
                <td className="px-2 py-2">
                  <Link href={`/ops/${run.symbol}/${run.start_date}`} className="text-accent hover:underline">
                    {run.symbol.replace("KRW-", "")}
                  </Link>
                </td>
                <td className="px-2 py-2">{TARGET_TEXT[run.target]}</td>
                <td className="num px-2 py-2">
                  {run.start_date === run.end_date ? run.start_date : `${run.start_date} ~ ${run.end_date}`}
                </td>
                <td className={`px-2 py-2 ${run.dry_run ? "text-muted" : "font-medium"}`}>
                  {run.dry_run ? "미리 보기" : "반영"}
                </td>
                <td className="px-2 py-2">
                  <span className={`mr-1.5 inline-block size-2 rounded-full ${REPROCESS_STATE_BG[state]}`} aria-hidden />
                  {REPROCESS_STATE_TEXT[state]}
                </td>
                <td className="num px-2 py-2 text-right">{run.changed_rows?.toLocaleString("ko-KR") ?? "-"}</td>
                <td className="num px-2 py-2 text-xs">
                  {run.error_message ? (
                    <span className="text-error">{run.error_message}</span>
                  ) : run.status === "success" ? (
                    diffSummary(run).join(" · ") || <span className="text-muted">바뀐 행 없음</span>
                  ) : (
                    "-"
                  )}
                </td>
                <td className="max-w-72 truncate py-2 pl-2 text-xs text-muted" title={run.reason}>
                  {run.requested_by} · {run.reason}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
