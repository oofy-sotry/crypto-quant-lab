import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """테스트끼리 캐시 결과가 섞이지 않도록 매 테스트 전에 비운다."""
    cache.clear()
    yield
