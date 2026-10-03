"use client";

import { BaselineSeries, createChart, LineSeries } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baseChartOptions, useChartColors, type ChartColors } from "./theme";

export type RatioSeries = {
  label: string;
  /** 색 이름(theme 키) — 테마가 바뀌어도 맞는 색을 쓰도록 이름으로 받는다 */
  color: keyof ChartColors;
  /** value는 비율(0.25 = 25%) */
  data: { time: string; value: number }[];
};

/** "#e0383e" + 0.3 → "rgba(224, 56, 62, 0.3)" — 차트 라이브러리가 읽을 수 있는 반투명 색 */
function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

const percent = (v: number) => `${(v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0)}%`;

/**
 * 비율(%) 시계열 여러 개를 한 차트에 겹쳐 그린다. 누적수익률(선)과 드로다운(면)에 같이 쓴다.
 * 범례는 차트 위에 HTML로 둔다(화면 읽기 프로그램도 읽을 수 있게).
 */
export function RatioChart({
  series,
  kind = "line",
  height = 320,
}: {
  series: RatioSeries[];
  kind?: "line" | "area";
  height?: number;
}) {
  const colors = useChartColors();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!colors || !containerRef.current) return;
    const chart = createChart(containerRef.current, baseChartOptions(colors));
    const priceFormat = { type: "custom" as const, formatter: percent, minMove: 0.0001 };
    for (const s of series) {
      const color = colors[s.color];
      const common = { priceFormat, lineWidth: 2 as const, priceLineVisible: false, title: "" };
      // 면 차트는 0%(기준선)와 선 사이만 채운다. 드로다운은 항상 0 이하라 아래쪽만 칠해진다.
      const added =
        kind === "area"
          ? chart.addSeries(BaselineSeries, {
              ...common,
              baseValue: { type: "price", price: 0 },
              topLineColor: color,
              topFillColor1: "transparent",
              topFillColor2: "transparent",
              bottomLineColor: color,
              bottomFillColor1: withAlpha(color, 0.05),
              bottomFillColor2: withAlpha(color, 0.25),
            })
          : chart.addSeries(LineSeries, { ...common, color });
      added.setData(s.data);
    }
    // 생성 직후에는 너비가 아직 0이라 fitContent가 먹지 않고, autoSize가 나중에 크기를 바꾼다.
    // 그래서 너비가 바뀔 때마다 전체 기간이 보이도록 다시 맞춘다.
    const timeScale = chart.timeScale();
    const fit = () => timeScale.fitContent();
    timeScale.subscribeSizeChange(fit);
    return () => {
      timeScale.unsubscribeSizeChange(fit);
      chart.remove();
    };
  }, [colors, series, kind]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-sm">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-4 rounded"
              style={{ background: colors?.[s.color] }}
              aria-hidden
            />
            {s.label}
          </span>
        ))}
      </div>
      <div ref={containerRef} style={{ height }} className="w-full" />
    </div>
  );
}
