import tempfile
from pathlib import Path

import sentry_sdk

from .base import *  # noqa: F403
from .base import DATABASES, env

DEBUG = False

# Vercel 프록시가 HTTPS를 종료하고 X-Forwarded-Proto 헤더로 원래 스킴을 전달한다.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# 관리형 MySQL(Aiven)은 SSL 연결이 필수다. 서버리스에는 인증서 파일을 둘 곳이 없어서
# 환경변수로 받은 CA 인증서(PEM) 내용을 임시 파일로 써서 사용한다.
DB_SSL_CA = env("DB_SSL_CA", default="")
if DB_SSL_CA:
    ca_path = Path(tempfile.gettempdir()) / "db-ca.pem"
    ca_path.write_text(DB_SSL_CA)
    DATABASES["default"]["OPTIONS"]["ssl"] = {"ca": str(ca_path)}

# 처리되지 않은 예외를 Sentry로 보낸다. DSN이 없으면(로컬에서 prod 설정으로 manage.py를
# 실행할 때 등) 초기화하지 않는다. Django 연동은 sentry-sdk가 자동으로 켠다.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("VERCEL_ENV", default="production"),
        # 무료 플랜 한도를 아끼려고 성능 추적은 끄고 오류만 받는다.
        traces_sample_rate=0.0,
        # 요청자 IP·쿠키 같은 개인정보는 보내지 않는다.
        send_default_pii=False,
    )
