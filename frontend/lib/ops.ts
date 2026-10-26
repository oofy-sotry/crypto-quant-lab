// 운영 콘솔(종목×날짜 표, 재처리 이력) 표시 규칙.
import type { DayStatus, ReprocessRun } from "@/lib/api";
import { isStalled } from "@/lib/runs";

export const DAY_STATUS_TEXT: Record<DayStatus, string> = {
  error: "오류",
  no_minutes: "분봉 없음",
  not_aggregated: "집계 안 됨",
  warning: "경고",
  ok: "정상",
};

export const DAY_STATUS_HELP: Record<DayStatus, string> = {
  error: "해결되지 않은 오류 이슈가 있음",
  no_minutes: "분봉이 하나도 없음 (수집 안 됨)",
  not_aggregated: "일 집계가 없거나, 집계한 분봉 수가 지금 분봉 수와 다름",
  warning: "해결되지 않은 경고 이슈가 있음 (예: 30분 이상 빈 구간)",
  ok: "분봉·집계·검사 모두 정상",
};

export const DAY_STATUS_BG: Record<DayStatus, string> = {
  error: "bg-error",
  no_minutes: "bg-muted/40",
  not_aggregated: "bg-accent",
  warning: "bg-warn",
  ok: "bg-ok",
};

export const TARGET_TEXT: Record<ReprocessRun["target"], string> = {
  minutes: "분봉 재수집",
  aggregates: "재집계",
  daily: "일봉 재수집",
};

export type ReprocessState = ReprocessRun["status"] | "stalled";

export const REPROCESS_STATE_TEXT: Record<ReprocessState, string> = {
  success: "성공",
  failed: "실패(롤백)",
  rejected: "거부(실행 중)",
  running: "실행 중",
  stalled: "중단됨",
};

export const REPROCESS_STATE_BG: Record<ReprocessState, string> = {
  success: "bg-ok",
  failed: "bg-error",
  rejected: "bg-warn",
  running: "bg-accent",
  stalled: "bg-error",
};

// 재처리 API는 서버리스 함수 제한(300초) 안에서 끝난다. 오래 running이면 함수가 강제 종료돼
// 이력을 못 바꾼 것이다(트랜잭션은 롤백됨). 수집 기록과 같은 규칙.
export function reprocessState(run: ReprocessRun, now: number): ReprocessState {
  if (run.status !== "running") return run.status;
  return isStalled(run.started_at, now) ? "stalled" : "running";
}

/** 재처리 diff의 테이블 이름 → 화면 이름 */
export const TABLE_TEXT: Record<string, string> = {
  minutecandle: "분봉",
  hourlybar: "시간봉",
  dailyagg: "일 집계",
  dailycandle: "일봉",
};
