"""Immutable-кеширование хешированных ассетов Nuxt.

WhiteNoise помечает файлы как immutable только когда узнаёт хеш staticfiles-манифеста
Django (STATIC_URL). Фронт лежит в WHITENOISE_ROOT (frontend_build) и под это правило
не попадает, поэтому /_nuxt/* отдавались с дефолтным max-age=60 и перекачивались при
каждом открытии. Имена в /_nuxt/ содержат хеш содержимого (Nuxt), значит кешировать
их можно надолго.
"""
from whitenoise.middleware import WhiteNoiseMiddleware


def is_immutable_nuxt_url(url: str) -> bool:
    """URL относится к хешированным бандлам Nuxt (/_nuxt/...).

    Исключение — /_nuxt/builds/: при включённом experimental.appManifest Nuxt
    пишет туда build-манифест (например, latest.json) стабильным именем без
    хеша содержимого, и его нельзя кешировать навсегда, как обычные бандлы.
    """
    url = url or ""
    return "/_nuxt/" in url and "/_nuxt/builds/" not in url


class ImmutableNuxtWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    def immutable_file_test(self, path, url):
        if is_immutable_nuxt_url(url):
            return True
        return super().immutable_file_test(path, url)
