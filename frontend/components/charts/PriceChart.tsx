"use client";

import {
  CandlestickSeries,
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatPriceAxis } from "@/lib/format";
import { sma } from "@/lib/indicators";
import { baseChartOptions, useChartColors } from "./theme";

/** 서버에서 숫자로 바꿔 넘긴 일봉 (t: 날짜) */
export type Bar = { t: string; o: number; h: number; l: number; c: number };

const RANGES = [
  { label: "3개월", days: 90 },
  { label: "1년", days: 365 },
  { label: "3년", days: 365 * 3 },
  { label: "전체", days: null },
] as const;

function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** 캔들 + 이동평균선 2개. 기간 버튼과 이동평균 기간은 화면에서 바로 바꾼다(다시 불러오지 않음). */
export function PriceChart({ bars }: { bars: Bar[] }) {
  const colors = useChartColors();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<{
    candles: ISeriesApi<"Candlestick">;
    short: ISeriesApi<"Line">;
    long: ISeriesApi<"Line">;
  } | null>(null);

  const [range, setRange] = useState<(typeof RANGES)[number]>(RANGES[1]);
  const [short, setShort] = useState(20);
  const [long, setLong] = useState(60);

  const closes = useMemo(() => bars.map((b) => ({ time: b.t, value: b.c })), [bars]);

  // 차트 생성·색 적용 (테마가 바뀌면 다시 만든다)
  useEffect(() => {
    if (!colors || !containerRef.current) return;
    const chart = createChart(containerRef.current, baseChartOptions(colors));
    chart.applyOptions({ localization: { locale: "ko-KR", priceFormatter: formatPriceAxis } });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderVisible: false,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });
    const line = { lineWidth: 2, priceLineVisible: false, lastValueVisible: false } as const;
    const shortSeries = chart.addSeries(LineSeries, { ...line, color: colors.lineA });
    const longSeries = chart.addSeries(LineSeries, { ...line, color: colors.lineB });
    candles.setData(bars.map((b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c })));
    chartRef.current = chart;
    seriesRef.current = { candles, short: shortSeries, long: longSeries };
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [colors, bars]);

  // 이동평균 다시 계산
  useEffect(() => {
    seriesRef.current?.short.setData(sma(closes, short));
    seriesRef.current?.long.setData(sma(closes, long));
  }, [colors, closes, short, long]);

  // 보이는 기간
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    if (range.days === null) {
      chart.timeScale().fitContent();
    } else {
      const to = bars[bars.length - 1].t;
      chart.timeScale().setVisibleRange({ from: shiftDate(to, range.days), to });
    }
  }, [colors, bars, range]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1" role="group" aria-label="기간">
          {RANGES.map((r) => (
            <button
              key={r.label}
              onClick={() => setRange(r)}
              aria-pressed={r === range}
              className={`rounded-md px-2.5 py-1 text-sm ${
                r === range ? "bg-accent/10 font-semibold text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <MaInput label="단기" color="var(--line-a)" value={short} onChange={setShort} />
          <MaInput label="장기" color="var(--line-b)" value={long} onChange={setLong} />
        </div>
      </div>
      <div ref={containerRef} className="h-[420px] w-full sm:h-[520px]" />
    </div>
  );
}

function MaInput({
  label,
  color,
  value,
  onChange,
}: {
  label: string;
  color: string;
  value: number;
  onChange: (v: number) => void;
}) {
  // "15"를 치는 도중의 "1"처럼 중간 값도 입력란에는 보여야 하므로 글자는 따로 들고,
  // 유효한 숫자일 때만 차트에 반영한다.
  const [text, setText] = useState(String(value));
  return (
    <label className="flex items-center gap-1.5">
      <span className="inline-block h-0.5 w-4 rounded" style={{ background: color }} aria-hidden />
      <span className="text-muted">{label} MA</span>
      <input
        type="number"
        min={2}
        max={400}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (Number.isInteger(n) && n >= 2 && n <= 400) onChange(n);
        }}
        className="num w-16 rounded-md border border-border bg-panel px-2 py-1"
      />
    </label>
  );
}
