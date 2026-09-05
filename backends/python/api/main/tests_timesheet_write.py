"""Списание часов идёт через наш бэкенд, а не напрямую из браузера.

Зачем перенос. Часы писались из браузера прямо в Битрикс — $b24.callMethod(
'crm.item.add', …) в task.vue, embedded.vue (создание и «разделение») и
reports/project-report.client.vue. Django об этих записях не знал, поэтому
серверного правила на них не наложить: запрет списания в закрытый месяц жил бы
только в браузере и снимался бы правкой JS.

Что здесь закреплено:
  * запись идёт ключом САМОГО СОТРУДНИКА — иначе перенос обезличил бы
    списания и сломал бы закрытие периодов правами Битрикса;
  * смарт-процесс берётся из серверной конфигурации, а не из тела запроса.
"""

import json
from unittest import mock

from django.test import Client, TestCase

from .models import Bitrix24Account
from .timesheet_write_service import TimesheetWriteError, TimesheetWriteService


class FakeToken:
    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {"result": {"item": {"id": 777}}}

    def call_method(self, method, params):
        self.calls.append((method, params))
        return self.response


class FakeClient:
    def __init__(self, response=None):
        self._bitrix_token = FakeToken(response)


CONFIG = {"sp_entity_type_id": 1058, "fields_mapping": {}}


class TimesheetWriteServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m-write",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.client_stub = FakeClient()

    def _service(self, config=None):
        with mock.patch.object(Bitrix24Account, "client", self.client_stub):
            return TimesheetWriteService(self.account, config if config is not None else CONFIG)

    def test_create_calls_bitrix_and_returns_id(self):
        result = self._service().create({"ufHours": 2})

        self.assertEqual(result, {"status": "success", "id": 777})
        method, params = self.client_stub._bitrix_token.calls[0]
        self.assertEqual(method, "crm.item.add")
        self.assertEqual(params["fields"], {"ufHours": 2})

    def test_entity_type_comes_from_server_config(self):
        """Клиент больше не выбирает смарт-процесс.

        Раньше entityTypeId приезжал из браузера, то есть в теле запроса можно
        было указать ЛЮБОЙ смарт-процесс портала, куда у пользователя есть
        доступ, и писать туда через наше приложение.
        """
        self._service().create({"ufHours": 2})

        _, params = self.client_stub._bitrix_token.calls[0]
        self.assertEqual(params["entityTypeId"], 1058)

    def test_update_passes_id(self):
        result = self._service().update("42", {"ufHours": 3})

        self.assertEqual(result["id"], 42)
        method, params = self.client_stub._bitrix_token.calls[0]
        self.assertEqual(method, "crm.item.update")
        self.assertEqual(params["id"], 42)

    def test_unconfigured_smart_process_is_explicit(self):
        with self.assertRaises(TimesheetWriteError) as ctx:
            self._service({"sp_entity_type_id": 0}).create({"ufHours": 1})
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("не настроен", ctx.exception.message)

    def test_empty_fields_rejected(self):
        for bad in ({}, None, [], "строка"):
            with self.subTest(fields=bad):
                with self.assertRaises(TimesheetWriteError):
                    self._service().create(bad)

    def test_bad_item_id_rejected(self):
        with self.assertRaises(TimesheetWriteError):
            self._service().update("не число", {"ufHours": 1})

    def test_flat_result_id_is_accepted(self):
        """crm.item.add отдаёт result.item.id, но встречается и плоский result.id."""
        self.client_stub = FakeClient({"result": {"id": 555}})
        self.assertEqual(self._service().create({"ufHours": 1})["id"], 555)

    def test_missing_id_does_not_break_response(self):
        self.client_stub = FakeClient({"result": {}})
        self.assertEqual(self._service().create({"ufHours": 1}), {"status": "success", "id": None})


class TimesheetWriteAuthorshipTest(TestCase):
    """Автор записи — тот, кто нажал кнопку, а не приложение.

    Bitrix24Account в этом приложении заводится НА СОТРУДНИКА (unique_together
    по b24_user_id + domain_url, у каждого свои OAuth-токены), и account.client
    ходит его ключом. Если бы приложение ходило общим вебхуком, перенос записи
    на бэкенд обезличил бы все списания: автор в Битриксе всегда равен
    владельцу ключа и не подменяется ничем (проверено шестью способами на
    portal.tvermilk24.ru 28.08.2026). Тест держит это свойство явно.
    """

    def test_write_uses_requesting_account_client(self):
        account_a = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        account_b = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m1",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

        client_a, client_b = FakeClient(), FakeClient()
        with mock.patch.object(Bitrix24Account, "client", client_a):
            TimesheetWriteService(account_a, CONFIG).create({"h": 1})
        with mock.patch.object(Bitrix24Account, "client", client_b):
            TimesheetWriteService(account_b, CONFIG).create({"h": 1})

        self.assertEqual(len(client_a._bitrix_token.calls), 1)
        self.assertEqual(len(client_b._bitrix_token.calls), 1)


class TimesheetWriteEndpointTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=303, is_b24_user_admin=False, member_id="m-ep",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.token = self.account.create_jwt_token()

    def _post(self, path, body):
        return Client().post(
            path,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    @mock.patch("main.views.TimesheetWriteService")
    def test_create_endpoint(self, m_service):
        m_service.return_value.create.return_value = {"status": "success", "id": 900}

        response = self._post("/api/timesheet/create", {"fields": {"h": 1}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 900)
        m_service.return_value.create.assert_called_once_with({"h": 1})

    @mock.patch("main.views.TimesheetWriteService")
    def test_update_endpoint(self, m_service):
        m_service.return_value.update.return_value = {"status": "success", "id": 42}

        response = self._post("/api/timesheet/update", {"id": 42, "fields": {"h": 2}})

        self.assertEqual(response.status_code, 200)
        m_service.return_value.update.assert_called_once_with(42, {"h": 2})

    @mock.patch("main.views.TimesheetWriteService")
    def test_service_error_becomes_clean_response(self, m_service):
        m_service.return_value.create.side_effect = TimesheetWriteError("Не настроено", status=409)

        response = self._post("/api/timesheet/create", {"fields": {"h": 1}})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "Не настроено")

    def test_write_requires_auth(self):
        """Без авторизации записать нельзя. Коды разные и это контракт
        auth_required: нет заголовка — 400, токен негодный — 401."""
        no_header = Client().post(
            "/api/timesheet/create",
            data=json.dumps({"fields": {"h": 1}}),
            content_type="application/json",
        )
        self.assertEqual(no_header.status_code, 400)

        bad_token = Client().post(
            "/api/timesheet/create",
            data=json.dumps({"fields": {"h": 1}}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer не-токен",
        )
        self.assertEqual(bad_token.status_code, 401)

    def test_get_not_allowed(self):
        response = Client().get(
            "/api/timesheet/create",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 405)
