import tempfile
from pathlib import Path

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
