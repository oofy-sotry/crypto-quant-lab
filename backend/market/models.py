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
