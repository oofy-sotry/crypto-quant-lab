import type { IntegrityIssue, IssueType } from "@/lib/api";
import { formatDateTime, formatPercent } from "@/lib/format";

export const ISSUE_TYPE_TEXT: Record<IssueType, string> = {
  missing: "결측일",
  ohlc_invalid: "OHLC 규칙 위반",
  non_positive: "0 이하 가격",
  zero_volume: "거래량 0",
  spike: "급등락",
  stale: "수집 지연",
};

/** 유형별 detail을 한 줄 설명으로 바꾼다. */
function describe(issue: IntegrityIssue): string {
  const d = issue.detail;
  switch (issue.type) {
    case "missing":
      return "이날 일봉이 없음";
    case "spike":
      return `전일(${String(d.prev_date).slice(5)}) 종가 대비 ${formatPercent(Number(d.change), true)}`;
    case "ohlc_invalid":
    case "non_positive":
      return `시 ${d.open} · 고 ${d.high} · 저 ${d.low} · 종 ${d.close}`;
    case "stale":
      return `마지막 확정 봉 이후 ${d.lag_days}일 지남`;
    case "zero_volume":
      return "거래량 0";
  }
}

function Status({ issue }: { issue: IntegrityIssue }) {
  if (!issue.resolved_at) return <span className="text-muted">열림</span>;
  return (
    <div>
      <span className="text-ok">해결됨</span>
      <span className="ml-1 text-xs text-muted">{formatDateTime(issue.resolved_at)}</span>
      {issue.note && <div className="max-w-56 text-xs whitespace-normal text-muted">{issue.note}</div>}
    </div>
  );
}

/** 무결성 이슈 표. 오류는 백테스트를 막고(422), 경고는 참고용이다. */
export function IssueList({ issues }: { issues: IntegrityIssue[] }) {
  if (issues.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">조건에 맞는 이슈가 없습니다.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="py-2 pr-2 font-normal">날짜</th>
            <th className="px-2 py-2 font-normal">종목</th>
            <th className="px-2 py-2 font-normal">유형</th>
            <th className="px-2 py-2 font-normal">내용</th>
            <th className="py-2 pl-2 font-normal">상태</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id} className="border-b border-border align-top last:border-0">
              <td className="num py-2 pr-2">{issue.date}</td>
              <td className="px-2 py-2">{issue.symbol}</td>
              <td className="px-2 py-2">
                <span
                  className={`mr-1.5 inline-block size-2 rounded-full ${issue.severity === "error" ? "bg-error" : "bg-warn"}`}
                  aria-label={issue.severity === "error" ? "오류" : "경고"}
                />
                {ISSUE_TYPE_TEXT[issue.type]}
              </td>
              <td className="num px-2 py-2">{describe(issue)}</td>
              <td className="py-2 pl-2">
                <Status issue={issue} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
