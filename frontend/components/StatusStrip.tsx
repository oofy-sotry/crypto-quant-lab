import type { Health, IntegritySummary } from "@/lib/api";
import { formatDateTime, hoursSince } from "@/lib/format";

// Cron은 하루 1번(무료 플랜이라 09시대 중 아무 때) 돈다. 하루 + 실행 시각 오차를 넘기면 경고.
const STALE_HOURS = 26;

type Tone = "ok" | "warn" | "error";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  error: "bg-error",
};

function Item({ tone, label, value, detail }: { tone: Tone; label: string; value: string; detail?: string }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <span className={`mt-1.5 size-2 shrink-0 rounded-full ${TONE_CLASS[tone]}`} aria-hidden />
      <div className="min-w-0">
        <div className="text-xs text-muted">{label}</div>
        <div className="font-medium">{value}</div>
        {detail && <div className="num truncate text-xs text-muted">{detail}</div>}
      </div>
    </div>
  );
}

const STATUS_TEXT = { success: "성공", partial: "일부 실패", failed: "실패", running: "실행 중" };
const TRIGGER_TEXT = { cron: "자동", manual: "수동", backfill: "백필", beat: "Celery" };

/** 홈 맨 위의 운영 상태 요약: 서버, 마지막 수집, 데이터 오류 */
export function StatusStrip({ health, summary }: { health: Health | null; summary: IntegritySummary | null }) {
  const server: [Tone, string, string | undefined] = !health
    ? ["error", "응답 없음", undefined]
    : health.status === "ok"
      ? ["ok", "정상", `DB ${health.latency_ms.database}ms · Redis ${health.latency_ms.cache}ms`]
      : ["error", "장애", Object.entries(health.checks).map(([k, v]) => `${k}: ${v}`).join(" · ")];

  const run = summary?.last_run;
  const collection: [Tone, string, string | undefined] = !run
    ? ["warn", "기록 없음", undefined]
    : [
        run.status === "failed" ? "error" : run.status === "success" && hoursSince(run.started_at) <= STALE_HOURS ? "ok" : "warn",
        `${formatDateTime(run.started_at)} ${STATUS_TEXT[run.status]}`,
        hoursSince(run.started_at) > STALE_HOURS
          ? `${Math.floor(hoursSince(run.started_at))}시간 동안 수집 없음`
          : `${TRIGGER_TEXT[run.trigger]} · ${run.upserted_count}건 저장`,
      ];

  const errors = summary?.assets.reduce((n, a) => n + a.open_errors, 0) ?? 0;
  const warnings = summary?.assets.reduce((n, a) => n + a.open_warnings, 0) ?? 0;
  const quality: [Tone, string, string | undefined] = !summary
    ? ["error", "확인 불가", undefined]
    : [errors > 0 ? "error" : "ok", errors > 0 ? `오류 ${errors}건` : "오류 없음", `참고할 경고 ${warnings}건(급등락 등)`];

  return (
    <section className="grid gap-4 rounded-xl border border-border bg-panel p-4 sm:grid-cols-3">
      <Item tone={server[0]} label="API 서버" value={server[1]} detail={server[2]} />
      <Item tone={collection[0]} label="마지막 수집" value={collection[1]} detail={collection[2]} />
      <Item tone={quality[0]} label="데이터 품질" value={quality[1]} detail={quality[2]} />
    </section>
  );
}
