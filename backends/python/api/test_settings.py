from settings import *  # noqa: F401,F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",
    }
}

STATICFILES_DIRS = []

# В прод-настройках кэш лежит в таблице БД (см. комментарий у CACHES в
# settings.py). Таблицу создаёт команда createcachetable, а не миграция, поэтому
# в тестовой БД её нет. Тестам общий между процессами кэш и не нужен — прогон
# однопроцессный, — а поведение самого бэкенда это код Django, не наш.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Сравнение по подстроке, а не по полному пути класса: раньше здесь стояло
# сравнение с голой строкой "whitenoise.middleware.WhiteNoiseMiddleware", и после
# замены в settings.py на main.whitenoise_immutable.ImmutableNuxtWhiteNoiseMiddleware
# фильтр молча перестал совпадать — WhiteNoise оставался в эффективном MIDDLEWARE
# тестового прогона (см. main.tests_static_immutable.TestEnvironmentMiddlewareIsolationTest).
MIDDLEWARE = [item for item in MIDDLEWARE if "WhiteNoiseMiddleware" not in item]
