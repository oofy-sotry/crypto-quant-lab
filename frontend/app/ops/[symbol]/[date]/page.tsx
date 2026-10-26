import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { DayCompare, HourlyBars } from "@/components/DayDetailParts";
import { IssueList } from "@/components/IssueList";
import { ReprocessTable } from "@/components/ReprocessTable";
import { ApiError, getOpsDay } from "@/lib/api";

function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function utcTime(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}

export default async function OpsDayPage(props: PageProps<"/ops/[symbol]/[date]">) {
  const { symbol, date } = await props.params;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) notFound();
  await connection();
  const detail = await getOpsDay(symbol, date).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) notFound();
    return null;
  });
  // eslint-disable-next-line react-hooks/purity -- 서버에서 요청마다 한 번 그리는 컴포넌트라 다시 렌더링될 일이 없다
  const now = Date.now();

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <Link href="/ops" className="text-sm text-accent hover:underline">
            ← 운영 콘솔
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">
            {symbol.replace("KRW-", "")} <span className="num">{date}</span>
            <span className="ml-2 text-sm font-normal text-muted">UTC 하루 (KST 09시 ~ 다음 날 09시)</span>
          </h1>
        </div>
        <nav className="flex gap-2 text-sm" aria-label="날짜 이동">
          <Link href={`/ops/${symbol}/${shiftDate(date, -1)}`} className="rounded-md border border-border px-3 py-1.5 hover:bg-accent/10">
            전날
          </Link>
          <Link href={`/ops/${symbol}/${shiftDate(date, 1)}`} className="rounded-md border border-border px-3 py-1.5 hover:bg-accent/10">
            다음 날
          </Link>
        </nav>
      </section>

      {!detail ? (
        <p className="rounded-xl border border-border bg-panel p-4 text-sm text-muted">API 응답이 없어 불러오지 못했습니다.</p>
      ) : (
        <>
          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-panel p-4">
              <h2 className="font-semibold">
                분봉 <span className="num">{detail.minute_count.toLocaleString("ko-KR")}</span>
                <span className="text-sm font-normal text-muted"> / 1,440분</span>
              </h2>
              <p className="mb-3 text-xs text-muted">거래가 없는 분은 업비트가 분봉을 주지 않아 1,440개보다 적을 수 있습니다.</p>
              <HourlyBars hourly={detail.hourly} />
              <h3 className="mt-4 mb-1 text-sm font-medium">10분 이상 빈 구간</h3>
              {detail.gaps.length === 0 ? (
                <p className="text-sm text-muted">없음</p>
              ) : (
                <ul className="num text-sm">
                  {detail.gaps.map((g) => (
                    <li key={g.start} className={g.minutes >= 30 ? "text-warn" : ""}>
                      {utcTime(g.start)} ~ {utcTime(g.end)} UTC ({g.minutes}분{g.minutes >= 30 && ", 경고 기준 이상"})
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="rounded-xl border border-border bg-panel p-4">
              <h2 className="font-semibold">업비트 일봉 대조</h2>
              <p className="mb-3 text-xs text-muted">
                가격이 하나라도 다르면 오류, 거래량·거래대금은 상대 오차 1e-6을 넘으면 경고입니다. 마감 전 일봉은 대조하지
                않습니다.
              </p>
              <DayCompare agg={detail.daily_agg} candle={detail.daily_candle} />
              {detail.daily_agg && (
                <p className="mt-2 text-xs text-muted">집계에 쓴 분봉 {detail.daily_agg.minute_count?.toLocaleString("ko-KR")}개</p>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-panel p-4">
            <h2 className="mb-2 font-semibold">이 날의 이슈 (해결된 것 포함)</h2>
            <IssueList issues={detail.issues} />
          </section>

          <section className="rounded-xl border border-border bg-panel p-4">
            <h2 className="mb-2 font-semibold">이 날을 포함한 재처리</h2>
            <ReprocessTable runs={detail.reprocess_runs} now={now} />
          </section>
        </>
      )}
    </div>
  );
}
