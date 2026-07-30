"""
Границы периода в выгрузке export_raw_data (views._build_export_date_filter).

Битрикс сравнивает datetime-поле со строкой-датой без времени как с НАЧАЛОМ
этих суток. Поэтому верхняя граница "<=CREATED_TIME: date_to" молча выбрасывала
из выгрузки всё, что создано в последний день выбранного периода: пользователь
просит «по 30.07 включительно», а получает данные по 29.07.

Тот же дефект был в scoped-синке таймшитов (фильтр B по createdTime) — там он
стоил 99.5 ч, не доехавших до отчёта по сотрудникам.

Тесты проверяют ПОВЕДЕНИЕ фильтра — какие записи он пропустит на стороне
Битрикса, — а не его форму: форма может быть любой, лишь бы последний день
периода попадал в выгрузку целиком.
"""
from datetime import datetime

from django.test import SimpleTestCase

from .views import _build_export_date_filter

# Портальная таймзона в тесте фиксирована: важна не она, а то, что у CREATED_TIME
# есть время суток, а у значения фильтра — нет.
TZ = "+03:00"


def _as_dt(value):
    text = str(value)
    if len(text) == 10:  # "2026-07-30" -> начало суток, как это делает Битрикс
        text = f"{text}T00:00:00{TZ}"
    return datetime.fromisoformat(text)


def _passes(crm_filter, item):
    """Мини-модель crm.item.list: пропустит ли фильтр эту запись."""
    for key, expected in crm_filter.items():
        op = key[:2] if key[:2] in (">=", "<=") else key[:1]
        actual = item.get(key[len(op):])
        if actual is None:
            return False
        actual_dt, expected_dt = _as_dt(actual), _as_dt(expected)
        if op == ">=" and not actual_dt >= expected_dt:
            return False
        if op == "<=" and not actual_dt <= expected_dt:
            return False
        if op == ">" and not actual_dt > expected_dt:
            return False
        if op == "<" and not actual_dt < expected_dt:
            return False
    return True


class ExportCreationDateBoundaryTest(SimpleTestCase):
    """date_type='creation' — фильтр по CREATED_TIME (поле со временем)."""

    def _filter(self):
        return _build_export_date_filter("creation", "2026-07-23", "2026-07-30", {})

    def test_item_created_during_last_day_is_included(self):
        """Запись, созданная в последний день периода днём, попадает в выгрузку."""
        item = {"CREATED_TIME": f"2026-07-30T15:04:00{TZ}"}
        self.assertTrue(
            _passes(self._filter(), item),
            "запись за последний день периода отброшена: верхняя граница "
            "читается как начало суток",
        )

    def test_item_created_at_last_midnight_is_included(self):
        """Полночь последнего дня — тоже внутри периода."""
        item = {"CREATED_TIME": f"2026-07-30T00:00:00{TZ}"}
        self.assertTrue(_passes(self._filter(), item))

    def test_item_created_next_day_is_excluded(self):
        """Следующий день за границей периода не захватывается."""
        item = {"CREATED_TIME": f"2026-07-31T00:00:00{TZ}"}
        self.assertFalse(_passes(self._filter(), item))

    def test_item_created_before_period_is_excluded(self):
        """Нижняя граница на месте: вечер предыдущего дня не попадает."""
        item = {"CREATED_TIME": f"2026-07-22T23:59:00{TZ}"}
        self.assertFalse(_passes(self._filter(), item))


class ExportReflectionDateBoundaryTest(SimpleTestCase):
    """date_type='reflection' — поле берётся из маппинга портала."""

    def _filter(self):
        return _build_export_date_filter(
            "reflection", "2026-07-23", "2026-07-30", {"data": "ufCrm6DataOtrazheniya"}
        )

    def test_uses_mapped_field(self):
        """Фильтр строится по полю из fields_mapping, а не по CREATED_TIME."""
        self.assertTrue(all("ufCrm6DataOtrazheniya" in key for key in self._filter()))

    def test_last_day_included_even_if_field_carries_time(self):
        """Последний день попадает целиком, как бы портал ни завёл это поле.

        Дата отражения обычно хранится с 00:00, и тогда работает любая граница.
        Но тип поля задаёт портал: если он завёл его как datetime, запись за
        30.07 15:04 обязана остаться в выгрузке.
        """
        item = {"ufCrm6DataOtrazheniya": f"2026-07-30T15:04:00{TZ}"}
        self.assertTrue(_passes(self._filter(), item))

    def test_field_stored_at_midnight_still_included(self):
        """Обычный случай (дата без времени) не сломан."""
        item = {"ufCrm6DataOtrazheniya": "2026-07-30"}
        self.assertTrue(_passes(self._filter(), item))


class ExportDateFilterEdgeCasesTest(SimpleTestCase):
    """Края: пустые и неразбираемые даты не должны ронять выгрузку."""

    def test_no_dates_gives_empty_filter(self):
        self.assertEqual(_build_export_date_filter("creation", "", "", {}), {})

    def test_only_date_from(self):
        crm_filter = _build_export_date_filter("creation", "2026-07-23", "", {})
        self.assertEqual(crm_filter, {">=CREATED_TIME": "2026-07-23"})

    def test_unparsable_date_to_is_passed_through(self):
        """Мусор в date_to уходит в Битрикс как есть — не 500 на нашей стороне."""
        crm_filter = _build_export_date_filter("creation", "", "не дата", {})
        self.assertEqual(list(crm_filter.values()), ["не дата"])

    def test_missing_mapping_falls_back_to_created_time(self):
        crm_filter = _build_export_date_filter("reflection", "2026-07-23", "", None)
        self.assertEqual(crm_filter, {">=CREATED_TIME": "2026-07-23"})
