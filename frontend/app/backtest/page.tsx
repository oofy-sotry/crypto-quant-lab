import { BacktestView } from "@/components/BacktestView";
import { getIntegritySummary } from "@/lib/api";

export default async function BacktestPage() {
  // 종목 목록과 데이터 기간(날짜 입력 범위·기본 종료일)만 서버에서 받고, 계산은 브라우저가 API를 직접 부른다.
  const summary = await getIntegritySummary().catch(() => null);

  return (
    <div className="flex flex-col gap-4">
      <section>
        <h1 className="text-2xl font-bold tracking-tight">백테스트</h1>
        <p className="mt-1 text-sm text-muted">
          과거 일봉으로 전략을 시뮬레이션하고, 같은 기간 매수 후 보유(Buy&amp;Hold)와 비교합니다.
        </p>
      </section>
      {summary && summary.assets.length > 0 ? (
        <BacktestView assets={summary.assets} />
      ) : (
        <p className="rounded-xl border border-border bg-panel p-4 text-sm text-muted">
          API 응답이 없어 종목을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.
        </p>
      )}
    </div>
  );
}
