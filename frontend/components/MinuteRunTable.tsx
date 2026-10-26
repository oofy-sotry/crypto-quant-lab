import { RUN_STATE_BG } from "@/components/RunTable";
import type { CollectionRun } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { RUN_STATE_TEXT, runSeconds, runState, TRIGGER_TEXT } from "@/lib/runs";

type Detail = {
  range?: [string, string];
  timings?: Record<string, number>;
  deleted_minutes?: number;
};

function seconds(value: number | undefined): string {
  return value === undefined ? "-" : `${value.toFixed(1)}초`;
}

/** 분봉 파이프라인 실행 기록(최신순): 단계별 소요 시간과 보관 기간 정리로 지운 분봉 수 */
export function MinuteRunTable({ runs, now }: { runs: CollectionRun[]; now: number }) {
  if (runs.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">분봉 파이프라인 실행 기록이 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">시작</th>
            <th className="px-2 py-2 font-normal">종류</th>
            <th className="px-2 py-2 font-normal">상태</th>
            <th className="px-2 py-2 font-normal">대상 날짜(UTC)</th>
            <th className="px-2 py-2 text-right font-normal">저장</th>
            <th className="px-2 py-2 text-right font-normal">수집·집계</th>
            <th className="px-2 py-2 text-right font-normal">검사</th>
            <th className="px-2 py-2 text-right font-normal">정리</th>
            <th className="px-2 py-2 text-right font-normal">전체</th>
            <th className="px-2 py-2 text-right font-normal">지운 분봉</th>
            <th className="py-2 pl-2 font-normal">오류</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const state = runState(run, now);
            const detail = run.detail as Detail;
            const total = runSeconds(run);
            return (
              <tr key={run.id} className="border-b border-border align-top last:border-0">
                <td className="num py-2 pr-2">{formatDateTime(run.started_at)}</td>
                <td className={`px-2 py-2 ${run.trigger === "cron" ? "" : "text-muted"}`}>{TRIGGER_TEXT[run.trigger]}</td>
                <td className="px-2 py-2">
                  <span className={`mr-1.5 inline-block size-2 rounded-full ${RUN_STATE_BG[state]}`} aria-hidden />
                  {RUN_STATE_TEXT[state]}
                </td>
                <td className="num px-2 py-2">{detail.range ? `${detail.range[0]} ~ ${detail.range[1]}` : "-"}</td>
                <td className="num px-2 py-2 text-right">{run.upserted_count.toLocaleString("ko-KR")}행</td>
                <td className="num px-2 py-2 text-right">{seconds(detail.timings?.collect_aggregate_s)}</td>
                <td className="num px-2 py-2 text-right">{seconds(detail.timings?.checks_s)}</td>
                <td className="num px-2 py-2 text-right">{seconds(detail.timings?.retention_s)}</td>
                <td className="num px-2 py-2 text-right">{total === null ? "-" : `${total.toFixed(1)}초`}</td>
                <td className="num px-2 py-2 text-right">{(detail.deleted_minutes ?? 0).toLocaleString("ko-KR")}행</td>
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
