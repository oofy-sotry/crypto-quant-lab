import Link from "next/link";
import type { AssetSummary, IssueFilters as Filters } from "@/lib/api";
import { ISSUE_TYPE_TEXT } from "@/components/IssueList";

const SELECT_CLASS = "rounded-md border border-border bg-background px-2 py-1.5 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}

/**
 * 이슈 목록 필터. 일반 GET 폼이라 조건이 URL(?symbol=…)에 남아 그대로 공유·새로고침할 수 있고,
 * 서버가 그 조건으로 다시 그리므로 브라우저 JavaScript 없이도 동작한다.
 */
export function IssueFilters({ assets, filters }: { assets: AssetSummary[]; filters: Filters }) {
  return (
    <form action="/integrity" className="flex flex-wrap items-end gap-3">
      <Field label="종목">
        <select name="symbol" defaultValue={filters.symbol ?? ""} className={SELECT_CLASS}>
          <option value="">전체</option>
          {assets.map((a) => (
            <option key={a.symbol} value={a.symbol}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="유형">
        <select name="type" defaultValue={filters.type ?? ""} className={SELECT_CLASS}>
          <option value="">전체</option>
          {Object.entries(ISSUE_TYPE_TEXT).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="심각도">
        <select name="severity" defaultValue={filters.severity ?? ""} className={SELECT_CLASS}>
          <option value="">전체</option>
          <option value="error">오류</option>
          <option value="warning">경고</option>
        </select>
      </Field>
      <Field label="상태">
        <select name="resolved" defaultValue={filters.resolved ?? ""} className={SELECT_CLASS}>
          <option value="">전체</option>
          <option value="false">열림</option>
          <option value="true">해결됨</option>
        </select>
      </Field>
      <button type="submit" className="rounded-md bg-accent px-4 py-1.5 text-sm font-semibold text-white">
        적용
      </button>
      <Link href="/integrity" className="py-1.5 text-sm text-muted hover:text-foreground">
        초기화
      </Link>
    </form>
  );
}
