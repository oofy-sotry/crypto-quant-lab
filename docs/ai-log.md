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

## 2026-10-23 — 1단계 D2 분봉 수집과 대량 적재

**Claude Code에게 맡긴 것**
- 업비트 분봉 API 실제 호출로 동작 확인(가장 오래된 시점, 거래 없는 분은 안 줌, `to`는 제외 조건)
- `MinuteCandle` 모델(외래키 단독 인덱스 제외), 분봉 조회·페이지 넘김, 배치 upsert, `collect_minutes`·`bench_minute_upsert` 커맨드와 테스트
- 로컬 5종목 × 1년 백필, 배치 크기별 적재 속도 측정
- VM 재부팅으로 백필이 끊긴 뒤 진행 상태 점검(커밋·DB 행 수) → 이어 받기
- 전체 재실행 전후 비교 스크립트(종목별 행 수·기간·값 md5·새 id)

**직접 확인·결정한 것**
- 이어 받기에서 생긴 DOGE 13시간 초과분을 지워 종목 간 범위를 맞추기로 결정
- 이미 하루치로 멱등을 확인했지만, 시간이 걸려도 1년치 전체를 다시 받아 정확히 검증하기로 결정("빠른 것도 중요하지만 정확한 게 중요")
- (직접 읽고 확인한 diff·화면이 있으면 여기에 추가)
