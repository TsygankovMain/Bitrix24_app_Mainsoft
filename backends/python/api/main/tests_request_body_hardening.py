"""
Аудит устойчивости 2026-07-28: восемь мест разбирают тело запроса без проверки
типа результата. Общий хелпер `_load_request_json` (views.py) уже возвращает
гарантированный dict у себя — эти восемь мест его не используют и разбирают
тело сами, с той же дырой: `json.loads(...)` успешно возвращает НЕ-объект
(список/число/строку/true/null/[]), и первый же `.get(...)` (или, для
collect_request_data.py, `dict(...)`/`x[key] = ...`) падает.

Тир 1 (утечка сырого текста исключения клиенту через log_errors -> 500
{"error": str(exc)}): timesheet_sync, inn_backfill_apply,
inn_backfill_project_items, export_raw_data.

Тир 2 (исключение уже ловится где-то по пути — клиенту уходит общий текст без
трейса, но статус всё равно 500, хотя виноват клиент): save_configuration,
create_fields, create_mapped_field, collect_request_data.py (двойной
потребитель: rate_limit.py уже защищён своей проверкой isinstance, а
placement-ветка auth_required.py — нет; она попадает в dict(x or {}), что
роняет TypeError/ValueError КОНСТРУКТОРА словаря, отличный от AttributeError
остальных мест, и это ловится общим except Exception в auth_required.py —
без утечки, но 500 вместо 400).

Фикс единообразен по приёму (после разбора проверяем isinstance(..., dict)),
но НЕ единообразен по итоговому статусу — решение принято отдельно на каждом
месте и объясняется в докстринге соответствующего класса ниже.

Матрица тел — ровно шесть форм из отчёта аудита. Все шесть парсятся как валидный
JSON, ни одна не является объектом. [1,2,3]/42/"hello"/true — истинные значения,
ломали ВСЕ восемь мест ещё до этого фикса. null/[] — ложные значения; часть мест
(collect_request_data.py: `params or {}`) случайно гасила именно их «подушкой
из ложных значений», но не гасила truthy-значения; часть мест (все семь
остальных) не имеет такой подушки вовсе и падала на null/[] тоже. Тестируем все
шесть форм везде — как регресс-сеть, а не только там, где было историческое
падение.
"""
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from .models import Bitrix24Account
from .utils.decorators.collect_request_data import collect_request_data

# Ровно шесть форм из отчёта аудита.
MALFORMED_BODIES = {
    "list": [1, 2, 3],
    "number": 42,
    "string": "hello",
    "bool_true": True,
    "null": None,
    "empty_list": [],
}

# Подстроки, которые не должны появляться в ответе клиенту (Тир 1): сырой текст
# исключения Python вместо человеко-читаемого сообщения.
_LEAK_MARKERS = (
    "object has no attribute",
    "Traceback",
    "cannot convert dictionary",
    "is not iterable",
    "dictionary update sequence",
    "NoneType",
)


def _make_account(domain_url: str, *, b24_user_id: int = 1) -> Bitrix24Account:
    return Bitrix24Account.objects.create(
        b24_user_id=b24_user_id,
        member_id=f"member_{b24_user_id}_{domain_url}",
        domain_url=domain_url,
        status="active",
        application_version=1,
        is_b24_user_admin=True,
        is_master_account=False,
    )


def _auth_header(account: Bitrix24Account) -> str:
    return f"Bearer {account.create_jwt_token()}"


def _assert_no_exception_leak(testcase, response):
    text = response.content.decode("utf-8", errors="replace")
    for marker in _LEAK_MARKERS:
        testcase.assertNotIn(
            marker, text,
            f"response body leaks raw Python exception text ({marker!r}): {text!r}",
        )


# ---------------------------------------------------------------------------
# Тир 1 — утечка сырого текста исключения (views.py)
# ---------------------------------------------------------------------------

class TimesheetSyncMalformedBodyTest(TestCase):
    """POST /api/sync-timesheets: `json.loads(request.body or "{}").get("date_from")`
    без проверки типа. До фикса — 500 с сырым текстом AttributeError.

    Решение: пустой словарь (не 400). Тело здесь — необязательное сужение по
    датам ("scoped"-режим отчёта); отсутствие date_from/date_to уже штатно
    означает "обычный синк по расписанию" (тот же смысл, что и при {} или
    вообще пустом теле). Нет причин отличать "прислали мусор" от "не прислали
    ничего" — оба должны просто запустить обычный синк."""

    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_malformed_bodies_no_longer_500(self, _cfg):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-ts-sync-{label}.bitrix24.ru")
                # Аккаунт уже "синкан только что" -> код уходит в fresh-гейт до
                # TimesheetSyncService.sync_all/refresh_writeoff_stats (не нужно
                # мокать реальный поход в Bitrix для этого теста).
                account.last_timesheet_synced_at = timezone.now()
                account.save(update_fields=["last_timesheet_synced_at"])
                resp = Client().post(
                    "/api/sync-timesheets",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 200,
                    f"body={value!r} must behave like {{}} (200 fresh), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)
                self.assertEqual(resp.json().get("status"), "fresh")

    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 1, "fields_mapping": {}})
    def test_control_empty_object_gives_the_same_shape(self, _cfg):
        account = _make_account("portal-ts-sync-control.bitrix24.ru")
        account.last_timesheet_synced_at = timezone.now()
        account.save(update_fields=["last_timesheet_synced_at"])
        resp = Client().post(
            "/api/sync-timesheets", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "fresh")


class InnBackfillApplyMalformedBodyTest(TestCase):
    """POST /api/inn-backfill/apply: перехват оборачивает только
    `json.loads(...)`; `body.get("items", [])` вызывается уже СНАРУЖИ try/except.
    До фикса — 500 с сырым текстом AttributeError.

    Решение: честный 400. Пользователь явно выбрал карточки и нажал "применить
    ИНН" — запись в Bitrix (crm.item.update) необратима на их стороне. Молча
    подставить {} означало бы ответить как на "карточки не выбраны" — что
    технически верно (см. test_control ниже, тот же текст), но лучше явно."""

    def test_malformed_bodies_return_400_not_500(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-inn-apply-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/inn-backfill/apply",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must be a client error (400), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)

    def test_control_empty_object_gives_400_too(self):
        account = _make_account("portal-inn-apply-control.bitrix24.ru")
        resp = Client().post(
            "/api/inn-backfill/apply", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 400)


class InnBackfillProjectItemsMalformedBodyTest(TestCase):
    """POST /api/inn-backfill/project-items: тот же паттерн, что и apply —
    try/except покрывает только разбор JSON, `body.get(...)` вызывается уже
    снаружи (и после похода в ConfigurationService). До фикса — 500 с сырым
    текстом AttributeError. Решение: честный 400 — тот же принцип, что и у
    apply (дозаполнение ИНН, а не read-only просмотр)."""

    @patch("main.views.ConfigurationService.get_configuration_sync",
           return_value={"sp_entity_type_id": 123,
                         "fields_mapping": {"our_inn": "UF_OUR", "client_inn": "UF_CLIENT"}})
    def test_malformed_bodies_return_400_not_500(self, _cfg):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-inn-items-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/inn-backfill/project-items",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must be a client error (400), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)


class ExportRawDataMalformedBodyTest(TestCase):
    """POST /api/export-raw-data: перехват оборачивает только `json.loads(...)`;
    `date_from = body.get("date_from", "")` и соседние `.get(...)` идут уже
    СНАРУЖИ try/except. До фикса — 500 с сырым текстом AttributeError.
    Заодно упрощаем избыточный `except (json.JSONDecodeError, Exception)` до
    `except Exception` — JSONDecodeError и так подкласс Exception.

    Решение: честный 400. Это выгрузка в Excel по явным фильтрам пользователя —
    молча подставленный {} тихо превратил бы "сломанный запрос" в "выгрузку
    всего без фильтров", что удивило бы пользователя гораздо больше, чем
    ошибка."""

    def test_malformed_bodies_return_400_not_500(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-export-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/export-raw-data",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must be a client error (400), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)

    def test_control_empty_object_gives_400_too(self):
        # {} -> date_from/date_to/fields все отсутствуют -> тот же путь, что и
        # раньше (никогда не проходил тип-чек, поведение не меняется), но
        # entity_type_id не настроен в тестовом окружении -> тоже 400, просто
        # с другим текстом. Проверяем только "не 500, не 200 с сырыми данными".
        account = _make_account("portal-export-control.bitrix24.ru")
        resp = Client().post(
            "/api/export-raw-data", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Тир 2 — исключение уже ловится где-то по пути, но статус всё равно 500
# ---------------------------------------------------------------------------

class SaveConfigurationMalformedBodyTest(TestCase):
    """POST /api/configuration/save: проверяет тип вложенного поля `config`,
    но не самого тела — `body.get('config', {})` на non-dict body ловится
    широким `except Exception` (без утечки текста), но отвечает 500 вместо 400.

    Решение: честный 400. save_configuration — операция с побочным эффектом
    (перезаписывает сохранённые настройки приложения); тихая деградация в {}
    выглядела бы как осмысленный запрос "сохранить конфигурацию по умолчанию",
    а не как отказ разобрать мусор — гораздо более опасное молчание, чем у
    create_fields ниже, где отсутствие entityTypeId — это просто "не выбран
    смарт-процесс", а не "сотри мои настройки"."""

    def test_malformed_bodies_return_400_not_500(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-save-cfg-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/configuration/save",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must be a client error (400), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)

    @patch("main.views.ConfigurationService.save_configuration_sync", return_value=None)
    @patch("main.views.ConfigurationService.normalize_configuration_sync", side_effect=lambda cfg: cfg)
    def test_control_empty_object_still_succeeds(self, _normalize_mock, _save_mock):
        """Контроль: {} — валидный (пустой) объект, уже сегодня успешно
        сохраняет конфигурацию по умолчанию. Фикс не должен тронуть эту ветку.
        Bitrix-сервис мокается тем же приёмом, что и в
        tests_reports.py::test_save_configuration_returns_success_when_project_sync_fails
        — сам факт похода в Bitrix здесь не по теме теста."""
        account = _make_account("portal-save-cfg-control.bitrix24.ru")
        resp = Client().post(
            "/api/configuration/save", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "success")


class CreateFieldsMalformedBodyTest(TestCase):
    """POST /api/smart-processes/create-fields: локальный алиас `json_module`
    (обычный grep по `json.loads`/`_load_request_json` его не находит) —
    `body.get('entityTypeId')` без проверки типа тела. До фикса ловится
    широким `except Exception` (без утечки текста), но отвечает 500 вместо 400.

    Решение: пустой словарь (не отдельный 400). entityTypeId и так уже
    обязателен и проверяется явно ("Не указан ID смарт-процесса") — non-dict
    тело просто заводит в ту же самую, уже существующую и уже протестированную
    ветку валидации, без нового сообщения об ошибке и нового кода."""

    def test_malformed_bodies_return_same_400_as_missing_entity_type(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-create-fields-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/smart-processes/create-fields",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must degrade to the same 'missing entityTypeId' 400, "
                    f"got {resp.status_code}: {resp.content!r}",
                )
                self.assertEqual(resp.json().get("error"), "Не указан ID смарт-процесса")
                _assert_no_exception_leak(self, resp)

    def test_control_empty_object_gives_the_same_400(self):
        account = _make_account("portal-create-fields-control.bitrix24.ru")
        resp = Client().post(
            "/api/smart-processes/create-fields", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "Не указан ID смарт-процесса")


class CreateMappedFieldMalformedBodyTest(TestCase):
    """POST /api/smart-processes/create-field: тот же паттерн и то же решение,
    что и create_fields — не найден обычным поиском (локальный алиас
    `json_module`), non-dict тело деградирует в {} и попадает в уже
    существующую проверку "Не указан ID смарт-процесса"."""

    def test_malformed_bodies_return_same_400_as_missing_entity_type(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                account = _make_account(f"portal-create-mapped-{label}.bitrix24.ru")
                resp = Client().post(
                    "/api/smart-processes/create-field",
                    data=json.dumps(value),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=_auth_header(account),
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must degrade to the same 'missing entityTypeId' 400, "
                    f"got {resp.status_code}: {resp.content!r}",
                )
                self.assertEqual(resp.json().get("error"), "Не указан ID смарт-процесса")
                _assert_no_exception_leak(self, resp)

    def test_control_empty_object_gives_the_same_400(self):
        account = _make_account("portal-create-mapped-control.bitrix24.ru")
        resp = Client().post(
            "/api/smart-processes/create-field", data=json.dumps({}), content_type="application/json",
            HTTP_AUTHORIZATION=_auth_header(account),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "Не указан ID смарт-процесса")


class CollectRequestDataMalformedBodyTest(TestCase):
    """utils/decorators/collect_request_data.py: `request.data = params or {}`
    гасит только ЛОЖНЫЕ non-dict значения (None, [], 0, "", False) — истинный
    non-dict (непустой список, ненулевое число, непустая строка, true)
    проходит насквозь как request.data. Юнит-тест самого декоратора, в обход
    HTTP — фиксирует контракт напрямую: request.data обязан быть словарём при
    любом входе.

    Решение: пустой словарь. Это разделяемый декоратор для GET/POST-параметров
    у множества эндпоинтов; { } уже сегодня штатный смысл "тело не задано" —
    как и у уже починенного `_load_request_json`."""

    def _collected_data(self, raw_body):
        @collect_request_data
        def _probe(request):
            return request.data

        request = RequestFactory().post("/x", data=raw_body, content_type="application/json")
        return _probe(request)

    def test_valid_object_passes_through_unchanged(self):
        result = self._collected_data(json.dumps({"a": 1, "b": [1, 2, 3], "c": None}))
        self.assertEqual(result, {"a": 1, "b": [1, 2, 3], "c": None})

    def test_malformed_bodies_become_empty_dict(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                result = self._collected_data(json.dumps(value))
                self.assertEqual(result, {})


class AuthRequiredPlacementBranchMalformedBodyTest(TestCase):
    """POST /api/getToken БЕЗ заголовка Authorization: `auth_required` уходит в
    OAuth placement-ветку и зовёт `_normalize_oauth_placement_payload(request.data)`,
    которая делает `dict(raw_payload or {})`. На непустом non-dict request.data
    это не вызов метода словаря, а отказ САМОГО КОНСТРУКТОРА dict() —
    TypeError ([1,2,3]/42/true) или ValueError ("hello") вместо AttributeError
    остальных семи мест. Он ловится широким `except Exception` в
    auth_required.py (утечки текста исключения нет), но отвечает 500 вместо
    честных 400 — ветка редкая (работает только для запросов БЕЗ Bearer-
    токена — get_token как раз такой), но рабочая, живая.

    Корень — в collect_request_data.py (см. класс выше, тот же `params or {}`),
    фикс применяется там же. Этот тест проверяет наблюдаемый эффект через
    реальный эндпоинт, а не патчит внутренности auth_required."""

    def setUp(self):
        # LocMemCache переживает между тестами в общем прогоне (см. остальные
        # rate_limit-тесты в tests_security_ratelimit.py) — get_token лимитирован
        # 10 запросами/60с на (ip, domain) снаружи auth_required.
        cache.clear()

    def test_malformed_bodies_no_longer_500(self):
        for label, value in MALFORMED_BODIES.items():
            with self.subTest(label=label):
                resp = Client().post(
                    "/api/getToken",
                    data=json.dumps(value),
                    content_type="application/json",
                    REMOTE_ADDR="203.0.113.55",
                )
                self.assertEqual(
                    resp.status_code, 400,
                    f"body={value!r} must be a client error (400), got {resp.status_code}: {resp.content!r}",
                )
                _assert_no_exception_leak(self, resp)

    def test_control_empty_object_gives_the_same_400_shape(self):
        resp = Client().post(
            "/api/getToken", data=json.dumps({}), content_type="application/json",
            REMOTE_ADDR="203.0.113.55",
        )
        self.assertEqual(resp.status_code, 400)
