import { DailyRunBars } from "@/components/DailyRunBars";
import { FreshnessTable } from "@/components/FreshnessTable";
import { OpsCards } from "@/components/OpsCards";
import { RunTable } from "@/components/RunTable";
import { connection } from "next/server";
import { getCollectionRuns, getHealth, getIntegritySummary } from "@/lib/api";

export default async function StatusPage() {
  // 미리 만들어 둔(캐시된) 화면을 주면 "몇 시간 전"이 만든 시점 기준으로 굳는다. 요청마다 새로 그린다.
  await connection();
  const [health, runs, summary] = await Promise.all([
    getHealth(true),
    getCollectionRuns(true).catch(() => null),
    getIntegritySummary(true).catch(() => null),
  ]);
  // 경과 시간·밀린 일수를 모두 같은 시각 기준으로 계산한다. connection() 뒤라 요청 시각이다.
  // eslint-disable-next-line react-hooks/purity -- 서버에서 요청마다 한 번 그리는 컴포넌트라 다시 렌더링될 일이 없다
  const now = Date.now();

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight">운영 상태</h1>
        <p className="mt-1 text-sm text-muted">
          서버와 매일 자동 수집(Vercel Cron)이 제대로 도는지 봅니다. Cron이 아예 실행되지 않으면 오류가 없어 알림도
          오지 않으므로, 마지막 수집 후 경과 시간과 빠진 날짜로 확인합니다.
        </p>
      </section>

      {runs ? (
        <>
          <OpsCards health={health} runs={runs} now={now} />
          <section className="rounded-xl border border-border bg-panel p-4">
            <h2 className="font-semibold">날짜별 수집 (최근 14일)</h2>
            <p className="mb-3 text-xs text-muted">막대 = 저장 건수, 색 = 그날 마지막 실행 결과, 빨간 점선 = 수집 없음</p>
            <DailyRunBars runs={runs} now={now} />
          </section>
        </>
      ) : (
        <p className="rounded-xl border border-border bg-panel p-4 text-sm text-muted">
          API 응답이 없어 수집 기록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.
        </p>
      )}

      <section className="rounded-xl border border-border bg-panel p-4">
        <h2 className="mb-2 font-semibold">종목별 최신 데이터</h2>
        {summary ? (
          <FreshnessTable assets={summary.assets} now={now} />
        ) : (
          <p className="text-sm text-muted">API 응답이 없어 불러오지 못했습니다.</p>
        )}
      </section>

      {runs && (
        <section className="rounded-xl border border-border bg-panel p-4">
          <h2 className="mb-2 font-semibold">수집 기록</h2>
          <RunTable runs={runs} now={now} />
        </section>
      )}
    </div>
  );
}
