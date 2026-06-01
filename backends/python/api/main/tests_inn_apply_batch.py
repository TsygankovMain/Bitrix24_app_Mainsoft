"""
Автономные тесты метода InnBackfillService.apply (без сети и БД).

Проверяет:
  (a) 60 валидных элементов → 2 чанка (50 + 10), call_batch вызван 2 раза
  (b) элементы без bitrix_id или без fields пропускаются
  (c) ключи из result_error → failed, остальные → updated
  (d) при исключении call_batch → фолбэк на per-element crm.item.update
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ─── Изолируем модуль от Django / b24pysdk / config ────────────────────────
# Делаем это ДО первого импорта inn_backfill_service — подменяем
# тяжёлые зависимости заглушками прямо в sys.modules.

_DJANGO_STUBS = [
    'django', 'django.db', 'django.db.models',
    'django.utils', 'django.utils.timezone',
    'config', 'jwt',
    'b24pysdk',
    'b24pysdk.bitrix_api', 'b24pysdk.bitrix_api.credentials',
    'b24pysdk.bitrix_api.events', 'b24pysdk.error',
    'b24pysdk.utils', 'b24pysdk.utils.functional',
]

for _name in _DJANGO_STUBS:
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock()

# Лёгкие заглушки для прямых зависимостей сервиса.
# Используем специальные фиктивные имена, чтобы не конфликтовать
# с реальным пакетом api.main на диске.
_PKG_NAME = '_test_inn_pkg'
_MOD_NAME = f'{_PKG_NAME}.inn_backfill_service'

_pkg = types.ModuleType(_PKG_NAME)
_pkg.__path__ = ['api/main']
_pkg.__package__ = _PKG_NAME
sys.modules[_PKG_NAME] = _pkg

_pbs = types.ModuleType(f'{_PKG_NAME}.project_board_service')
_pbs.ProjectCardService = MagicMock
sys.modules[f'{_PKG_NAME}.project_board_service'] = _pbs

_pbs_shared = types.ModuleType(f'{_PKG_NAME}.project_board_shared')
_pbs_shared.get_project_card_queryset = MagicMock(return_value=[])
sys.modules[f'{_PKG_NAME}.project_board_shared'] = _pbs_shared

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    _MOD_NAME,
    'api/main/inn_backfill_service.py',
    submodule_search_locations=[],
)
_mod = _ilu.module_from_spec(_spec)
_mod.__package__ = _PKG_NAME
sys.modules[_MOD_NAME] = _mod
setattr(_pkg, 'inn_backfill_service', _mod)   # нужно для patch() по строке
_spec.loader.exec_module(_mod)

InnBackfillService = _mod.InnBackfillService
MAX_APPLY_BATCH = _mod.MAX_APPLY_BATCH

# Путь для patch() — используем полное имя в sys.modules
_TIME_PATCH = f'{_MOD_NAME}.time.sleep'


# ─── Вспомогательные функции ────────────────────────────────────────────────

def make_service(field_our='UF_CRM_OUR_INN', field_client='UF_CRM_CLIENT_INN',
                 entity_type_id=1048):
    client = MagicMock()
    account = MagicMock()
    config = {
        'sp_entity_type_id': entity_type_id,
        'fields_mapping': {
            'our_inn': field_our,
            'client_inn': field_client,
        },
    }
    return InnBackfillService(client=client, account=account, config=config)


def make_items(n, our_inn='7701234567', client_inn='7709876543'):
    """n валидных items с последовательными bitrix_id 1..n."""
    return [{'bitrix_id': str(i + 1), 'our_inn': our_inn, 'client_inn': client_inn}
            for i in range(n)]


def batch_ok_response(keys):
    """Мок-ответ call_batch: все ключи успешны."""
    return {
        'result': {
            'result': {k: {'result': True} for k in keys},
            'result_error': {},
        }
    }


# ─── Тесты (a): чанкирование ────────────────────────────────────────────────

class TestApplyBatching(unittest.TestCase):

    def test_60_items_two_chunks(self):
        """60 элементов → 2 чанка (50+10), call_batch вызван ровно 2 раза."""
        svc = make_service()
        items = make_items(60)

        captured_methods = []

        def fake_call_batch(methods, halt=False):
            captured_methods.append(dict(methods))
            return batch_ok_response(list(methods.keys()))

        svc.client._bitrix_token.call_batch.side_effect = fake_call_batch

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(svc.client._bitrix_token.call_batch.call_count, 2,
                         'call_batch должен быть вызван ровно 2 раза')
        self.assertEqual(len(captured_methods[0]), 50, 'Первый чанк — 50 элементов')
        self.assertEqual(len(captured_methods[1]), 10, 'Второй чанк — 10 элементов')
        self.assertEqual(result['updated'], 60)
        self.assertEqual(result['failed'], [])
        self.assertFalse(result['truncated'])

    def test_sleep_between_chunks_not_before_first(self):
        """sleep должен вызываться ровно 1 раз — между первым и вторым чанком."""
        svc = make_service()
        items = make_items(60)

        svc.client._bitrix_token.call_batch.side_effect = (
            lambda methods, halt=False: batch_ok_response(list(methods.keys()))
        )

        with patch(_TIME_PATCH) as mock_sleep:
            svc.apply(items)

        self.assertEqual(mock_sleep.call_count, 1,
                         'sleep вызывается ровно один раз — только между чанками')

    def test_no_sleep_for_single_chunk(self):
        """При одном чанке sleep не должен вызываться."""
        svc = make_service()
        items = make_items(5)

        svc.client._bitrix_token.call_batch.side_effect = (
            lambda methods, halt=False: batch_ok_response(list(methods.keys()))
        )

        with patch(_TIME_PATCH) as mock_sleep:
            svc.apply(items)

        mock_sleep.assert_not_called()


# ─── Тесты (b): пропуск невалидных элементов ────────────────────────────────

class TestApplySkipsInvalidItems(unittest.TestCase):

    def _run(self, items_input, field_our='UF_CRM_OUR_INN', field_client='UF_CRM_CLIENT_INN'):
        svc = make_service(field_our=field_our, field_client=field_client)
        captured = []

        svc.client._bitrix_token.call_batch.side_effect = (
            lambda m, halt=False: captured.append(dict(m)) or batch_ok_response(list(m.keys()))
        )

        with patch(_TIME_PATCH):
            result = svc.apply(items_input)
        return result, captured

    def test_no_bitrix_id(self):
        items = [
            {'bitrix_id': None, 'our_inn': '1234567890'},  # нет id
            {'bitrix_id': '2', 'our_inn': '9876543210'},   # валидный
        ]
        result, captured = self._run(items)
        self.assertEqual(result['updated'], 1)
        self.assertEqual(len(captured), 1)
        self.assertIn('2', captured[0])

    def test_no_fields_empty_strings(self):
        """Пустые строки our_inn/client_inn → fields пустой → пропуск."""
        items = [
            {'bitrix_id': '1', 'our_inn': '', 'client_inn': ''},   # пустые
            {'bitrix_id': '2', 'our_inn': '9876543210'},            # валидный
        ]
        result, captured = self._run(items)
        self.assertEqual(result['updated'], 1)
        self.assertIn('2', captured[0])

    def test_missing_inn_keys(self):
        """Отсутствуют ключи our_inn/client_inn → fields пустой → пропуск."""
        items = [
            {'bitrix_id': '1'},                           # нет ключей ИНН
            {'bitrix_id': '2', 'our_inn': '1234567890'},  # валидный
        ]
        result, captured = self._run(items)
        self.assertEqual(result['updated'], 1)

    def test_empty_list(self):
        result, captured = self._run([])
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['failed'], [])
        self.assertFalse(result['truncated'])
        self.assertEqual(captured, [])

    def test_unmapped_field_valid_via_other(self):
        """client_inn не замаплен (''), но our_inn есть — элемент валиден."""
        items = [{'bitrix_id': '5', 'our_inn': '1234567890', 'client_inn': '9876543210'}]
        result, captured = self._run(items, field_our='UF_OUR', field_client='')
        self.assertEqual(result['updated'], 1)
        key = list(captured[0].keys())[0]
        _, params = captured[0][key]
        self.assertIn('UF_OUR', params['fields'])
        # Пустой ключ '' не должен попасть в fields
        self.assertNotIn('', params['fields'])


# ─── Тесты (c): разбор ответа батча ────────────────────────────────────────

class TestApplyResultParsing(unittest.TestCase):

    def test_partial_errors(self):
        """Часть ключей в result_error → попадают в failed, остальные → updated."""
        svc = make_service()
        items = make_items(3)  # bitrix_id: '1', '2', '3'

        svc.client._bitrix_token.call_batch.side_effect = lambda methods, halt=False: {
            'result': {
                'result': {'1': {'result': True}, '3': {'result': True}},
                'result_error': {'2': 'Запись не найдена'},
            }
        }

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(result['updated'], 2)
        self.assertEqual(len(result['failed']), 1)
        self.assertEqual(result['failed'][0]['bitrix_id'], '2')
        self.assertIn('не найдена', result['failed'][0]['error'])

    def test_all_errors(self):
        svc = make_service()
        items = make_items(2)

        svc.client._bitrix_token.call_batch.side_effect = lambda methods, halt=False: {
            'result': {
                'result': {},
                'result_error': {'1': 'Error A', '2': 'Error B'},
            }
        }

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(result['updated'], 0)
        self.assertEqual(len(result['failed']), 2)

    def test_result_shape_unchanged(self):
        """Форма возвращаемого словаря: status, updated, failed, truncated."""
        svc = make_service()
        items = make_items(1)

        svc.client._bitrix_token.call_batch.side_effect = (
            lambda m, halt=False: batch_ok_response(list(m.keys()))
        )

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertIn('status', result)
        self.assertIn('updated', result)
        self.assertIn('failed', result)
        self.assertIn('truncated', result)
        self.assertEqual(result['status'], 'success')
        self.assertIsInstance(result['updated'], int)
        self.assertIsInstance(result['failed'], list)
        self.assertIsInstance(result['truncated'], bool)

    def test_truncated_flag(self):
        """Более MAX_APPLY_BATCH элементов → truncated=True, обработано ровно MAX_APPLY_BATCH."""
        svc = make_service()
        items = make_items(MAX_APPLY_BATCH + 5)

        processed_ids = []

        def fake_call_batch(methods, halt=False):
            processed_ids.extend(methods.keys())
            return batch_ok_response(list(methods.keys()))

        svc.client._bitrix_token.call_batch.side_effect = fake_call_batch

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertTrue(result['truncated'])
        self.assertEqual(len(processed_ids), MAX_APPLY_BATCH)
        self.assertEqual(result['updated'], MAX_APPLY_BATCH)


# ─── Тесты (d): фолбэк при исключении call_batch ────────────────────────────

class TestApplyFallback(unittest.TestCase):

    def test_fallback_on_batch_exception_all_succeed(self):
        """Исключение call_batch → все элементы чанка проходят через call_method."""
        svc = make_service()
        items = make_items(3)

        svc.client._bitrix_token.call_batch.side_effect = RuntimeError('Network timeout')
        svc.client._bitrix_token.call_method.return_value = {'result': True}

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(result['updated'], 3)
        self.assertEqual(result['failed'], [])
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 3)

    def test_fallback_partial_failure(self):
        """Фолбэк: часть элементов успешна, часть — нет."""
        svc = make_service()
        items = make_items(3)  # ids: '1', '2', '3'

        svc.client._bitrix_token.call_batch.side_effect = ConnectionError('Timeout')

        def fake_call_method(method, params):
            if params['id'] == 2:
                raise ValueError('Элемент заблокирован')
            return {'result': True}

        svc.client._bitrix_token.call_method.side_effect = fake_call_method

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(result['updated'], 2)
        self.assertEqual(len(result['failed']), 1)
        self.assertEqual(result['failed'][0]['error'], 'Элемент заблокирован')

    def test_fallback_chunk2_exception_chunk1_ok(self):
        """Чанк1 OK через batch, чанк2 выбрасывает → чанк2 идёт через fallback call_method."""
        svc = make_service()
        items = make_items(55)  # 50 + 5

        call_n = [0]

        def fake_call_batch(methods, halt=False):
            call_n[0] += 1
            if call_n[0] == 1:
                return batch_ok_response(list(methods.keys()))
            raise RuntimeError('Second chunk failed')

        svc.client._bitrix_token.call_batch.side_effect = fake_call_batch
        svc.client._bitrix_token.call_method.return_value = {'result': True}

        with patch(_TIME_PATCH):
            result = svc.apply(items)

        self.assertEqual(result['updated'], 55)
        self.assertEqual(result['failed'], [])
        # Только 5 элементов из чанка 2 идут через fallback
        self.assertEqual(svc.client._bitrix_token.call_method.call_count, 5)

    def test_no_fallback_called_on_success(self):
        """Если call_batch успешен — call_method не вызывается."""
        svc = make_service()
        items = make_items(10)

        svc.client._bitrix_token.call_batch.side_effect = (
            lambda m, halt=False: batch_ok_response(list(m.keys()))
        )

        with patch(_TIME_PATCH):
            svc.apply(items)

        svc.client._bitrix_token.call_method.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
