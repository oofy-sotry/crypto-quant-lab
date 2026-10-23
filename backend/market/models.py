from django.db import models


class Asset(models.Model):
    symbol = models.CharField(max_length=20, unique=True)  # 업비트 마켓 코드, 예: KRW-BTC
    name = models.CharField(max_length=50)
    # 상장 첫 거래일(KST). 이 날짜 이전은 결측으로 보지 않는다. 백필 시 가장 오래된 일봉으로 채운다.
    listed_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["symbol"]

    def __str__(self):
        return self.symbol


class DailyCandle(models.Model):
    # 가격은 정확히 저장해야 하므로 float 대신 Decimal을 쓴다.
    # BTC(1억 원대)부터 소수점 가격 코인까지 담도록 정수 16자리 + 소수 8자리.
    PRICE = {"max_digits": 24, "decimal_places": 8}
    # 누적 거래대금은 1천억 원을 넘으므로 자릿수를 더 둔다.
    AMOUNT = {"max_digits": 30, "decimal_places": 8}

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="candles")
    date = models.DateField()  # KST 기준 거래일 (업비트 일봉은 KST 09:00에 시작)
    open = models.DecimalField(**PRICE)
    high = models.DecimalField(**PRICE)
    low = models.DecimalField(**PRICE)
    close = models.DecimalField(**PRICE)
    volume = models.DecimalField(**AMOUNT)  # 거래량 (코인 개수)
    value = models.DecimalField(**AMOUNT)  # 거래대금 (원)
    # 오늘 일봉은 아직 마감 전이라 값이 계속 바뀐다. 마감된 봉만 백테스트에 쓴다.
    is_final = models.BooleanField(default=False)
    collected_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_id", "date"]  # asset으로 정렬하면 Asset 테이블 JOIN이 붙는다
        constraints = [
            models.UniqueConstraint(fields=["asset", "date"], name="uniq_candle_asset_date"),
        ]

    def __str__(self):
        return f"{self.asset} {self.date}"


class MinuteCandle(models.Model):
    """업비트 1분봉. 거래가 없는 분은 업비트가 주지 않으므로 빈 분이 정상적으로 있다."""

    # 외래키 기본 인덱스(asset_id 단독)는 끈다. unique(asset_id, ts) 인덱스의 첫 컬럼이 asset_id라
    # asset_id 조건 조회에도 그대로 쓰인다. 수백만 행에서 중복 인덱스는 용량과 INSERT 비용만 늘린다.
    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="minute_candles", db_index=False
    )
    # 분 시작 시각(UTC). UTC로 두면 date_trunc('day', ts)가 일봉 경계(UTC 00:00)와 맞는다.
    ts = models.DateTimeField()
    open = models.DecimalField(**DailyCandle.PRICE)
    high = models.DecimalField(**DailyCandle.PRICE)
    low = models.DecimalField(**DailyCandle.PRICE)
    close = models.DecimalField(**DailyCandle.PRICE)
    volume = models.DecimalField(**DailyCandle.AMOUNT)
    value = models.DecimalField(**DailyCandle.AMOUNT)

    class Meta:
        ordering = ["asset_id", "ts"]
        # 다른 인덱스는 쿼리별로 측정하면서 추가한다(ROADMAP D5).
        constraints = [
            models.UniqueConstraint(fields=["asset", "ts"], name="uniq_minute_asset_ts"),
        ]

    def __str__(self):
        return f"{self.asset} {self.ts:%Y-%m-%d %H:%M}"


class AggBar(models.Model):
    """분봉을 묶은 집계 봉의 공통 컬럼. 값은 market/aggregates.py가 DB 쿼리로 채운다."""

    # unique(asset_id, bucket) 인덱스가 asset_id 조회도 맡으므로 외래키 단독 인덱스는 끈다
    # (MinuteCandle과 같은 이유).
    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="%(class)ss", db_index=False
    )
    bucket = models.DateTimeField()  # 구간 시작 시각(UTC)
    open = models.DecimalField(**DailyCandle.PRICE)
    high = models.DecimalField(**DailyCandle.PRICE)
    low = models.DecimalField(**DailyCandle.PRICE)
    close = models.DecimalField(**DailyCandle.PRICE)
    volume = models.DecimalField(**DailyCandle.AMOUNT)
    value = models.DecimalField(**DailyCandle.AMOUNT)
    vwap = models.DecimalField(**DailyCandle.PRICE, null=True)  # 거래대금 / 거래량
    # 구간 안 1분 로그수익률의 표본 표준편차(연율화 안 함). 수익률이 2개 미만이면 NULL.
    # 돈이 아니라 통계값이라 float로 둔다.
    volatility = models.FloatField(null=True)
    minute_count = models.PositiveIntegerField()  # 원본 분봉 수 (거래 없는 분은 빠져 있음)
    # 집계 계산 방식이 바뀌면 올린다. 옛 버전으로 남은 행을 찾아 다시 집계할 수 있다.
    agg_version = models.PositiveSmallIntegerField()
    aggregated_at = models.DateTimeField()

    class Meta:
        abstract = True
        ordering = ["asset_id", "bucket"]
        constraints = [
            models.UniqueConstraint(fields=["asset", "bucket"], name="uniq_%(class)s_asset_bucket"),
        ]

    def __str__(self):
        return f"{self.asset} {self.bucket:%Y-%m-%d %H:%M}"


class HourlyBar(AggBar):
    """1시간 집계 봉."""


class DailyAgg(AggBar):
    """분봉으로 만든 일봉(UTC 00:00 시작 = 업비트 일봉 경계). 업비트 일봉과 대조하는 데 쓴다."""


class CollectionRun(models.Model):
    class Trigger(models.TextChoices):
        CRON = "cron", "Vercel Cron"
        BEAT = "beat", "Celery beat"
        MANUAL = "manual", "수동 실행"
        BACKFILL = "backfill", "과거 데이터 백필"

    class Status(models.TextChoices):
        RUNNING = "running", "실행 중"
        SUCCESS = "success", "성공"
        PARTIAL = "partial", "일부 실패"
        FAILED = "failed", "실패"

    trigger = models.CharField(max_length=10, choices=Trigger.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    assets_count = models.PositiveIntegerField(default=0)
    upserted_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.trigger} {self.started_at:%Y-%m-%d %H:%M} {self.status}"


class IntegrityIssue(models.Model):
    class Type(models.TextChoices):
        MISSING = "missing", "결측일"
        OHLC_INVALID = "ohlc_invalid", "OHLC 규칙 위반"
        NON_POSITIVE = "non_positive", "0 이하 가격"
        ZERO_VOLUME = "zero_volume", "거래량 0"
        SPIKE = "spike", "급등락"
        STALE = "stale", "수집 지연"

    class Severity(models.TextChoices):
        ERROR = "error", "오류"
        WARNING = "warning", "경고"

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="issues")
    date = models.DateField()
    type = models.CharField(max_length=20, choices=Type.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    detail = models.JSONField(default=dict)
    detected_run = models.ForeignKey(
        CollectionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="issues"
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # 사람이 확인하고 해결 처리한 사유 (예: "업비트 원본에도 없는 날짜").
    # note가 있으면 다음 검사에서 같은 이슈가 다시 발견돼도 해결 상태를 유지한다.
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "asset_id"]
        constraints = [
            # 검사를 여러 번 돌려도 같은 이슈가 중복으로 쌓이지 않게 한다.
            models.UniqueConstraint(fields=["asset", "date", "type"], name="uniq_issue"),
        ]

    def __str__(self):
        return f"{self.asset} {self.date} {self.type}"
