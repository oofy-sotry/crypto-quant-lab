import Link from "next/link";
import { notFound } from "next/navigation";
import { PriceChart, type Bar } from "@/components/charts/PriceChart";
import { getCandles, getIntegritySummary } from "@/lib/api";
import { formatKRW, formatPercent } from "@/lib/format";

export default async function AssetPage(props: PageProps<"/assets/[symbol]">) {
  const { symbol } = await props.params;
  const summary = await getIntegritySummary().catch(() => null);
  if (!summary) {
    return <p className="rounded-xl border border-border bg-panel p-4 text-sm text-muted">API 응답이 없어 차트를 불러오지 못했습니다.</p>;
  }
  const asset = summary.assets.find((a) => a.symbol === symbol);
  if (!asset) notFound();

  const candles = await getCandles(symbol);
  // 가격 문자열(Decimal)을 차트용 숫자로 바꾸고 필드 이름을 줄여 브라우저로 보내는 양을 줄인다.
  const bars: Bar[] = candles.map((c) => ({
    t: c.date,
    o: Number(c.open),
    h: Number(c.high),
    l: Number(c.low),
    c: Number(c.close),
  }));
  const last = candles.at(-1);
  const prev = candles.at(-2);
  const dayChange = last && prev ? Number(last.close) / Number(prev.close) - 1 : 0;

  return (
    <div className="flex flex-col gap-4">
      <nav className="flex flex-wrap gap-1.5" aria-label="종목">
        {summary.assets.map((a) => (
          <Link
            key={a.symbol}
            href={`/assets/${a.symbol}`}
            aria-current={a.symbol === symbol ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-sm ${
              a.symbol === symbol
                ? "border-accent bg-accent/10 font-semibold text-accent"
                : "border-border bg-panel text-muted hover:text-foreground"
            }`}
          >
            {a.name}
          </Link>
        ))}
      </nav>

      <section className="rounded-xl border border-border bg-panel p-4">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-bold">
              {asset.name} <span className="text-sm font-normal text-muted">{asset.symbol}</span>
            </h1>
            {last && (
              <div className="mt-1 flex items-baseline gap-2">
                <span className="num text-2xl font-semibold">{formatKRW(Number(last.close))}</span>
                <span className={`num text-sm ${dayChange >= 0 ? "text-up" : "text-down"}`}>
                  전일 대비 {formatPercent(dayChange, true)}
                </span>
              </div>
            )}
          </div>
          <div className="text-right text-xs text-muted">
            <div>
              {asset.first_date} ~ {asset.last_final_date} · 일봉 {asset.candle_count.toLocaleString()}개
            </div>
            {last && !last.is_final && <div>마지막 봉({last.date})은 진행 중이라 값이 바뀔 수 있습니다</div>}
          </div>
        </div>
        <PriceChart bars={bars} />
      </section>
    </div>
  );
}
