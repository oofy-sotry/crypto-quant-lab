import { IntegrityTable } from "@/components/IntegrityTable";
import { IssueFilters } from "@/components/IssueFilters";
import { IssueList } from "@/components/IssueList";
import { getIntegrityIssues, getIntegritySummary, type IssueFilters as Filters } from "@/lib/api";

function pick(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

export default async function IntegrityPage(props: PageProps<"/integrity">) {
  const query = await props.searchParams;
  const resolved = pick(query.resolved);
  const filters: Filters = {
    symbol: pick(query.symbol),
    type: pick(query.type),
    severity: pick(query.severity),
    resolved: resolved === "true" || resolved === "false" ? resolved : undefined,
  };

  const [summary, issues] = await Promise.all([
    getIntegritySummary().catch(() => null),
    getIntegrityIssues(filters).catch(() => null),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight">데이터 품질</h1>
        <p className="mt-1 text-sm text-muted">
          수집할 때마다 결측일·OHLC 규칙·급등락·수집 지연을 검사합니다. 해결되지 않은 <b className="text-error">오류</b>가
          기간에 있으면 백테스트를 거부하고(빈 날을 채워 틀린 결과를 내지 않기 위해), <b className="text-warn">경고</b>는
          실제 시장 움직임일 수 있어 참고용으로만 남깁니다.
        </p>
      </section>

      <section className="rounded-xl border border-border bg-panel p-4">
        <h2 className="mb-2 font-semibold">종목별 요약</h2>
        {summary ? (
          <IntegrityTable assets={summary.assets} />
        ) : (
          <p className="text-sm text-muted">API 응답이 없어 요약을 불러오지 못했습니다.</p>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-xl border border-border bg-panel p-4">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-semibold">이슈 목록</h2>
          {issues && (
            <span className="text-xs text-muted">
              {issues.count}건{issues.count > issues.results.length && ` 중 최근 ${issues.results.length}건`}
            </span>
          )}
        </div>
        <IssueFilters assets={summary?.assets ?? []} filters={filters} />
        {issues ? (
          <IssueList issues={issues.results} />
        ) : (
          <p className="text-sm text-muted">API 응답이 없어 이슈를 불러오지 못했습니다.</p>
        )}
      </section>
    </div>
  );
}
