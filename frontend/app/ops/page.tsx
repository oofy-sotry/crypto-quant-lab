import { OpsMatrix } from "@/components/OpsMatrix";
import { ReprocessTable } from "@/components/ReprocessTable";
import { connection } from "next/server";
import { getOpsDays, getReprocessRuns } from "@/lib/api";

export default async function OpsPage() {
  // 재처리·Cron 직후의 상태를 바로 봐야 해서 캐시하지 않고 요청마다 새로 그린다.
  await connection();
  const [matrix, runs] = await Promise.all([
    getOpsDays(30).catch(() => null),
    getReprocessRuns().catch(() => null),
  ]);
  // eslint-disable-next-line react-hooks/purity -- 서버에서 요청마다 한 번 그리는 컴포넌트라 다시 렌더링될 일이 없다
  const now = Date.now();

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight">운영 콘솔</h1>
        <p className="mt-1 text-sm text-muted">
          종목·날짜(UTC, 업비트 일봉 경계)마다 분봉 수집 → 집계 → 정합성 검사가 끝났는지 봅니다. 칸을 누르면 그날의
          빈 구간, 시간대별 집계, 업비트 일봉과의 대조, 이슈와 재처리 이력이 나옵니다. 운영 DB는 분봉을 최근 30일만
          보관합니다.
        </p>
      </section>

      <section className="rounded-xl border border-border bg-panel p-4">
        <h2 className="mb-3 font-semibold">
          날짜별 상태{matrix && <span className="num ml-2 text-xs font-normal text-muted">{matrix.start} ~ {matrix.end}</span>}
        </h2>
        {matrix ? <OpsMatrix matrix={matrix} /> : <p className="text-sm text-muted">API 응답이 없어 불러오지 못했습니다.</p>}
      </section>

      <section className="rounded-xl border border-border bg-panel p-4">
        <h2 className="font-semibold">재처리 이력</h2>
        <p className="mb-3 text-xs text-muted">
          재처리는 관리자 토큰이 필요한 API(<code>POST /api/reprocess/</code>)나 커맨드로만 실행하고, 이 화면은 조회만
          합니다. 미리 보기(dry-run)는 실제와 같은 코드를 실행한 뒤 되돌린 결과입니다.
        </p>
        {runs ? <ReprocessTable runs={runs.slice(0, 30)} now={now} /> : <p className="text-sm text-muted">API 응답이 없어 불러오지 못했습니다.</p>}
      </section>
    </div>
  );
}
