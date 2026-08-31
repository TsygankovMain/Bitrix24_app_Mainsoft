"""Устаревшая вкладка не может писать часы.

Инцидент 31.08.2026. После подмены контейнера пользователь с открытым
приложением продолжал работать на СТАРОМ коде: приложение живёт в айфрейме
внутри страницы Битрикса, и жёсткая перезагрузка внешней страницы содержимое
фрейма не обновляет. В логах: у одного сотрудника записи шли через новую ручку
и отвечали 200, а у другого в те же минуты уходили мимо бэкенда напрямую в
Битрикс; помогла только перезагрузка самого фрейма.

Тогда последствий не было — старый код просто писал прежним путём. Но
следующим шагом идёт закрытие месяца, и там та же вкладка списала бы часы в
закрытый период, обойдя проверку. Отсюда серверная сверка версии сборки.
"""

import json
from unittest import mock

from django.test import Client, TestCase

from . import app_version as app_version_module
from .app_version import UNKNOWN_VERSION, get_app_version, is_version_acceptable
from .models import Bitrix24Account


class VersionResolutionTest(TestCase):
    def setUp(self):
        app_version_module._cache.clear()

    def tearDown(self):
        app_version_module._cache.clear()

    def test_version_is_hash_of_built_index(self):
        with mock.patch.object(app_version_module.Path, "read_bytes", return_value=b"<html>build-a</html>"):
            first = get_app_version()

        self.assertNotEqual(first, UNKNOWN_VERSION)
        self.assertEqual(len(first), 12)

        app_version_module._cache.clear()
        with mock.patch.object(app_version_module.Path, "read_bytes", return_value=b"<html>build-b</html>"):
            second = get_app_version()

        self.assertNotEqual(first, second, "новая сборка обязана дать новую версию")

    def test_same_build_gives_same_version(self):
        """Рестарт контейнера с тем же образом версию менять не должен."""
        with mock.patch.object(app_version_module.Path, "read_bytes", return_value=b"<html>same</html>"):
            first = get_app_version()
            app_version_module._cache.clear()
            second = get_app_version()

        self.assertEqual(first, second)

    def test_missing_build_is_not_an_error(self):
        """Бэкенд без собранного фронта — рабочее состояние dev-контура."""
        with mock.patch.object(app_version_module.Path, "read_bytes", side_effect=OSError("нет файла")):
            self.assertEqual(get_app_version(), UNKNOWN_VERSION)

    def test_version_is_cached(self):
        with mock.patch.object(app_version_module.Path, "read_bytes", return_value=b"x") as m_read:
            get_app_version()
            get_app_version()
            get_app_version()

        self.assertEqual(m_read.call_count, 1, "версия читается с диска один раз")


class VersionAcceptanceTest(TestCase):
    def setUp(self):
        app_version_module._cache.clear()
        app_version_module._cache["version"] = "abc123def456"

    def tearDown(self):
        app_version_module._cache.clear()

    def test_matching_version_accepted(self):
        self.assertTrue(is_version_acceptable("abc123def456"))

    def test_stale_version_rejected(self):
        """Ядро защиты: вкладка со старой сборкой писать не может."""
        self.assertFalse(is_version_acceptable("000000000000"))

    def test_absent_version_accepted(self):
        """Вкладка, открытая ДО появления проверки, версию не шлёт.

        Отвергать её значило бы сломать работу всем, кто не перезагрузился в
        момент этой выкатки, ради защиты, которой в их коде ещё нет.
        """
        self.assertTrue(is_version_acceptable(None))
        self.assertTrue(is_version_acceptable(""))

    def test_unknown_server_version_accepts_anything(self):
        app_version_module._cache["version"] = UNKNOWN_VERSION
        self.assertTrue(is_version_acceptable("что угодно"))

    def test_whitespace_is_tolerated(self):
        self.assertTrue(is_version_acceptable("  abc123def456  "))


class WriteRejectsStaleClientTest(TestCase):
    def setUp(self):
        app_version_module._cache.clear()
        app_version_module._cache["version"] = "server-build1"
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-ver",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def tearDown(self):
        app_version_module._cache.clear()

    def _post(self, version=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        if version is not None:
            headers["HTTP_X_APP_VERSION"] = version
        return Client().post(
            "/api/timesheet/create",
            data=json.dumps({"fields": {"h": 1}}),
            content_type="application/json",
            **headers,
        )

    @mock.patch("main.views.TimesheetWriteService")
    def test_stale_client_gets_clear_message(self, m_service):
        response = self._post(version="old-build")

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "app_version_mismatch")
        self.assertIn("Перезагрузите", body["error"])
        m_service.assert_not_called()

    @mock.patch("main.views.TimesheetWriteService")
    def test_current_client_passes(self, m_service):
        m_service.return_value.create.return_value = {"status": "success", "id": 1}

        response = self._post(version="server-build1")

        self.assertEqual(response.status_code, 200)
        m_service.return_value.create.assert_called_once()

    @mock.patch("main.views.TimesheetWriteService")
    def test_client_without_version_passes(self, m_service):
        m_service.return_value.create.return_value = {"status": "success", "id": 1}

        self.assertEqual(self._post().status_code, 200)

    @mock.patch("main.views.TimesheetWriteService")
    def test_update_is_guarded_too(self, m_service):
        response = Client().post(
            "/api/timesheet/update",
            data=json.dumps({"id": 5, "fields": {"h": 1}}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_APP_VERSION="old-build",
        )

        self.assertEqual(response.status_code, 409)
        m_service.assert_not_called()


class PeriodOperationsRejectStaleClientTest(TestCase):
    """Закрытие месяца тоже закрыто проверкой версии.

    Сначала проверка стояла только на списании часов, и этого было мало:
    закрытие и переоткрытие необратимы и решают, что уйдёт клиенту в счёт.
    Вкладка со старым кодом могла закрыть месяц по правилам, которых на
    сервере уже нет.
    """

    def setUp(self):
        app_version_module._cache.clear()
        app_version_module._cache["version"] = "server-build1"
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-ver-period",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def tearDown(self):
        app_version_module._cache.clear()

    def _post(self, path, body, version="old-build"):
        return Client().post(
            path, data=json.dumps(body), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_APP_VERSION=version,
        )

    def test_close_rejects_stale_client(self):
        response = self._post("/api/periods/close", {"year": 2026, "month": 8})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "app_version_mismatch")

    def test_reopen_rejects_stale_client(self):
        response = self._post(
            "/api/periods/reopen", {"year": 2026, "month": 8, "reason": "правка"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "app_version_mismatch")

    def test_bulk_close_rejects_stale_client(self):
        response = self._post(
            "/api/periods/close-bulk", {"until_year": 2026, "until_month": 8},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "app_version_mismatch")

    def test_fix_rejects_stale_client(self):
        response = self._post(
            "/api/periods/fix",
            {"year": 2026, "month": 8, "code": "diverged_project"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "app_version_mismatch")

    def test_current_client_is_not_blocked_by_the_guard(self):
        """Свежая вкладка проходит гейт версии.

        Ответ при этом может быть каким угодно по существу операции — важно
        лишь, что отказ не по версии.
        """
        response = self._post(
            "/api/periods/close", {"year": 2026, "month": 8}, version="server-build1",
        )

        body = response.json() if response.status_code != 200 else {}
        self.assertNotEqual(body.get("code"), "app_version_mismatch")


class AppVersionEndpointTest(TestCase):
    def setUp(self):
        app_version_module._cache.clear()
        app_version_module._cache["version"] = "endpoint-build"

    def tearDown(self):
        app_version_module._cache.clear()

    def test_returns_version_without_auth(self):
        """Фронт спрашивает версию до получения JWT — авторизации быть не должно."""
        response = Client().get("/api/app-version")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"version": "endpoint-build"})
