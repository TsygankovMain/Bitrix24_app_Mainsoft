"""
Автономные тесты scoped-ветки TimesheetSyncService.
Запуск: python3 backends/python/api/main/tests_sync_scoped.py
Не требует Django ORM/БД/сети — все зависимости замокированы.
"""
import sys
import os
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Мок Django и зависимостей ДО импорта модуля
# ---------------------------------------------------------------------------

# django.db.transaction
transaction_mod = types.ModuleType("django.db.transaction")
transaction_mod.atomic = lambda f=None: (f if f else lambda fn: fn)
sys.modules["django"] = types.ModuleType("django")
sys.modules["django.db"] = types.ModuleType("django.db")
sys.modules["django.db.transaction"] = transaction_mod
django_utils = types.ModuleType("django.utils")
django_utils.timezone = MagicMock()
sys.modules["django.utils"] = django_utils
sys.modules["django.utils.timezone"] = django_utils.timezone

# b24pysdk
b24pysdk_mod = types.ModuleType("b24pysdk")
b24pysdk_mod.Client = object
sys.modules["b24pysdk"] = b24pysdk_mod

# report_services
report_services_mod = types.ModuleType(
    "main.report_services"
    if "main.report_services" in sys.modules
    else "backends.python.main.report_services"
)


class _FakeDataProcessingService:
    def __init__(self, mapping=None):
        self.mapping = mapping or {"data": "UF_DATE_REFLECTION"}

    def normalize_items(self, items):
        return [{"id_elem": str(item["id"]), "data": "2024-01-01"} for item in items]


# Прокидываем мок-сервис через sys.modules так, чтобы импорт в timesheet_sync_service.py
# нашёл его через относительный импорт (.report_services)
_fake_rs_mod = types.ModuleType("main_report_services_fake")
_fake_rs_mod.DataProcessingService = _FakeDataProcessingService
sys.modules[".report_services"] = _fake_rs_mod

# models
models_mod = types.ModuleType("models_fake")
models_mod.Bitrix24Account = object
_TimesheetItemMock = MagicMock()
models_mod.TimesheetItem = _TimesheetItemMock
sys.modules[".models"] = models_mod

# Вставляем пакет main как sys.modules чтобы relative imports сработали
main_pkg = types.ModuleType("main")
main_pkg.__path__ = []
main_pkg.__package__ = "main"
sys.modules["main"] = main_pkg
sys.modules["main.report_services"] = _fake_rs_mod
sys.modules["main.models"] = models_mod

# ---------------------------------------------------------------------------
# Импортируем сервис напрямую, обходя relative imports через exec
# ---------------------------------------------------------------------------
import importlib.util

_SERVICE_PATH = os.path.join(
    os.path.dirname(__file__),
    "timesheet_sync_service.py",
)


def _load_service():
    """Загружаем модуль, подменяя relative imports на моки."""
    with open(_SERVICE_PATH, "r", encoding="utf-8") as f:
        source = f.read()

    # Заменяем relative imports на прямые ссылки на моки
    source = source.replace("from .models import Bitrix24Account, TimesheetItem", "")
    source = source.replace("from .report_services import DataProcessingService", "")
    source = source.replace("from .tenant_scoping import scope_to_tenant", "")

    mod = types.ModuleType("timesheet_sync_service_test")
    mod.__dict__["Bitrix24Account"] = models_mod.Bitrix24Account
    mod.__dict__["TimesheetItem"] = _TimesheetItemMock
    mod.__dict__["DataProcessingService"] = _FakeDataProcessingService
    # Django stubs
    mod.__dict__["transaction"] = transaction_mod
    mod.__dict__["timezone"] = django_utils.timezone
    mod.__dict__["Client"] = object
    # Стаб scope_to_tenant (этап 3 мультитенантности): автономный тест без Django
    # settings → флаг OFF → account-скоупинг, как предполагают эти тесты.
    mod.__dict__["scope_to_tenant"] = lambda account, *, write=False: {"bitrix24_account": account}
    exec(compile(source, _SERVICE_PATH, "exec"), mod.__dict__)
    return mod


_mod = _load_service()
TimesheetSyncService = _mod.__dict__["TimesheetSyncService"]


# ---------------------------------------------------------------------------
# Хелпер для построения экземпляра сервиса
# ---------------------------------------------------------------------------

def _make_service(mapping=None):
    """Строит TimesheetSyncService с полностью замоканными зависимостями."""
    client = MagicMock()
    account = MagicMock()
    account.pk = 42
    config = {
        "sp_entity_type_id": 177,
        "fields_mapping": mapping or {"data": "UF_DATE_REFLECTION"},
    }
    service = TimesheetSyncService(client, account, config)
    return service


def _items(ids):
    """Создаёт список сырых items с заданными id."""
    return [{"id": i, "UF_DATE_REFLECTION": "2024-01-15", "createdTime": "2024-01-10"} for i in ids]


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestScopedUnion(unittest.TestCase):
    """(a) scoped собирает union двух фильтров и дедуплицирует по id."""

    def setUp(self):
        self.service = _make_service()

    def test_union_deduplication(self):
        """Элементы из обоих фильтров объединяются; дубли по id удаляются."""
        # Фильтр A вернёт id 1,2,3; фильтр B вернёт id 2,3,4 → union: 1,2,3,4
        items_a = _items([1, 2, 3])
        items_b = _items([2, 3, 4])

        # first-page total ≤ 50 → только первая страница для каждого фильтра
        def mock_call_with_retry(method, params):
            filt = params.get("filter", {})
            if ">=UF_DATE_REFLECTION" in filt or ">=createdTime" not in filt:
                # Определяем по наличию поля fdate в фильтре
                if any("UF_DATE_REFLECTION" in k for k in filt):
                    return {"result": {"items": items_a}, "total": 3}
                else:
                    return {"result": {"items": items_b}, "total": 3}
            return {"result": {"items": items_b}, "total": 3}

        def smart_mock(method, params):
            filt = params.get("filter", {})
            if any("UF_DATE_REFLECTION" in k for k in filt):
                return {"result": {"items": items_a}, "total": len(items_a)}
            else:
                return {"result": {"items": items_b}, "total": len(items_b)}

        self.service._call_with_retry = smart_mock
        self.service._save_batch = MagicMock(return_value=[])
        self.service._autofill_inn = MagicMock()
        self.service._delete_scoped_orphans = MagicMock()

        result = self.service._sync_scoped("2024-01-01", "2024-01-31", "UF_DATE_REFLECTION")

        # 4 уникальных элемента (1,2,3,4)
        self.assertEqual(result, 4)

    def test_union_no_duplicates_when_disjoint(self):
        """Если наборы не пересекаются, результат — сумма."""
        items_a = _items([1, 2])
        items_b = _items([3, 4])

        def smart_mock(method, params):
            filt = params.get("filter", {})
            if any("UF_DATE_REFLECTION" in k for k in filt):
                return {"result": {"items": items_a}, "total": 2}
            return {"result": {"items": items_b}, "total": 2}

        self.service._call_with_retry = smart_mock
        self.service._save_batch = MagicMock(return_value=[])
        self.service._autofill_inn = MagicMock()
        self.service._delete_scoped_orphans = MagicMock()

        result = self.service._sync_scoped("2024-01-01", "2024-01-31", "UF_DATE_REFLECTION")
        self.assertEqual(result, 4)


class TestBatchOffsets(unittest.TestCase):
    """(b) при total>50 формируются батч-офсеты 50, 100, ..."""

    def setUp(self):
        self.service = _make_service()

    def test_batch_offsets_generated_correctly(self):
        """total=130 → офсеты 50, 100 (два батч-запроса)."""
        first_page_items = _items(list(range(1, 51)))  # 50 элементов

        def mock_call_with_retry(method, params):
            return {"result": {"items": first_page_items}, "total": 130}

        # call_batches должен получить методы с ключами p50, p100
        captured_methods = {}

        def mock_call_batches(methods, halt=False):
            captured_methods.update(methods)
            # Вернём пустые страницы — нас интересует только то, какие ключи переданы
            fake_sub = {k: {"items": []} for k in methods}
            return {"result": {"result": fake_sub}, "time": {}}

        self.service._call_with_retry = mock_call_with_retry
        self.service.client._bitrix_token.call_batches = mock_call_batches

        self.service._fetch_all_pages_batched({">=UF_DATE_REFLECTION": "2024-01-01"})

        self.assertIn("p50", captured_methods)
        self.assertIn("p100", captured_methods)
        self.assertNotIn("p0", captured_methods)
        self.assertNotIn("p130", captured_methods)

    def test_no_batch_when_total_le_50(self):
        """total≤50 → call_batches не вызывается."""
        items = _items(list(range(1, 11)))

        self.service._call_with_retry = lambda m, p: {"result": {"items": items}, "total": 10}
        self.service.client._bitrix_token.call_batches = MagicMock()

        result = self.service._fetch_all_pages_batched({">=UF_DATE_REFLECTION": "2024-01-01"})

        self.service.client._bitrix_token.call_batches.assert_not_called()
        self.assertEqual(len(result), 10)

    def test_batch_items_collected(self):
        """Элементы из батча добавляются к первой странице."""
        first_page = _items(list(range(1, 51)))
        second_page = _items(list(range(51, 71)))

        self.service._call_with_retry = lambda m, p: {"result": {"items": first_page}, "total": 70}

        def mock_call_batches(methods, halt=False):
            fake_sub = {k: {"items": second_page} for k in methods}
            return {"result": {"result": fake_sub}, "time": {}}

        self.service.client._bitrix_token.call_batches = mock_call_batches

        result = self.service._fetch_all_pages_batched({">=UF_DATE_REFLECTION": "2024-01-01"})
        # 50 первой страницы + 20 из батча
        self.assertEqual(len(result), 70)


class TestScopedFallback(unittest.TestCase):
    """(c) при исключении в scoped-пути происходит фолбэк на полный путь."""

    def setUp(self):
        self.service = _make_service()

    def test_fallback_on_scoped_exception(self):
        """Если _sync_scoped бросает, вызывается _sync_full."""
        self.service._sync_full = MagicMock(return_value=999)
        self.service._sync_scoped = MagicMock(side_effect=RuntimeError("test error"))

        result = self.service.sync_all(date_from="2024-01-01", date_to="2024-01-31")

        self.service._sync_scoped.assert_called_once()
        self.service._sync_full.assert_called_once()
        self.assertEqual(result, 999)

    def test_no_fallback_on_success(self):
        """Если scoped работает успешно, _sync_full не вызывается."""
        self.service._sync_full = MagicMock(return_value=0)
        self.service._sync_scoped = MagicMock(return_value=42)

        result = self.service.sync_all(date_from="2024-01-01", date_to="2024-01-31")

        self.service._sync_full.assert_not_called()
        self.assertEqual(result, 42)

    def test_full_sync_when_no_dates(self):
        """Без дат всегда выполняется полный синк."""
        self.service._sync_full = MagicMock(return_value=100)
        self.service._sync_scoped = MagicMock(return_value=0)

        result = self.service.sync_all()

        self.service._sync_scoped.assert_not_called()
        self.service._sync_full.assert_called_once()
        self.assertEqual(result, 100)

    def test_full_sync_when_partial_dates(self):
        """Если задана только date_from (без date_to) — полный синк."""
        self.service._sync_full = MagicMock(return_value=50)
        self.service._sync_scoped = MagicMock(return_value=0)

        result = self.service.sync_all(date_from="2024-01-01")

        self.service._sync_scoped.assert_not_called()
        self.service._sync_full.assert_called_once()


class TestScopedFilters(unittest.TestCase):
    """Проверяем, что оба фильтра (fdate и createdTime) действительно передаются."""

    def setUp(self):
        self.service = _make_service()

    def test_both_filters_called(self):
        """_fetch_all_pages_batched вызывается ровно дважды с разными фильтрами."""
        calls_filters = []

        def mock_fetch(filter_dict):
            calls_filters.append(dict(filter_dict))
            return []

        self.service._fetch_all_pages_batched = mock_fetch
        self.service._save_batch = MagicMock(return_value=[])
        self.service._autofill_inn = MagicMock()
        self.service._delete_scoped_orphans = MagicMock()

        self.service._sync_scoped("2024-01-01", "2024-01-31", "UF_DATE_REFLECTION")

        self.assertEqual(len(calls_filters), 2)
        # Фильтр A: по полю даты-отражения
        filter_a = calls_filters[0]
        self.assertIn(">=UF_DATE_REFLECTION", filter_a)
        self.assertIn("<=UF_DATE_REFLECTION", filter_a)
        # Фильтр B: по createdTime, только нижняя граница. Верхняя отсекала бы
        # всё созданное сегодня (Битрикс читает дату без времени как начало
        # суток) — см. TestScopedCreatedTimeBoundary.
        filter_b = calls_filters[1]
        self.assertIn(">=createdTime", filter_b)
        self.assertNotIn("<=createdTime", filter_b)


class TestScopedCreatedTimeBoundary(unittest.TestCase):
    """Граница суток в фильтре по createdTime.

    Битрикс сравнивает datetime-поле со строкой-датой без времени как с
    НАЧАЛОМ этих суток. Поэтому верхняя граница вида "<=createdTime: сегодня"
    отсекает всё, что создано сегодня в течение дня, — а это ровно те записи,
    ради которых выборка B и существует: внесённые задним числом за дату
    старше окна. Боевой случай: 31 запись за 01–22.07 внесена 30.07 и не
    доехала до отчёта (см. docs/incidents).
    """

    # Портальная таймзона в тесте фиксирована: важна не она, а то, что у
    # createdTime есть время суток, а у значения фильтра — нет.
    TZ = "+03:00"

    def _bitrix_filter(self, items, filter_dict):
        """Мини-модель crm.item.list: применяет фильтр по правилам Битрикса."""
        def _dt(value):
            text = str(value)
            if len(text) == 10:  # "2026-07-30" -> начало суток
                text = f"{text}T00:00:00{self.TZ}"
            return datetime.fromisoformat(text)

        matched = []
        for item in items:
            ok = True
            for key, expected in filter_dict.items():
                op, field = key[:2], key[2:]
                actual = item.get(field)
                if actual is None:
                    ok = False
                    break
                if op == ">=" and not _dt(actual) >= _dt(expected):
                    ok = False
                    break
                if op == "<=" and not _dt(actual) <= _dt(expected):
                    ok = False
                    break
            if ok:
                matched.append(item)
        return matched

    def test_retroactive_entry_created_today_is_synced(self):
        """Запись, внесённая сегодня за дату старше окна, попадает в синк."""
        date_from, date_to = "2026-07-23", "2026-07-30"
        created_today = f"2026-07-30T15:04:00{self.TZ}"

        portal_items = [
            # Внесена сегодня задним числом: фильтр A её не видит (03.07 вне
            # окна), поймать может только выборка B по createdTime.
            {"id": 20329, "UF_DATE_REFLECTION": "2026-07-03", "createdTime": created_today},
            # Контроль: дата отражения в окне -> проходит фильтром A. Если
            # свалится и она, значит сломан харнесс, а не граница суток.
            {"id": 20303, "UF_DATE_REFLECTION": "2026-07-23", "createdTime": created_today},
        ]

        service = _make_service()
        service._call_with_retry = lambda method, params: {
            "result": {"items": self._bitrix_filter(portal_items, params["filter"])},
            "total": len(self._bitrix_filter(portal_items, params["filter"])),
        }
        saved = []
        service._save_batch = lambda chunk: saved.extend(chunk) or []
        service._autofill_inn = MagicMock()
        service._delete_scoped_orphans = MagicMock()

        service._sync_scoped(date_from, date_to, "UF_DATE_REFLECTION")

        saved_ids = {row["id_elem"] for row in saved}
        self.assertIn(
            "20329", saved_ids,
            "запись, внесённая сегодня за 03.07, не доехала: верхняя граница "
            "по createdTime отсекла всё созданное сегодня",
        )
        self.assertIn("20303", saved_ids, "контрольная запись в окне тоже потерялась")


if __name__ == "__main__":
    unittest.main(verbosity=2)
