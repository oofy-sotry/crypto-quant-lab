import Link from "next/link";
import { AssetCard } from "@/components/AssetCard";
import { StatusStrip } from "@/components/StatusStrip";
import { getCandles, getHealth, getIntegritySummary } from "@/lib/api";

const CARD_DAYS = 30;

function daysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export default async function Home() {
  // 서로 의존하지 않는 호출은 동시에 보낸다. 실패해도 화면 전체가 깨지지 않게 null로 받는다.
  const [health, summary] = await Promise.all([getHealth(), getIntegritySummary().catch(() => null)]);
  const from = daysAgo(CARD_DAYS);
  const candles = await Promise.all(
    (summary?.assets ?? []).map((a) => getCandles(a.symbol, from).catch(() => null)),
  );

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight">코인 데이터 대시보드</h1>
        <p className="mt-1 text-sm text-muted">
          업비트 일봉을 매일 수집해 무결성을 검사하고, 전략을 백테스트합니다.
        </p>
      </section>

      <StatusStrip health={health} summary={summary} />

      <section>
        <h2 className="mb-3 font-semibold">종목</h2>
        {summary ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {summary.assets.map((asset, i) => (
              <AssetCard key={asset.symbol} asset={asset} candles={candles[i]} />
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-border bg-panel p-4 text-sm text-muted">
            API 응답이 없어 종목을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.
          </p>
        )}
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <Link
          href="/backtest"
          className="rounded-xl border border-border bg-panel p-4 transition-colors hover:border-accent"
        >
          <div className="font-semibold">백테스트 실행 →</div>
          <p className="mt-1 text-sm text-muted">
            이동평균 교차 전략을 기간·파라미터별로 돌려 보고 매수 후 보유와 비교합니다.
          </p>
        </Link>
        <Link
          href="/assets/KRW-BTC"
          className="rounded-xl border border-border bg-panel p-4 transition-colors hover:border-accent"
        >
          <div className="font-semibold">가격 차트 →</div>
          <p className="mt-1 text-sm text-muted">상장일부터 전체 일봉과 이동평균선을 봅니다.</p>
        </Link>
        <Link
          href="/integrity"
          className="rounded-xl border border-border bg-panel p-4 transition-colors hover:border-accent"
        >
          <div className="font-semibold">데이터 품질 →</div>
          <p className="mt-1 text-sm text-muted">결측·급등락 같은 무결성 이슈와 해결 사유를 봅니다.</p>
        </Link>
        <Link
          href="/status"
          className="rounded-xl border border-border bg-panel p-4 transition-colors hover:border-accent"
        >
          <div className="font-semibold">운영 상태 →</div>
          <p className="mt-1 text-sm text-muted">서버 상태와 매일 자동 수집(Cron) 기록을 봅니다.</p>
        </Link>
      </section>
    </div>
  );
}
