// 수집 실행 기록(CollectionRun) 표시 규칙.
import type { CollectionRun } from "@/lib/api";

export type RunState = CollectionRun["status"] | "stalled";

export const RUN_STATE_TEXT: Record<RunState, string> = {
  success: "성공",
  partial: "일부 실패",
  failed: "실패",
  running: "실행 중",
  stalled: "중단됨",
};

export const TRIGGER_TEXT: Record<CollectionRun["trigger"], string> = {
  cron: "자동",
  manual: "수동",
  backfill: "백필",
  beat: "Celery",
};

// 함수 제한 시간(300초)보다 넉넉히 길게. 이보다 오래 running이면 함수가 강제 종료돼 상태를 못 바꾼 것이다.
const STALLED_MINUTES = 10;

/** running으로 남아 있지만 실제로는 끝난(강제 종료된) 실행을 "중단됨"으로 본다. */
export function runState(run: CollectionRun, now: number = Date.now()): RunState {
  if (run.status !== "running") return run.status;
  const minutes = (now - new Date(run.started_at).getTime()) / 60_000;
  return minutes > STALLED_MINUTES ? "stalled" : "running";
}

/** 실행에 걸린 시간(초). 끝나지 않았으면 null. */
export function runSeconds(run: CollectionRun): number | null {
  if (!run.finished_at) return null;
  return (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000;
}

/** ISO 시각의 한국 날짜 "YYYY-MM-DD" */
export function kstDate(iso: string | number): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date(iso));
}

/**
 * 지금 기준으로 마감됐어야 하는 가장 최근 일봉 날짜.
 * 업비트 일봉은 KST 09:00(= UTC 00:00)에 바뀌므로, 진행 중인 봉의 날짜는 UTC 날짜이고 그 전날까지가 확정이다.
 */
export function expectedLastFinalDate(now: number = Date.now()): string {
  const d = new Date(now);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** 두 "YYYY-MM-DD" 사이의 일수 (b - a) */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);
}
