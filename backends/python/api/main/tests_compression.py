"""Тесты сжатия ответов (django.middleware.gzip.GZipMiddleware, см. settings.MIDDLEWARE).

Хотфикс 2026-07-28: ни один крупный ответ нашего домена (в т.ч. /api/project-board/meta,
~12 МБ) не уезжал сжатым — в MIDDLEWARE не было GZipMiddleware вовсе. Эти тесты гоняют
полный стек middleware через django.test.Client, но на изолированных тестовых view/urlconf,
объявленных прямо в этом модуле (@override_settings(ROOT_URLCONF=__name__)) — без завязки
на бизнес-логику, авторизацию (JWT) и реальные данные конкретного эндпоинта. Так тест
проверяет контракт GZipMiddleware как таковой, а не реализацию отдельной вьюхи.

Покрыты 4 сценария:
  1. крупный ответ сжимается, и распакованное тело совпадает с исходным;
  2. мелкий ответ (< 200 байт) НЕ сжимается — это намеренное поведение Django
     (invoke порог в GZipMiddleware.process_response), а не дефект;
  3. без Accept-Encoding: gzip в запросе ответ остаётся несжатым;
  4. ответ с уже выставленным Content-Encoding (как у WhiteNoise на предсжатых
     .br/.gz файлах — см. main.whitenoise_immutable) повторно не сжимается.
"""
import gzip
import json

from django.http import HttpResponse, JsonResponse
from django.test import SimpleTestCase, override_settings
from django.urls import path


def _large_json_view(request):
    # ~2000 однотипных записей: заведомо больше 200-байтного порога GZipMiddleware
    # и заведомо хорошо сжимается за счёт повторов — компрессия не может "не сработать"
    # из-за случайно невыгодного содержимого.
    payload = {
        "items": [
            {"id": i, "name": f"item-{i}", "note": "x" * 40}
            for i in range(2000)
        ]
    }
    return JsonResponse(payload)


def _short_view(request):
    # 2 байта — гарантированно меньше порога в 200 байт, ниже которого Django
    # намеренно не сжимает: выигрыш не окупает накладные расходы на маленьких ответах.
    return HttpResponse("ok")


def _precompressed_view(request):
    # Имитация ответа WhiteNoise на предсжатый .br-файл: Content-Encoding уже
    # выставлен раздающим статику middleware ДО того, как ответ дойдёт до GZipMiddleware.
    # Тело не является настоящим brotli-потоком — для проверки поведения GZipMiddleware
    # это неважно, важно лишь, что он не должен трогать уже закодированный ответ.
    body = b"already-precompressed-payload" * 20  # > 200 байт
    response = HttpResponse(body, content_type="application/octet-stream")
    response["Content-Encoding"] = "br"
    return response


urlpatterns = [
    path("__compression-tests__/large-json", _large_json_view, name="compression-test-large-json"),
    path("__compression-tests__/short", _short_view, name="compression-test-short"),
    path("__compression-tests__/precompressed", _precompressed_view, name="compression-test-precompressed"),
]


@override_settings(ROOT_URLCONF=__name__)
class GZipMiddlewareTests(SimpleTestCase):
    """Реальный стек MIDDLEWARE из settings.py, прогнанный через django.test.Client."""

    def test_large_response_is_gzip_compressed(self):
        # Базовая (несжатая) версия того же ответа — эталон для сравнения ниже.
        plain = self.client.get("/__compression-tests__/large-json")
        self.assertNotIn("Content-Encoding", plain)
        self.assertGreater(len(plain.content), 200)

        compressed = self.client.get(
            "/__compression-tests__/large-json",
            HTTP_ACCEPT_ENCODING="gzip",
        )

        self.assertEqual(compressed["Content-Encoding"], "gzip")
        self.assertLess(len(compressed.content), len(plain.content))

        decompressed = gzip.decompress(compressed.content)
        self.assertEqual(decompressed, plain.content)
        self.assertEqual(json.loads(decompressed), json.loads(plain.content))

    def test_short_response_is_not_compressed(self):
        # Мелочь не сжимается — так и задумано в Django (порог 200 байт), а не баг.
        response = self.client.get(
            "/__compression-tests__/short",
            HTTP_ACCEPT_ENCODING="gzip",
        )

        self.assertNotIn("Content-Encoding", response)
        self.assertEqual(response.content, b"ok")

    def test_without_accept_encoding_response_stays_uncompressed(self):
        response = self.client.get("/__compression-tests__/large-json")

        self.assertNotIn("Content-Encoding", response)
        self.assertEqual(
            json.loads(response.content)["items"][0],
            {"id": 0, "name": "item-0", "note": "x" * 40},
        )

    def test_already_encoded_response_is_not_recompressed(self):
        expected_body = b"already-precompressed-payload" * 20

        response = self.client.get(
            "/__compression-tests__/precompressed",
            HTTP_ACCEPT_ENCODING="gzip",
        )

        # Content-Encoding остаётся "br" — GZipMiddleware не перезаписал его на "gzip"
        # и не тронул тело, потому что заголовок уже был выставлен выше по стеку.
        self.assertEqual(response["Content-Encoding"], "br")
        self.assertEqual(response.content, expected_body)
