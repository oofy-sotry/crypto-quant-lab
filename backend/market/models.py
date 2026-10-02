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
        ordering = ["asset", "date"]
        constraints = [
            models.UniqueConstraint(fields=["asset", "date"], name="uniq_candle_asset_date"),
        ]

    def __str__(self):
        return f"{self.asset} {self.date}"
