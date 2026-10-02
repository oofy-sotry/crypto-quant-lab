from .base import *  # noqa: F403

DEBUG = False

# Vercel 프록시가 HTTPS를 종료하고 X-Forwarded-Proto 헤더로 원래 스킴을 전달한다.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
