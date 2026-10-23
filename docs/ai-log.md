# AI 작업 기록

v2(`docs/ROADMAP.md`)부터 매일 Claude Code에게 맡긴 것과 직접 확인·결정·수정한 것을 나눠 기록한다.

## 2026-10-23 — 1단계 D1 PostgreSQL 전환

**Claude Code에게 맡긴 것**
- ROADMAP 초안과 원래 계획(5일안) 비교, 빠진 항목("같은 종목·기간" 동시 실행 방지) 복원
- 코드 전환: compose·CI의 MySQL → PostgreSQL, `PyMySQL` → `psycopg[binary]`, MySQL 전용 설정 제거, `DISABLE_SERVER_SIDE_CURSORS` 추가 — 브랜치 `v2-postgres`, PR #1
- 로컬 데이터 이전 리허설, 운영 MySQL 덤프(`v1-mysql` 태그를 worktree로 꺼내 실행)
- `loaddata`가 느린 원인 분석(왕복 81ms 측정) → `bulk_create` 배치 적재 스크립트 작성, 원본과 객체 단위 전수 비교
- Vercel 환경변수 교체, PR 머지, 운영 확인(health·조회·Cron 수동 호출·백테스트·대시보드)
- README·ROADMAP 반영

**직접 확인·결정한 것**
- 계획: 1단계를 6일로 늘린 안 확인, 2단계 에이전트 프레임워크를 LangGraph로 결정
- 운영 DB Neon 생성 시 마켓플레이스 약관 동의(카드 등록 없이 무료 플랜 확인), GitHub 토큰에 `workflow` 권한 추가
- 데이터 이전을 `loaddata` 대기 대신 배치 적재로 바꾸는 것 승인
- 로컬·CI PostgreSQL 버전을 운영(Neon 18.6)에 맞춰 18로 결정
- (직접 읽고 확인한 diff·화면이 있으면 여기에 추가)
