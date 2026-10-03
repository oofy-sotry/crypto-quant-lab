// 화면 표시용 숫자·날짜 포맷.

const krw = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
const krwSmall = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

/** 원화 가격. 1원 미만 코인(예: 도지코인 일부 구간)은 소수점 둘째 자리까지. */
export function formatKRW(value: number): string {
  return `${(value < 100 ? krwSmall : krw).format(value)}원`;
}

/** 차트 가격 축: 200000000 → "200,000,000" (단위 없이) */
export function formatPriceAxis(value: number): string {
  return (value < 100 ? krwSmall : krw).format(value);
}

/** 0.1234 → "+12.34%" (sign=true면 양수에 + 표시) */
export function formatPercent(ratio: number, sign = false): string {
  const text = `${(ratio * 100).toFixed(2)}%`;
  return sign && ratio > 0 ? `+${text}` : text;
}

export function formatNumber(value: number, digits = 2): string {
  return value.toFixed(digits);
}

/** ISO 시각 → "10/3 18:41" (한국 시간) */
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/** 지금부터 몇 시간 전인지 */
export function hoursSince(iso: string, now: number = Date.now()): number {
  return (now - new Date(iso).getTime()) / 3_600_000;
}
