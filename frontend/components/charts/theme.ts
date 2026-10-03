"use client";

import { ColorType, type DeepPartial, type ChartOptions } from "lightweight-charts";
import { useEffect, useState } from "react";

// 차트 라이브러리는 CSS 변수를 직접 못 읽어서, globals.css의 색을 읽어 넘겨준다.
export type ChartColors = {
  text: string;
  muted: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  accent: string;
  lineA: string;
  lineB: string;
};

function readColors(): ChartColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    text: v("--foreground"),
    muted: v("--muted"),
    grid: v("--chart-grid"),
    border: v("--border"),
    up: v("--up"),
    down: v("--down"),
    accent: v("--accent"),
    lineA: v("--line-a"),
    lineB: v("--line-b"),
  };
}

/** 현재 테마 색. OS가 라이트↔다크로 바뀌면 다시 읽는다. 첫 렌더(서버)에서는 null. */
export function useChartColors(): ChartColors | null {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setColors(readColors());
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return colors;
}

export function baseChartOptions(c: ChartColors): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: c.muted,
      fontFamily: "var(--font-geist-sans), sans-serif",
      // 라이선스(Apache 2.0 + NOTICE)상 TradingView 표기가 필요해 기본 로고를 그대로 둔다.
    },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.border },
    timeScale: { borderColor: c.border },
    localization: { locale: "ko-KR" },
  };
}
