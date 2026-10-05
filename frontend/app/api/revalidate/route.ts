import { createHash, timingSafeEqual } from "node:crypto";
import { revalidateTag } from "next/cache";
import { API_CACHE_TAG } from "@/lib/api";

// 해시해서 길이를 맞춘 뒤 비교한다. timingSafeEqual은 길이가 다르면 바로 예외를 내서 길이가 새기 때문.
function sameSecret(received: string, expected: string): boolean {
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(received), digest(expected));
}

/**
 * 백엔드 Cron이 수집을 마친 뒤 호출한다. 캐시한 API 응답을 바로 만료시켜,
 * 오랜만에 들어온 첫 방문자도 이전 데이터가 아니라 새 데이터를 보게 한다.
 * `Authorization: Bearer <REVALIDATE_SECRET>`이 맞아야 하고, 비밀값이 설정되지 않았으면 모두 거부한다.
 */
export async function POST(request: Request) {
  const secret = process.env.REVALIDATE_SECRET ?? "";
  const received = request.headers.get("authorization") ?? "";
  if (!secret || !sameSecret(received, `Bearer ${secret}`)) {
    return Response.json({ detail: "인증 실패" }, { status: 401 });
  }
  // "max"는 다음 요청에 이전 값을 주며 뒤에서 갱신한다. 그걸 피하려는 호출이라 즉시 만료(expire: 0)로 한다.
  revalidateTag(API_CACHE_TAG, { expire: 0 });
  return Response.json({ revalidated: true });
}
