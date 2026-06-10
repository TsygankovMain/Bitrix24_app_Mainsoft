"""
Автономные тесты _fetch_paginated (unittest.mock, без сети / БД).

Запуск:
    cd backends/python
    python3 -m pytest api/main/tests_fetch_paginated_batch.py -v
  или
    python3 -m unittest api.main.tests_fetch_paginated_batch -v
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Минимальные заглушки модулей, от которых зависит project_board_service
# ---------------------------------------------------------------------------

def _make_stub_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# Django
django_mod = _make_stub_module("django")
django_mod.setup = lambda: None

cache_mock = MagicMock()
cache_mock.get.return_value = None

django_core = _make_stub_module("django.core")
django_cache_mod = _make_stub_module("django.core.cache")
django_cache_mod.cache = cache_mock

django_db = _make_stub_module("django.db")
django_db.ProgrammingError = Exception

# django.conf.settings нужен реальному tenant_scoping (этап 3 мультитенантности),
# который импортирует project_board_service. Флаг OFF → account-скоупинг.
django_conf = _make_stub_module("django.conf")
django_conf.settings = types.SimpleNamespace(USE_PORTAL_SCOPING=False)

django_db_models = _make_stub_module("django.db.models")
for _attr in ("Case", "F", "FloatField", "Max", "Sum", "Value", "When"):
    setattr(django_db_models, _attr, MagicMock())

django_utils = _make_stub_module("django.utils")
django_utils_tz = _make_stub_module("django.utils.timezone")
django_utils_tz.now = MagicMock()
django_utils_tz.localdate = MagicMock()
django_utils_tz.get_current_timezone = MagicMock()

# b24pysdk
b24pysdk_mod = _make_stub_module("b24pysdk")
b24pysdk_mod.Client = MagicMock()

# Внутренние зависимости проекта
for _dep in (
    "api.main.bitrix_data_access",
    "api.main.configuration_service",
    "api.main.models",
    "api.main.project_board_shared",
):
    dep_mod = _make_stub_module(_dep)
    # stub для всего, что импортируется из project_board_shared
    dep_mod.BITRIX_REFERENCE_CACHE_TTL = 300
    dep_mod.HOMEPAGE_CACHE_TTL = 300
    dep_mod.PROJECT_AUTO_STAGES = []
    dep_mod.PROJECT_BOARD_CACHE_TTL = 300
    dep_mod.PROJECT_MANUAL_STAGES = []
    dep_mod.PROJECT_STAGE_IN_WORK = "in_work"
    dep_mod.PROJECT_STAGE_NEW = "new"
    dep_mod.PROJECT_STAGE_NO_WRITEOFF_30 = "no_writeoff_30"
    dep_mod.PROJECT_STAGE_NO_WRITEOFF_90 = "no_writeoff_90"
    dep_mod.PROJECT_STAGE_ORDER = []
    dep_mod.build_account_cache_key = MagicMock(return_value="key")
    dep_mod.build_local_project_groups = MagicMock(return_value=[])
    dep_mod.ensure_project_card_schema = MagicMock(return_value=True)
    dep_mod.get_project_card_queryset = MagicMock(return_value=MagicMock())
    dep_mod.invalidate_project_runtime_caches = MagicMock()
    dep_mod.BitrixDataService = MagicMock()
    dep_mod.ConfigurationService = MagicMock()
    dep_mod.Bitrix24Account = MagicMock()
    dep_mod.ProjectCard = MagicMock()
    dep_mod.SystemLog = MagicMock()
    dep_mod.TimesheetItem = MagicMock()

# Нужные конкретные имена для from ... import
sys.modules["api.main.bitrix_data_access"].BitrixDataService = MagicMock()
sys.modules["api.main.configuration_service"].ConfigurationService = MagicMock()

# ---------------------------------------------------------------------------
# Теперь можно импортировать тестируемый модуль
# ---------------------------------------------------------------------------
from api.main.project_board_service import ProjectCardService  # noqa: E402


# ---------------------------------------------------------------------------
# Вспомогательная фабрика
# ---------------------------------------------------------------------------

def _make_service() -> ProjectCardService:
    """Создаёт ProjectCardService с замоканным client."""
    account = MagicMock()
    account.domain_url = "test.bitrix24.ru"
    account.pk = 1

    client = MagicMock()
    service = ProjectCardService.__new__(ProjectCardService)
    service.client = client
    service.account = account
    return service


def _bx_response(items, total=None, next_val=None):
    """Строит минимальный ответ Bitrix24 call_method."""
    resp: dict = {"result": items}
    if total is not None:
        resp["total"] = total
    if next_val is not None:
        resp["next"] = next_val
    return resp


def _bx_batch_response(pages: dict) -> dict:
    """
    Строит ответ call_batches.
    pages: {key: [item, ...]}
    """
    return {"result": {"result": {k: v for k, v in pages.items()}}}


# ---------------------------------------------------------------------------
# Тест-кейсы
# ---------------------------------------------------------------------------

class TestFetchPaginatedBatch(unittest.TestCase):

    # -----------------------------------------------------------------------
    # (a) total ≤ 50: только один call_method, call_batches не вызывается
    # -----------------------------------------------------------------------
    def test_single_page_no_batch(self):
        svc = _make_service()
        items_page1 = [{"ID": str(i)} for i in range(1, 11)]  # 10 записей

        svc.client._bitrix_token.call_method.return_value = _bx_response(
            items_page1, total=10
        )

        result = svc._fetch_paginated("crm.company.list", {"select": ["ID", "TITLE"]})

        self.assertEqual(len(result), 10)
        self.assertEqual(result, items_page1)

        # Ровно один вызов call_method
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 1)
        # call_batches не вызван вообще
        svc.client._bitrix_token.call_batches.assert_not_called()

    # -----------------------------------------------------------------------
    # (b) total = 130: батч строится для офсетов 50 и 100, все items собраны
    # -----------------------------------------------------------------------
    def test_batch_three_pages(self):
        svc = _make_service()

        # Страница 0: 50 элементов, total=130
        page0 = [{"ID": str(i)} for i in range(1, 51)]
        # Страницы 50 и 100 по 50 и 30 элементов соответственно
        page50 = [{"ID": str(i)} for i in range(51, 101)]
        page100 = [{"ID": str(i)} for i in range(101, 131)]

        svc.client._bitrix_token.call_method.return_value = _bx_response(
            page0, total=130
        )
        svc.client._bitrix_token.call_batches.return_value = _bx_batch_response(
            {"p50": page50, "p100": page100}
        )

        result = svc._fetch_paginated("crm.requisite.list", {"filter": {"ENTITY_TYPE_ID": 4}})

        # Все 130 элементов собраны
        self.assertEqual(len(result), 130)
        expected_ids = [str(i) for i in range(1, 131)]
        self.assertEqual([r["ID"] for r in result], expected_ids)

        # call_method вызван ровно один раз (start=0)
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 1)
        called_params = svc.client._bitrix_token.call_method.call_args[0][1]
        self.assertEqual(called_params["start"], 0)

        # call_batches вызван ровно один раз
        self.assertEqual(svc.client._bitrix_token.call_batches.call_count, 1)
        batch_arg = svc.client._bitrix_token.call_batches.call_args[0][0]
        # Батч содержит именно офсеты 50 и 100
        self.assertIn("p50", batch_arg)
        self.assertIn("p100", batch_arg)
        self.assertNotIn("p0", batch_arg)

        # Проверяем start в каждом методе батча
        self.assertEqual(batch_arg["p50"][1]["start"], 50)
        self.assertEqual(batch_arg["p100"][1]["start"], 100)

    # -----------------------------------------------------------------------
    # (c) исключение в call_batches → фолбэк на offset-цикл
    # -----------------------------------------------------------------------
    def test_fallback_on_batch_exception(self):
        svc = _make_service()

        # Страница 0: 50 элементов, total=100 → попытается батч
        page0 = [{"ID": str(i)} for i in range(1, 51)]
        page50 = [{"ID": str(i)} for i in range(51, 101)]

        # call_method: первый вызов (start=0) вернёт page0+total=100;
        # последующие вызовы фолбэка: start=0 → page0, start=50 → page50
        call_method_responses = [
            # первый вызов батч-пути
            _bx_response(page0, total=100),
            # фолбэк start=0
            _bx_response(page0, total=100, next_val=50),
            # фолбэк start=50
            _bx_response(page50, total=100),
        ]
        svc.client._bitrix_token.call_method.side_effect = call_method_responses

        # call_batches выбрасывает исключение
        svc.client._bitrix_token.call_batches.side_effect = RuntimeError("network timeout")

        result = svc._fetch_paginated("crm.company.list", {"select": ["ID"]})

        # Фолбэк собрал все 100 элементов
        self.assertEqual(len(result), 100)
        expected_ids = [str(i) for i in range(1, 51)] + [str(i) for i in range(51, 101)]
        self.assertEqual([r["ID"] for r in result], expected_ids)

        # call_batches был вызван (попытка) и упал
        svc.client._bitrix_token.call_batches.assert_called_once()

        # call_method вызван 3 раза: 1 батч-путь + 2 фолбэк
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 3)

    # -----------------------------------------------------------------------
    # (d) батч вернул 0 items при total>50 → фолбэк
    # -----------------------------------------------------------------------
    def test_fallback_on_zero_batch_items(self):
        svc = _make_service()

        page0 = [{"ID": str(i)} for i in range(1, 51)]
        page50 = [{"ID": str(i)} for i in range(51, 101)]

        # Первый call_method (батч-путь) + два фолбэковых вызова
        svc.client._bitrix_token.call_method.side_effect = [
            _bx_response(page0, total=100),
            _bx_response(page0, total=100, next_val=50),
            _bx_response(page50, total=100),
        ]
        # call_batches возвращает пустой результат
        svc.client._bitrix_token.call_batches.return_value = _bx_batch_response({})

        result = svc._fetch_paginated("crm.company.list", {"select": ["ID"]})

        self.assertEqual(len(result), 100)
        # call_batches был вызван
        svc.client._bitrix_token.call_batches.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
