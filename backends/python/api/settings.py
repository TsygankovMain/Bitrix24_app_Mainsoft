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
    # Django проходит response-фазу в порядке, ОБРАТНОМ этому списку: модуль,
    # стоящий выше (раньше), видит ответ позже — последним перед отправкой клиенту.
    # Сжатие обязано быть самым последним преобразованием тела ответа, поэтому
    # GZipMiddleware должен стоять выше всего, что ещё читает или меняет body:
    # ImmutableNuxtWhiteNoiseMiddleware (статика), RequestLoggingMiddleware (пишет
    # response.content как текст в лог — сожми раньше, и туда уедут бинарные
    # gzip-байты вместо читаемого тела), CommonMiddleware, CSRF, messages и т.д.
    # Для статики модуль безвреден: если WhiteNoise уже отдал предсжатый .br/.gz
    # файл, у ответа выставлен Content-Encoding, и GZipMiddleware такой ответ
    # пропускает без повторного сжатия (см. main.tests_compression).
    "django.middleware.gzip.GZipMiddleware",
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

# Кэш общий на процессы, а не локальный.
#
# CACHES не был объявлен вовсе, поэтому Django поднимал LocMemCache — свой в
# КАЖДОМ процессе. При gunicorn --workers 2 это значит, что прогретый кэш видит
# в лучшем случае половина запросов, --max-requests 1000 регулярно обнуляет его
# вместе с воркером, а четыре фоновых цикла sync_all_portals из start.sh — это
# отдельные процессы со своим пустым кэшем, то есть они не переиспользуют вообще
# ничего. При этом кэшем в проекте обёрнуты именно дорогие обращения к Bitrix
# REST (справочник сотрудников, поиск компаний, схема карточки проекта, пресеты
# реквизитов) — около двух десятков мест.
#
# Взята таблица в той же БД, а не Redis: приложение живёт одним контейнером на
# App Platform, отдельного сервиса кэша в контуре нет и заводить его ради этого
# несоразмерно. Промах по кэшу стоит round-trip в Bitrix (сотни миллисекунд),
# попадание из БД — единицы миллисекунд, так что размен очевидный. Если контур
# однажды получит Redis, менять придётся только этот блок.
#
# Таблица создаётся идемпотентной командой createcachetable в start.sh.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 300,
        "OPTIONS": {
            # Записей немного (справочники и схемы), но потолок нужен, чтобы
            # таблица не росла бесконтрольно при всплеске ключей поиска.
            "MAX_ENTRIES": 5000,
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

# Логи приложения идут в ДВА места. console — как и раньше, поток контейнера
# (App Platform, короткая история). db — таблица system_log: только WARNING и
# выше, зато переживает рестарт и доступна через /api/logs/system, не вставая
# из-за терминала.
#
# Порог у db-обработчика отдельный и намеренно выше корневого: на INFO
# приложение пишет каждую страницу синка и каждую нормализацию — десятки тысяч
# строк в сутки, которые таблицу утопят, а диагностике не помогут. WARNING —
# это ровно "что-то пошло не так": проглоченные сбои автопростановки ИНН,
# упавший синк, отказы Битрикса в резолве реквизитов, пропуски планировщика.
# Раньше всё это было только в stdout, а в system_log за месяц лежала ОДНА
# строка (единственное необработанное исключение вьюхи).
#
# django.db.backends не подключаем сознательно: обработчик пишет в ту же БД,
# и её собственные логи создали бы петлю. Реентрантная защита в самом
# обработчике есть, но кормить её лишним трафиком незачем.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
        "db": {
            "class": "main.utils.db_log_handler.DatabaseLogHandler",
            "level": "WARNING",
        },
        # Отдельный обработчик с порогом INFO — только для логгера main.audit.
        # Нужен, потому что порог db намеренно стоит на WARNING (на INFO
        # приложение пишет каждую страницу синка — десятки тысяч строк в
        # сутки), но есть события, которые НЕ являются ошибками и при этом
        # обязаны переживать рестарт и быть видимыми из БД: перенос задачи
        # между проектами, запись часов, сводка резолва отчёта. Без этого
        # обработчика такая диагностика уходила в stdout контейнера и
        # пропадала — на чём я и споткнулся 31.08.2026, добавив её уровнем
        # INFO в общий логгер и не увидев в system_log ни строки.
        "db_audit": {
            "class": "main.utils.db_log_handler.DatabaseLogHandler",
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["console", "db"],
        "level": "INFO",
    },
    "loggers": {
        "main": {
            "handlers": ["console", "db"],
            "level": "INFO",
            "propagate": False,
        },
        # Аудит: события, которые нужны в БД на уровне INFO. Держать их
        # отдельным логгером, а не понижать порог общего db-обработчика —
        # иначе в таблицу польётся весь INFO приложения.
        # propagate=False обязателен: иначе запись поднимется к "main" и
        # продублируется его обработчиками.
        "main.audit": {
            "handlers": ["console", "db_audit"],
            "level": "INFO",
            "propagate": False,
        },
        # Петля: сообщения самого драйвера БД не должны идти в обработчик,
        # который пишет в БД.
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
