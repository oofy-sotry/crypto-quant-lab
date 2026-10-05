from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Vercel Cron이 Authorization: Bearer 헤더로 보내는 값. 비어 있으면 Cron 엔드포인트는 모두 거부한다.
CRON_SECRET = env("CRON_SECRET", default="")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "market",
    "backtest",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # CommonMiddleware보다 앞에 둬야 리다이렉트 응답에도 CORS 헤더가 붙는다.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASE_URL 예: mysql://user:password@host:3306/dbname
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["OPTIONS"] = {"charset": "utf8mb4"}
# 서버리스에서는 요청마다 인스턴스가 바뀔 수 있어 기본값은 커넥션을 재사용하지 않는다.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=0)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    # 요청 횟수 제한은 캐시(Redis)에 기록된다. 서버리스 인스턴스가 여러 개여도 같은 카운터를 쓴다.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "backtest": "20/min",  # 계산이 무거운 백테스트 실행은 더 엄격하게
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# 브라우저에서 API를 직접 부르는 곳(대시보드)만 허용한다. 백테스트 실행은 사용자 브라우저가
# 직접 호출해야 IP별 throttle이 사용자마다 따로 적용된다(대시보드 서버를 거치면 한도를 나눠 씀).
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])
CORS_URLS_REGEX = r"^/api/.*$"

# API 서버 첫 화면(/)에서 보낼 대시보드 주소. 비어 있으면 /는 404.
DASHBOARD_URL = env("DASHBOARD_URL", default="")
# 수집 후 대시보드 캐시를 바로 갱신할 때 쓰는 비밀값(대시보드 REVALIDATE_SECRET과 같은 값). 비어 있으면 호출하지 않는다.
DASHBOARD_REVALIDATE_SECRET = env("DASHBOARD_REVALIDATE_SECRET", default="")

SPECTACULAR_SETTINGS = {
    "TITLE": "crypto-quant-lab API",
    "DESCRIPTION": "업비트 코인 일봉 수집·무결성 검사·백테스트 API",
    "VERSION": "0.1.0",
}
