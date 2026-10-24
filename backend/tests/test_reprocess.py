import threading
from datetime import date

import pytest
from django.db import connection, transaction

from market.models import Asset
from market.reprocess import lock_days

DAY = date(2026, 10, 20)


def get_asset(symbol):
    # transaction=True 테스트는 pytest-django가 맨 뒤에 몰아 돌리고, 앞선 transaction=True 테스트가
    # 끝날 때 테이블을 비워 마이그레이션이 넣은 시드 종목이 없을 수 있다.
    return Asset.objects.get_or_create(symbol=symbol, defaults={"name": symbol})[0]


@pytest.fixture
def btc():
    return get_asset("KRW-BTC")


def hold_lock_in_other_connection(asset, start, end):
    """다른 DB 연결(스레드)에서 락을 잡고 있게 한다. 돌려준 release()를 부르면 풀린다."""
    locked, release = threading.Event(), threading.Event()

    def worker():
        try:
            with transaction.atomic():
                assert lock_days(asset, start, end)
                locked.set()
                release.wait(timeout=10)
        finally:
            connection.close()  # 스레드마다 연결이 따로 생기므로 직접 닫는다

    thread = threading.Thread(target=worker)
    thread.start()
    assert locked.wait(timeout=10)

    def finish():
        release.set()
        thread.join()

    return finish


@pytest.mark.django_db(transaction=True)
def test_lock_days_rejects_overlapping_period_and_frees_after_commit(btc):
    finish = hold_lock_in_other_connection(btc, DAY, DAY.replace(day=22))
    try:
        with transaction.atomic():
            assert lock_days(btc, DAY.replace(day=22), DAY.replace(day=25)) is False  # 22일 겹침
        with transaction.atomic():
            assert lock_days(btc, DAY.replace(day=23), DAY.replace(day=25)) is True  # 안 겹침
        eth = get_asset("KRW-ETH")
        with transaction.atomic():
            assert lock_days(eth, DAY, DAY) is True  # 다른 종목
    finally:
        finish()

    with transaction.atomic():
        assert lock_days(btc, DAY, DAY) is True  # 상대 트랜잭션이 끝나면 풀림
