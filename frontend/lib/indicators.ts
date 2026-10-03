// 차트 보조 지표. 백엔드 전략(ma_cross)과 같은 정의를 쓴다: 종가 단순이동평균.

export type Point = { time: string; value: number };

/** 단순이동평균. 앞의 (period-1)일은 값이 없으므로 결과에서 빠진다. */
export function sma(points: Point[], period: number): Point[] {
  const result: Point[] = [];
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    sum += points[i].value;
    if (i >= period) sum -= points[i - period].value;
    if (i >= period - 1) result.push({ time: points[i].time, value: sum / period });
  }
  return result;
}

/** 각 시점의 고점 대비 하락률 (0 또는 음수, -0.3 = 고점 대비 -30%). 백엔드 drawdown과 같은 정의. */
export function drawdowns(values: number[]): number[] {
  let peak = -Infinity;
  return values.map((v) => {
    peak = Math.max(peak, v);
    return peak > 0 ? v / peak - 1 : 0;
  });
}

/** 처음 값 대비 마지막 값의 변화율 (0.1 = +10%) */
export function changeRatio(values: number[]): number {
  if (values.length < 2 || values[0] === 0) return 0;
  return values[values.length - 1] / values[0] - 1;
}
