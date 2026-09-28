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


class RoutedToken:
    """Токен, отвечающий по методу: list — записи дня, get — правимая запись."""

    def __init__(self, day_items=None, current_item=None):
        self.calls = []
        self.day_items = day_items or []
        self.current_item = current_item or {}

    def call_method(self, method, params):
        self.calls.append((method, params))
        if method == "crm.item.list":
            return {"result": {"items": self.day_items}}
        if method == "crm.item.get":
            return {"result": {"item": self.current_item}}
        return {"result": {"item": {"id": 777}}}


class DailyHoursLimitTest(TestCase):
    """Больше 24 часов в сутки на сотрудника — только если портал разрешил.

    Раньше лимит жил во фронте и касался одной записи: три записи по 10 часов
    за день проходили. Теперь считается сумма за день, на сервере.
    """

    MAPPING = {"kolichestvo_chasov": "ufHours", "sotrudnik": "ufEmployee", "data": "ufDate"}

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=304, is_b24_user_admin=False, member_id="m-limit",
            is_master_account=False, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _service(self, token, allow=None):
        config = {"sp_entity_type_id": 1058, "fields_mapping": self.MAPPING}
        if allow is not None:
            config["allow_over_24h_per_day"] = allow
        client = FakeClient()
        client._bitrix_token = token
        with mock.patch.object(Bitrix24Account, "client", client):
            return TimesheetWriteService(self.account, config)

    @staticmethod
    def _methods(token):
        return [method for method, _ in token.calls]

    def test_create_over_limit_rejected_by_default(self):
        token = RoutedToken(day_items=[{"id": 1, "ufHours": 10}, {"id": 2, "ufHours": 10.5}])
        with self.assertRaises(TimesheetWriteError) as ctx:
            self._service(token).create({"ufHours": 4, "ufEmployee": "7", "ufDate": "2026-09-28"})

        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("28.09.2026", ctx.exception.message)
        self.assertIn("20,5", ctx.exception.message)
        self.assertIn("24,5", ctx.exception.message)
        self.assertNotIn("crm.item.add", self._methods(token))

    def test_day_filter_is_employee_and_calendar_day(self):
        token = RoutedToken()
        self._service(token).create({"ufHours": 2, "ufEmployee": ["7"], "ufDate": "2026-09-28T00:00:00+03:00"})

        _, params = token.calls[0]
        self.assertEqual(params["filter"], {
            "ufEmployee": "7", ">=ufDate": "2026-09-28", "<ufDate": "2026-09-29",
        })

    def test_exactly_24_is_allowed(self):
        token = RoutedToken(day_items=[{"id": 1, "ufHours": 20}])
        self._service(token).create({"ufHours": 4, "ufEmployee": "7", "ufDate": "2026-09-28"})
        self.assertIn("crm.item.add", self._methods(token))

    def test_single_entry_over_24_rejected(self):
        """Прежнее фронтовое правило «одна запись не больше 24 ч» сохраняется."""
        token = RoutedToken()
        with self.assertRaises(TimesheetWriteError):
            self._service(token).create({"ufHours": 25, "ufEmployee": "7", "ufDate": "2026-09-28"})

    def test_setting_allows_over_limit_without_extra_calls(self):
        token = RoutedToken(day_items=[{"id": 1, "ufHours": 20}])
        self._service(token, allow="true").create({"ufHours": 30, "ufEmployee": "7", "ufDate": "2026-09-28"})
        self.assertEqual(self._methods(token), ["crm.item.add"])

    def test_string_false_does_not_allow(self):
        """app.option хранит строки: 'false' не должно включать настройку."""
        token = RoutedToken()
        with self.assertRaises(TimesheetWriteError):
            self._service(token, allow="false").create({"ufHours": 25, "ufEmployee": "7", "ufDate": "2026-09-28"})

    def test_update_excludes_itself_from_day_sum(self):
        token = RoutedToken(
            day_items=[{"id": 2, "ufHours": 16}],
            current_item={"id": 5, "ufHours": 4, "ufEmployee": 7, "ufDate": "2026-09-28T00:00:00+03:00"},
        )
        self._service(token).update(5, {"ufHours": 8})

        list_params = next(params for method, params in token.calls if method == "crm.item.list")
        self.assertEqual(list_params["filter"]["!id"], 5)
        self.assertIn("crm.item.update", self._methods(token))

    def test_update_that_adds_hours_over_limit_rejected(self):
        token = RoutedToken(
            day_items=[{"id": 2, "ufHours": 16}],
            current_item={"id": 5, "ufHours": 4, "ufEmployee": 7, "ufDate": "2026-09-28"},
        )
        with self.assertRaises(TimesheetWriteError):
            self._service(token).update(5, {"ufHours": 9})
        self.assertNotIn("crm.item.update", self._methods(token))

    def test_reducing_update_passes_even_when_day_already_over(self):
        """Разделение записи шлёт только часы, и их становится меньше.

        День, где лимит уже превышен старыми данными, не должен запирать
        правку — иначе такую запись не исправить вовсе.
        """
        token = RoutedToken(
            day_items=[{"id": 2, "ufHours": 30}],
            current_item={"id": 5, "ufHours": 6, "ufEmployee": 7, "ufDate": "2026-09-28"},
        )
        self._service(token).update(5, {"ufHours": 3})

        self.assertEqual(self._methods(token), ["crm.item.get", "crm.item.update"])

    def test_move_to_another_day_checks_new_day(self):
        token = RoutedToken(
            day_items=[{"id": 2, "ufHours": 22}],
            current_item={"id": 5, "ufHours": 4, "ufEmployee": 7, "ufDate": "2026-09-27"},
        )
        with self.assertRaises(TimesheetWriteError):
            self._service(token).update(5, {"ufHours": 4, "ufDate": "2026-09-28"})

    def test_unmapped_fields_skip_check(self):
        token = RoutedToken(day_items=[{"id": 1, "ufHours": 30}])
        service = self._service(token)
        service.config["fields_mapping"] = {"kolichestvo_chasov": "ufHours"}
        service.create({"ufHours": 30, "ufEmployee": "7", "ufDate": "2026-09-28"})
        self.assertEqual(self._methods(token), ["crm.item.add"])

    def test_russian_date_format_is_understood(self):
        token = RoutedToken()
        self._service(token).create({"ufHours": 1, "ufEmployee": "7", "ufDate": "28.09.2026"})
        self.assertEqual(token.calls[0][1]["filter"][">=ufDate"], "2026-09-28")
