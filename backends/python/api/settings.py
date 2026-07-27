from pathlib import Path
from urllib.parse import urlparse

from config import config

if config.db_type == "mysql":
    import pymysql

    pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = config.jwt_secret
DEBUG = config.debug

VIRTUAL_HOST = (config.app_base_url or "").strip()
if VIRTUAL_HOST and not VIRTUAL_HOST.startswith(("http://", "https://")):
    VIRTUAL_HOST = f"https://{VIRTUAL_HOST}"

parsed_virtual_host = urlparse(VIRTUAL_HOST) if VIRTUAL_HOST else None

default_allowed_hosts = ["localhost", "127.0.0.1"]
if DEBUG:
    default_allowed_hosts.extend(
        [
            "api",
            "api-python",
            "api-php",
            "api-node",
            "frontend",
            "cloudpub",
            "cloudpubFront",
        ]
    )
if parsed_virtual_host and parsed_virtual_host.hostname:
    default_allowed_hosts.append(parsed_virtual_host.hostname)

ALLOWED_HOSTS = sorted(set([*default_allowed_hosts, *config.allowed_hosts]))

CSRF_TRUSTED_ORIGINS = [VIRTUAL_HOST] if VIRTUAL_HOST else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "main",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "main.whitenoise_immutable.ImmutableNuxtWhiteNoiseMiddleware", # WhiteNoise + immutable-кеш для /_nuxt/*
    "main.middleware.RequestLoggingMiddleware",
    "main.middleware.ApiTrailingSlashNormalizeMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wsgi.application"
ASGI_APPLICATION = "asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql" if config.db_type == "mysql" else "django.db.backends.postgresql_psycopg2",
        "NAME": config.db_name,
        "USER": config.db_user,
        "PASSWORD": config.db_password,
        "HOST": config.db_host,
        "PORT": config.db_port,
        "OPTIONS": {
            "connect_timeout": 3,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
STATICFILES_DIRS = [
    BASE_DIR / "frontend_build",
]
# Serve frontend_build at root (for favicon, robots.txt, etc)
WHITENOISE_ROOT = BASE_DIR / "frontend_build"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [] if DEBUG else sorted(set([*CSRF_TRUSTED_ORIGINS, *config.cors_allowed_origins]))

# Безопасный regex для разрешённых доменов Bitrix24.
# Перечислены только реально выданные Bitrix24 TLD/домены второго уровня.
# Точечный список исключает атаки вида «attacker.bitrix24.com.evil.io».
BITRIX24_ORIGIN_REGEX = (
    r"^https://[a-z0-9][a-z0-9-]*\.bitrix24\."
    r"(ru|by|kz|com|de|es|fr|pl|it|in|eu|ua|mx|id|vn|com\.br|com\.tr|co\.uk)$"
)

CORS_ALLOWED_ORIGIN_REGEXES = [] if DEBUG else [BITRIX24_ORIGIN_REGEX]
X_FRAME_OPTIONS = 'ALLOWALL'
XS_SHARING_ALLOWED_METHODS = ['POST', 'GET', 'OPTIONS', 'PUT', 'DELETE']

# Флаг перевода скоупинга данных на portal (этап 3 перестройки мультитенантности).
# По умолчанию False — поведение БИТ-в-БИТ как до спринта 4 (account-скоупинг).
# Включать на проде ТОЛЬКО после backfill + dedupe (см. план sprint-4, Часть B).
USE_PORTAL_SCOPING = config.use_portal_scoping

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "main": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
