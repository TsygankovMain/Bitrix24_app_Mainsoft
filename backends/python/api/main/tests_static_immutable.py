"""Тесты immutable-кеширования хешированных ассетов Nuxt (/_nuxt/*).

Покрывает main.whitenoise_immutable: is_immutable_nuxt_url() — чистую
функцию классификации URL — и то, что settings.MIDDLEWARE использует
ImmutableNuxtWhiteNoiseMiddleware вместо голого
whitenoise.middleware.WhiteNoiseMiddleware. Без замены класса WhiteNoise
не считает файлы в WHITENOISE_ROOT (frontend_build) хешированными и не
ставит Cache-Control: immutable — см. WhiteNoiseMiddleware.immutable_file_test,
который проверяет только STATIC_URL-префикс через staticfiles-манифест.
"""
import settings as project_settings
from django.test import SimpleTestCase

from .whitenoise_immutable import is_immutable_nuxt_url


class IsImmutableNuxtUrlTest(SimpleTestCase):
    def test_nuxt_js_bundle_is_immutable(self):
        self.assertTrue(is_immutable_nuxt_url("/_nuxt/D_3xNJA9.js"))

    def test_nuxt_css_bundle_is_immutable(self):
        self.assertTrue(is_immutable_nuxt_url("/_nuxt/entry.ByiiF8kH.css"))

    def test_index_html_is_not_immutable(self):
        self.assertFalse(is_immutable_nuxt_url("/index.html"))

    def test_root_is_not_immutable(self):
        self.assertFalse(is_immutable_nuxt_url("/"))

    def test_embedded_page_is_not_immutable(self):
        self.assertFalse(is_immutable_nuxt_url("/embedded"))

    def test_empty_string_is_not_immutable(self):
        self.assertFalse(is_immutable_nuxt_url(""))

    def test_none_is_not_immutable(self):
        self.assertFalse(is_immutable_nuxt_url(None))


class MiddlewareConfigurationTest(SimpleTestCase):
    """settings.py должен ссылаться на наш подкласс, а не на голый WhiteNoise —
    иначе immutable_file_test() никогда не увидит /_nuxt/* (см. докстринг модуля)."""

    def test_immutable_middleware_is_configured(self):
        self.assertIn(
            "main.whitenoise_immutable.ImmutableNuxtWhiteNoiseMiddleware",
            project_settings.MIDDLEWARE,
        )

    def test_bare_whitenoise_middleware_is_not_configured(self):
        self.assertNotIn(
            "whitenoise.middleware.WhiteNoiseMiddleware",
            project_settings.MIDDLEWARE,
        )
