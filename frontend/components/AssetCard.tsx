import Link from "next/link";
import type { AssetSummary, Candle } from "@/lib/api";
import { formatKRW, formatPercent } from "@/lib/format";
import { changeRatio } from "@/lib/indicators";
import { Sparkline } from "./Sparkline";

/** 홈의 종목 카드: 최근 가격, 30일 변화율, 추세선. 누르면 가격 차트로 간다. */
export function AssetCard({ asset, candles }: { asset: AssetSummary; candles: Candle[] | null }) {
  const closes = candles?.map((c) => Number(c.close)) ?? [];
  const last = candles?.at(-1);
  const change = changeRatio(closes);
  const up = change >= 0;

  return (
    <Link
      href={`/assets/${asset.symbol}`}
      className="group flex flex-col gap-3 rounded-xl border border-border bg-panel p-4 transition-colors hover:border-accent"
    >
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="font-semibold">{asset.name}</div>
          <div className="text-xs text-muted">{asset.symbol}</div>
        </div>
        {asset.open_errors > 0 && (
          <span className="rounded bg-error/10 px-1.5 py-0.5 text-xs text-error">오류 {asset.open_errors}</span>
        )}
      </div>

      {last ? (
        <>
          <div className="flex items-end justify-between gap-2">
            <div>
              <div className="num text-lg font-semibold">{formatKRW(Number(last.close))}</div>
              <div className={`num text-sm ${up ? "text-up" : "text-down"}`}>
                30일 {formatPercent(change, true)}
              </div>
            </div>
            <Sparkline values={closes} up={up} />
          </div>
          <div className="text-xs text-muted">
            {last.is_final ? `${last.date} 종가` : `${last.date} 진행 중 (마감 전)`}
          </div>
        </>
      ) : (
        <div className="text-sm text-muted">가격을 불러오지 못했습니다</div>
      )}
    </Link>
  );
}
