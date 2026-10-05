import type { CollectionRun } from "@/lib/api";
import { RUN_STATE_TEXT, runState, TRIGGER_TEXT, kstDate } from "@/lib/runs";
import { RUN_STATE_BG } from "@/components/RunTable";

const DAYS = 14;
const MAX_BAR_PX = 64;

/** 오늘(KST)부터 거꾸로 days일의 "YYYY-MM-DD" (오래된 날 → 오늘 순) */
function lastDays(now: number, days: number): string[] {
  return Array.from({ length: days }, (_, i) => kstDate(now - (days - 1 - i) * 86_400_000));
}

/**
 * 최근 14일, 날짜별 수집 막대. 높이 = 그날 저장 건수, 색 = 그날 마지막 실행의 상태.
 * 수집이 없던 날은 빈 칸으로 남아서, Cron이 아예 안 돈 날(오류가 없어 Sentry로는 모르는 경우)이 눈에 띈다.
 * 백필(수천 건)은 높이를 다른 날과 맞추려고 최대 높이로 자른다.
 */
export function DailyRunBars({ runs, now }: { runs: CollectionRun[]; now: number }) {
  const byDay = new Map<string, CollectionRun[]>();
  for (const run of runs) {
    const day = kstDate(run.started_at);
    byDay.set(day, [...(byDay.get(day) ?? []), run]);
  }
  // 프로젝트 시작(첫 수집) 전 날짜는 "수집 없음"이 아니라 그냥 그리지 않는다.
  const firstDay = runs.length > 0 ? kstDate(runs[runs.length - 1].started_at) : null;
  const days = lastDays(now, DAYS).filter((d) => firstDay !== null && d >= firstDay);

  const regular = runs.filter((r) => r.trigger !== "backfill").map((r) => r.upserted_count);
  const scale = Math.max(1, ...regular);
  // Cron은 09시대에 돈다. 오늘 10시 전이면 아직 안 돈 게 정상이고, 그 뒤에도 없으면 빠진 날이다.
  const today = kstDate(now);
  const kstHour = Number(new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Seoul", hour: "numeric", hourCycle: "h23" }).format(now));
  const pendingToday = kstHour < 10;

  return (
    <div className="flex items-end gap-1.5 overflow-x-auto pb-1">
      {days.map((day) => {
        // API가 최신순으로 주므로 첫 번째가 그날 마지막 실행이다.
        const dayRuns = byDay.get(day) ?? [];
        const last = dayRuns[0];
        const saved = dayRuns.reduce((n, r) => n + r.upserted_count, 0);
        const height = last ? Math.max(6, Math.min(MAX_BAR_PX, (saved / scale) * (MAX_BAR_PX * 0.8))) : 0;
        const title = last
          ? dayRuns.map((r) => `${TRIGGER_TEXT[r.trigger]} ${RUN_STATE_TEXT[runState(r, now)]} ${r.upserted_count}건`).join(", ")
          : day === today && pendingToday
            ? "오늘 수집 전(매일 09시대)"
            : "수집 없음";
        return (
          <div key={day} className="flex w-9 shrink-0 flex-col items-center gap-1" title={`${day}: ${title}`}>
            <span className="num text-[10px] text-muted">{last ? saved.toLocaleString("ko-KR") : ""}</span>
            <div className="flex h-16 w-full items-end">
              {last ? (
                <div className={`w-full rounded-sm ${RUN_STATE_BG[runState(last, now)]}`} style={{ height }} />
              ) : (
                <div
                  className={`h-2 w-full rounded-sm border border-dashed ${day === today && pendingToday ? "border-border" : "border-error"}`}
                />
              )}
            </div>
            <span className="num text-[10px] text-muted">{day.slice(5).replace("-", "/")}</span>
          </div>
        );
      })}
    </div>
  );
}
