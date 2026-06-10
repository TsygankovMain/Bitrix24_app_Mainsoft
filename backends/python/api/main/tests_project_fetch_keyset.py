"""
Автономные тесты keyset-пагинации fetch_project_sp_items.
Без сети, без БД — только unittest.mock.

Запуск:
  python3 backends/python/api/main/tests_project_fetch_keyset.py
  # или из backends/python:
  python3 api/main/tests_project_fetch_keyset.py
"""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Шаг 1. Стабы внешних зависимостей (до любого импорта сервиса)
# ---------------------------------------------------------------------------

def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# b24pysdk
_b24 = _stub("b24pysdk")
_b24.Client = object

# django
_django = _stub("django")
_django.setup = lambda: None

_db = _stub("django.db")
_db_models = _stub("django.db.models")
_db_models.Q = object
_db.models = _db_models

_utils = _stub("django.utils")
_tz = _stub("django.utils.timezone")
_tz.now = lambda: datetime(2024, 1, 1, tzinfo=dt_timezone.utc)
_tz.localdate = lambda: datetime(2024, 1, 1).date()
_utils.timezone = _tz

_conf = _stub("django.conf")
_settings_stub = types.SimpleNamespace(USE_PORTAL_SCOPING=False)
_conf.settings = _settings_stub

# Local sub-modules (заглушки, чтобы не тянуть реальные пакеты)
_stub("api")
_stub("api.main")
_stub("api.main.bitrix_data_access")
_stub("api.main.configuration_service")
_stub("api.main.models")
_stub("api.main.project_board_service")
_stub("api.main.project_board_shared")
_stub("api.main.stage_automation_service")

sys.modules["api.main.models"].Bitrix24Account = object
sys.modules["api.main.models"].ProjectCard = MagicMock()
sys.modules["api.main.models"].TimesheetItem = MagicMock()

sys.modules["api.main.bitrix_data_access"].BitrixDataService = MagicMock()
sys.modules["api.main.configuration_service"].ConfigurationService = MagicMock()
sys.modules["api.main.project_board_service"].ProjectCardService = MagicMock()

_shared = sys.modules["api.main.project_board_shared"]
_shared.PROJECT_STAGE_IN_WORK = "in_work"
_shared.PROJECT_STAGE_NEW = "new"
_shared.build_local_project_groups = MagicMock(return_value=[])
_shared.ensure_project_card_schema = MagicMock(return_value=True)
_shared.get_project_card_queryset = MagicMock(return_value=[])
_shared.invalidate_project_runtime_caches = MagicMock()

sys.modules["api.main.stage_automation_service"].ProjectStageAutomationService = MagicMock()

# Загружаем tenant_scoping через importlib (нужен project_sync_service после правок 4.3)
_TENANT_SCOPING_FILE = Path(__file__).with_name("tenant_scoping.py")
_ts_spec = importlib.util.spec_from_file_location("api.main.tenant_scoping", _TENANT_SCOPING_FILE)
_ts_module = importlib.util.module_from_spec(_ts_spec)
sys.modules["api.main.tenant_scoping"] = _ts_module
_ts_spec.loader.exec_module(_ts_module)

# ---------------------------------------------------------------------------
# Шаг 2. Загружаем project_sync_service напрямую через importlib
#         (избегаем конфликта реальных __init__.py в пакете api/main/)
# ---------------------------------------------------------------------------
_SERVICE_FILE = Path(__file__).with_name("project_sync_service.py")
_spec = importlib.util.spec_from_file_location(
    "api.main.project_sync_service", _SERVICE_FILE
)
_module = importlib.util.module_from_spec(_spec)
sys.modules["api.main.project_sync_service"] = _module
_spec.loader.exec_module(_module)

ProjectSyncService = _module.ProjectSyncService


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_service() -> ProjectSyncService:
    """Создаёт экземпляр сервиса с мок-клиентом без вызова __init__."""
    svc = ProjectSyncService.__new__(ProjectSyncService)
    svc.client = MagicMock()
    svc.account = MagicMock()
    svc.card_service = MagicMock()
    return svc


def _make_items(id_start: int, count: int) -> list:
    """Генерирует список сырых элементов с последовательными id."""
    return [{"id": str(id_start + i), "title": f"Project {id_start + i}"} for i in range(count)]


def _pages_side_effect(pages: list):
    """
    Возвращает side_effect для call_method — по очереди отдаёт страницы.
    pages — список списков элементов; лишние вызовы → пустой список.
    """
    it = iter(pages)

    def _se(method: str, payload: dict):
        assert method == "crm.item.list", f"unexpected method: {method}"
        try:
            batch = next(it)
        except StopIteration:
            batch = []
        return {"result": {"items": batch}}

    return _se


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestFetchProjectSpItemsKeyset(unittest.TestCase):

    # ------------------------------------------------------------------
    # (a) Keyset обходит все элементы по разу и завершается
    # ------------------------------------------------------------------

    def test_full_keyset_traversal_120_items(self):
        """120 элементов (id 1..120) → 3 страницы 50/50/20 → 120 результатов."""
        svc = _make_service()
        page1 = _make_items(1, 50)    # id 1..50
        page2 = _make_items(51, 50)   # id 51..100
        page3 = _make_items(101, 20)  # id 101..120

        svc.client._bitrix_token.call_method.side_effect = _pages_side_effect(
            [page1, page2, page3]
        )

        result = svc.fetch_project_sp_items(entity_type_id=42)

        self.assertEqual(len(result), 120, "Должно вернуться ровно 120 элементов")
        ids = [r["id"] for r in result]
        self.assertEqual(len(ids), len(set(ids)), "Элементы не должны дублироваться")
        # page3 < 50 → break, 4-й вызов не нужен
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 3)

    def test_keyset_cursor_advances_correctly(self):
        """Курсор >id должен сдвигаться на max(id) предыдущей пачки."""
        svc = _make_service()
        calls_log = []

        def _se(method, payload):
            calls_log.append(dict(payload))
            if len(calls_log) == 1:
                return {"result": {"items": _make_items(1, 50)}}   # max id = 50
            elif len(calls_log) == 2:
                return {"result": {"items": _make_items(51, 10)}}  # max id = 60, len<50 → stop
            return {"result": {"items": []}}

        svc.client._bitrix_token.call_method.side_effect = _se

        result = svc.fetch_project_sp_items(entity_type_id=10)

        self.assertEqual(len(result), 60)
        self.assertEqual(len(calls_log), 2)

        # Первый вызов: start=-1, >id=0, order={"id":"ASC"}
        self.assertEqual(calls_log[0]["start"], -1)
        self.assertEqual(calls_log[0]["filter"][">id"], 0)
        self.assertEqual(calls_log[0]["order"], {"id": "ASC"})

        # Второй вызов: курсор = 50 (max id первой пачки)
        self.assertEqual(calls_log[1]["start"], -1)
        self.assertEqual(calls_log[1]["filter"][">id"], 50)

    # ------------------------------------------------------------------
    # (b) updated_since: фильтр содержит >id И >updatedTime
    # ------------------------------------------------------------------

    def test_incremental_filter_contains_both_keys(self):
        """При updated_since фильтр содержит >id и >updatedTime."""
        svc = _make_service()
        captured_filters = []

        def _se(method, payload):
            captured_filters.append(dict(payload["filter"]))
            return {"result": {"items": _make_items(1, 5)}}  # 5 < 50 → stop

        svc.client._bitrix_token.call_method.side_effect = _se

        since = datetime(2024, 6, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
        result = svc.fetch_project_sp_items(entity_type_id=42, updated_since=since)

        self.assertEqual(len(result), 5)
        self.assertEqual(len(captured_filters), 1)

        filt = captured_filters[0]
        self.assertIn(">id", filt, "Фильтр должен содержать >id")
        self.assertIn(">updatedTime", filt, "Фильтр должен содержать >updatedTime")
        self.assertEqual(filt[">updatedTime"], since.isoformat())
        self.assertEqual(filt[">id"], 0)

    def test_no_updated_time_without_since(self):
        """Без updated_since — >updatedTime в фильтре отсутствует."""
        svc = _make_service()
        captured_filters = []

        def _se(method, payload):
            captured_filters.append(dict(payload["filter"]))
            return {"result": {"items": _make_items(1, 3)}}

        svc.client._bitrix_token.call_method.side_effect = _se

        svc.fetch_project_sp_items(entity_type_id=42)

        self.assertEqual(len(captured_filters), 1)
        self.assertNotIn(">updatedTime", captured_filters[0])
        self.assertIn(">id", captured_filters[0])

    # ------------------------------------------------------------------
    # (c) Фолбэк инкремент → полный при исключении
    # ------------------------------------------------------------------

    def test_fallback_on_incremental_exception(self):
        """При ошибке в инкрементальном запросе — фолбэк на полный синк."""
        svc = _make_service()
        call_count = [0]

        def _se(method, payload):
            call_count[0] += 1
            if ">updatedTime" in payload.get("filter", {}):
                raise RuntimeError("incremental not supported")
            return {"result": {"items": _make_items(1, 3)}}

        svc.client._bitrix_token.call_method.side_effect = _se

        since = datetime(2024, 6, 1, tzinfo=dt_timezone.utc)
        result = svc.fetch_project_sp_items(entity_type_id=42, updated_since=since)

        self.assertEqual(call_count[0], 2, "Должно быть 2 вызова: 1 бросает, 2 успешен")
        self.assertEqual(len(result), 3)

    def test_fallback_resets_last_id_and_accumulated_items(self):
        """После фолбэка last_id=0 и накопленные items сбрасываются."""
        svc = _make_service()
        calls = []

        def _se(method, payload):
            calls.append(dict(payload["filter"]))
            if ">updatedTime" in payload["filter"]:
                raise RuntimeError("fail incremental")
            return {"result": {"items": _make_items(1, 2)}}

        svc.client._bitrix_token.call_method.side_effect = _se

        since = datetime(2024, 5, 1, tzinfo=dt_timezone.utc)
        result = svc.fetch_project_sp_items(entity_type_id=7, updated_since=since)

        # Полный запрос должен идти с >id=0
        full_filter = calls[1]
        self.assertEqual(full_filter[">id"], 0, "После фолбэка last_id должен быть 0")
        self.assertNotIn(">updatedTime", full_filter, ">updatedTime не должен быть в полном запросе")
        # Только 2 элемента из полного синка (инкрементальные не накапливались)
        self.assertEqual(len(result), 2)

    def test_no_fallback_without_incremental_mode(self):
        """Без updated_since исключение пробрасывается наружу."""
        svc = _make_service()
        svc.client._bitrix_token.call_method.side_effect = RuntimeError("network error")

        with self.assertRaises(RuntimeError):
            svc.fetch_project_sp_items(entity_type_id=42)

    # ------------------------------------------------------------------
    # (d) Защита от зацикливания при неменяющемся max id
    # ------------------------------------------------------------------

    def test_anti_loop_cursor_does_not_advance(self):
        """Если пачка возвращает id <= last_id — цикл прерывается."""
        svc = _make_service()
        call_count = [0]

        def _se(method, payload):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"result": {"items": _make_items(1, 50)}}   # max id=50, last_id→50
            else:
                # Снова те же id 1..50 → batch_max_id=50 <= last_id=50 → break
                return {"result": {"items": _make_items(1, 50)}}

        svc.client._bitrix_token.call_method.side_effect = _se

        result = svc.fetch_project_sp_items(entity_type_id=42)

        self.assertEqual(call_count[0], 2, "Должно быть ровно 2 вызова")
        # items.extend вызывается до break, поэтому 100 элементов
        self.assertEqual(len(result), 100)

    def test_anti_loop_empty_batch(self):
        """Пустая пачка → немедленная остановка после первого вызова."""
        svc = _make_service()
        svc.client._bitrix_token.call_method.return_value = {"result": {"items": []}}

        result = svc.fetch_project_sp_items(entity_type_id=42)

        self.assertEqual(result, [])
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 1)

    def test_anti_loop_all_items_have_invalid_id(self):
        """Если все id нечисловые — batch_max_id = last_id → break после первой пачки."""
        svc = _make_service()
        bad_items = [{"id": "abc", "title": "bad"}, {"title": "no id at all"}]
        svc.client._bitrix_token.call_method.return_value = {"result": {"items": bad_items}}

        result = svc.fetch_project_sp_items(entity_type_id=42)

        # Элементы добавляются (extend перед break), курсор не двигается → break
        self.assertEqual(len(result), 2)
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 1)

    # ------------------------------------------------------------------
    # Проверка неизменности select и сигнатуры
    # ------------------------------------------------------------------

    def test_select_fields_exact(self):
        """select должен быть точно ["id","title","createdTime","updatedTime","*","UF_*"]."""
        svc = _make_service()
        captured_selects = []

        def _se(method, payload):
            captured_selects.append(list(payload.get("select", [])))
            return {"result": {"items": _make_items(1, 1)}}

        svc.client._bitrix_token.call_method.side_effect = _se

        svc.fetch_project_sp_items(entity_type_id=99)

        self.assertEqual(len(captured_selects), 1)
        self.assertEqual(
            captured_selects[0],
            ["id", "title", "createdTime", "updatedTime", "*", "UF_*"],
        )

    def test_return_type_is_list(self):
        """Метод должен возвращать list (сигнатура List[Dict])."""
        svc = _make_service()
        svc.client._bitrix_token.call_method.return_value = {"result": {"items": []}}
        result = svc.fetch_project_sp_items(entity_type_id=1)
        self.assertIsInstance(result, list)

    def test_entity_type_id_passed_correctly(self):
        """entityTypeId передаётся как int."""
        svc = _make_service()
        captured = []

        def _se(method, payload):
            captured.append(payload.get("entityTypeId"))
            return {"result": {"items": []}}

        svc.client._bitrix_token.call_method.side_effect = _se
        svc.fetch_project_sp_items(entity_type_id="123")  # строка → должна стать int

        self.assertEqual(captured[0], 123)
        self.assertIsInstance(captured[0], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
