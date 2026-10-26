import threading

import pytest
from django.core.cache import cache
from django.db import connection, transaction

from market.reprocess import lock_days


@pytest.fixture(autouse=True)
def clear_cache():
    """테스트끼리 캐시 결과가 섞이지 않도록 매 테스트 전에 비운다."""
    cache.clear()
    yield


@pytest.fixture
def hold_lock():
    """다른 DB 연결(스레드)에서 (종목, 날짜) 재처리 락을 잡고 있게 하는 함수를 준다.

    hold(asset, start, end)는 락을 잡은 뒤 돌아오고, 돌려준 finish()를 부르면 풀린다.
    transaction=True 테스트에서 써야 한다(다른 연결이 테스트 트랜잭션 밖의 데이터를 봐야 하므로).
    """

    def hold(asset, start, end):
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

    return hold
