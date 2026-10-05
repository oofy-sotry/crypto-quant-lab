"""대시보드(Next.js) 캐시 갱신 알림."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


def revalidate_dashboard() -> bool:
    """대시보드에 새 데이터가 들어왔다고 알려 캐시를 바로 만료시킨다.

    대시보드는 API 응답을 몇 분씩 캐시하는데, 만료 뒤 첫 요청에는 이전 값을 준다.
    수집 직후 이걸 부르면 다음 방문자부터 새 데이터를 본다.
    부가 기능이라 실패해도 예외를 내지 않는다
    (수집 결과는 이미 저장됐고, 캐시는 몇 분 뒤 스스로 갱신된다).
    """
    if not settings.DASHBOARD_URL or not settings.DASHBOARD_REVALIDATE_SECRET:
        return False
    try:
        response = requests.post(
            f"{settings.DASHBOARD_URL.rstrip('/')}/api/revalidate",
            headers={"Authorization": f"Bearer {settings.DASHBOARD_REVALIDATE_SECRET}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("대시보드 캐시 갱신 실패: %s", exc)
        return False
    return True
