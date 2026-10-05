import type { CollectionRun } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { RUN_STATE_TEXT, runSeconds, runState, TRIGGER_TEXT, type RunState } from "@/lib/runs";

export const RUN_STATE_BG: Record<RunState, string> = {
  success: "bg-ok",
  partial: "bg-warn",
  failed: "bg-error",
  stalled: "bg-error",
  running: "bg-accent",
};

/** 수집 실행 기록 표(최신순). 자동(Cron)·수동·백필을 구분하고, 실패하면 오류 메시지를 보여 준다. */
export function RunTable({ runs, now }: { runs: CollectionRun[]; now: number }) {
  if (runs.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">수집 기록이 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">시작</th>
            <th className="px-2 py-2 font-normal">종류</th>
            <th className="px-2 py-2 font-normal">상태</th>
            <th className="px-2 py-2 text-right font-normal">소요</th>
            <th className="px-2 py-2 text-right font-normal">종목</th>
            <th className="px-2 py-2 text-right font-normal">저장</th>
            <th className="py-2 pl-2 font-normal">오류</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const state = runState(run, now);
            const seconds = runSeconds(run);
            return (
              <tr key={run.id} className="border-b border-border align-top last:border-0">
                <td className="num py-2 pr-2">{formatDateTime(run.started_at)}</td>
                <td className={`px-2 py-2 ${run.trigger === "cron" ? "" : "text-muted"}`}>{TRIGGER_TEXT[run.trigger]}</td>
                <td className="px-2 py-2">
                  <span className={`mr-1.5 inline-block size-2 rounded-full ${RUN_STATE_BG[state]}`} aria-hidden />
                  {RUN_STATE_TEXT[state]}
                </td>
                <td className="num px-2 py-2 text-right">{seconds === null ? "-" : `${seconds.toFixed(1)}초`}</td>
                <td className="num px-2 py-2 text-right">{run.assets_count}</td>
                <td className="num px-2 py-2 text-right">{run.upserted_count.toLocaleString("ko-KR")}건</td>
                <td className="max-w-72 truncate py-2 pl-2 text-xs text-error" title={run.error_message}>
                  {run.error_message}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
