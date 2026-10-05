import type { CollectionRun, Health } from "@/lib/api";
import { formatDateTime, hoursSince } from "@/lib/format";
import { kstDate, RUN_STATE_TEXT, runState, STALE_HOURS } from "@/lib/runs";

type Tone = "ok" | "warn" | "error";

const TONE_TEXT: Record<Tone, string> = { ok: "text-ok", warn: "text-warn", error: "text-error" };

function Card({ label, tone, value, children }: { label: string; tone: Tone; value: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${TONE_TEXT[tone]}`}>{value}</div>
      <div className="mt-2 text-sm text-muted">{children}</div>
    </div>
  );
}

const SERVICE_TEXT: Record<string, string> = { database: "DB (MySQL)", cache: "Redis" };

/** 운영 상태 화면 위쪽 카드 3개: 서버 의존 서비스, 마지막 자동 수집, 최근 자동 수집 성공 일수 */
export function OpsCards({ health, runs, now }: { health: Health | null; runs: CollectionRun[]; now: number }) {
  const lastCron = runs.find((r) => r.trigger === "cron");
  const hours = lastCron ? hoursSince(lastCron.started_at, now) : Infinity;
  const stale = hours > STALE_HOURS;
  const cronTone: Tone = !lastCron || stale ? "error" : lastCron.status === "success" ? "ok" : "warn";

  // 어제까지 최근 7일 중 자동 수집이 한 번이라도 성공한 날 수. Cron을 걸기 전 날짜는 빼고 센다.
  const cronRuns = runs.filter((r) => r.trigger === "cron");
  const firstCronDay = cronRuns.length > 0 ? kstDate(cronRuns[cronRuns.length - 1].started_at) : kstDate(now);
  const week = Array.from({ length: 7 }, (_, i) => kstDate(now - (i + 1) * 86_400_000)).filter((d) => d >= firstCronDay);
  const cronDays = new Set(cronRuns.filter((r) => r.status === "success").map((r) => kstDate(r.started_at)));
  const okDays = week.filter((d) => cronDays.has(d)).length;

  return (
    <section className="grid gap-3 sm:grid-cols-3">
      <Card label="API 서버" tone={!health ? "error" : health.status === "ok" ? "ok" : "error"} value={!health ? "응답 없음" : health.status === "ok" ? "정상" : "장애"}>
        {health ? (
          <ul className="flex flex-col gap-0.5">
            {Object.entries(health.checks).map(([name, status]) => (
              <li key={name} className="flex justify-between gap-2">
                <span>{SERVICE_TEXT[name] ?? name}</span>
                <span className={`num ${status === "ok" ? "" : "text-error"}`}>
                  {status === "ok" ? `${health.latency_ms[name]}ms` : status}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          "health API가 응답하지 않습니다."
        )}
      </Card>
      <Card
        label="마지막 자동 수집 (Cron)"
        tone={cronTone}
        value={lastCron ? `${Math.floor(hours)}시간 전` : "기록 없음"}
      >
        {lastCron ? (
          <>
            {formatDateTime(lastCron.started_at)} {RUN_STATE_TEXT[runState(lastCron, now)]}
            {stale && <div className="text-error">{STALE_HOURS}시간 넘게 자동 수집이 없습니다.</div>}
          </>
        ) : (
          "아직 자동 수집 기록이 없습니다."
        )}
        <div>매일 KST 09시대 실행</div>
      </Card>
      <Card
        label="자동 수집 성공 (어제까지 최근 7일)"
        tone={okDays === week.length ? "ok" : okDays === 0 ? "error" : "warn"}
        value={`${okDays} / ${week.length}일`}
      >
        하루 실패해도 다음 날 최근 7일을 다시 받아 빈 날을 메웁니다.
      </Card>
    </section>
  );
}
