"""Тесты чистого расчёта полей карточки проекта (§5 спеки: пустых полей не остаётся)."""
from datetime import date
from django.test import SimpleTestCase

from .project_creation_defaults import (
    DEFAULT_BUDGET_MODE,
    DEFAULT_PROJECT_TYPE,
    add_one_year,
    resolve_project_fields,
)


def _config(hourly_rate=1500):
    return {"hourly_rate": hourly_rate, "project_fields_mapping": {}, "project_sp_entity_type_id": 180}


def _stages():
    return [{"id": "DT180_7:NEW", "title": "Новый"}, {"id": "DT180_7:WON", "title": "Завершён"}]


def _resolve(form, **overrides):
    kwargs = {
        "config": _config(),
        "current_user_id": "42",
        "current_user_name": "Петров Иван",
        "today": date(2026, 7, 28),
        "legal_entities": [{"id": "7", "name": "ООО Мейнсофт"}],
        "stage_options": _stages(),
    }
    kwargs.update(overrides)
    return resolve_project_fields(form, **kwargs)


class AddOneYearTest(SimpleTestCase):
    def test_adds_one_year(self):
        self.assertEqual(add_one_year(date(2026, 7, 28)), date(2027, 7, 28))

    def test_leap_day_falls_back_to_28_february(self):
        self.assertEqual(add_one_year(date(2028, 2, 29)), date(2029, 2, 28))


class ResolveProjectFieldsTest(SimpleTestCase):
    def test_fills_every_field_from_defaults(self):
        fields, missing = _resolve({"project_name": "Портал АО Ромашка", "company_id": "15"})

        self.assertEqual(missing, [])
        self.assertEqual(fields.project_name, "Портал АО Ромашка")
        self.assertEqual(fields.curator_user_id, "42")
        self.assertEqual(fields.curator_name, "Петров Иван")
        self.assertEqual(fields.project_start_date, date(2026, 7, 28))
        self.assertEqual(fields.project_end_date, date(2027, 7, 28))
        self.assertEqual(fields.hourly_rate, 1500.0)
        self.assertEqual(fields.project_type, DEFAULT_PROJECT_TYPE)
        self.assertEqual(fields.budget_mode, DEFAULT_BUDGET_MODE)
        self.assertFalse(fields.is_support)
        self.assertEqual(fields.stage, "DT180_7:NEW")
        # Единственное разрешённое исключение из «пустых полей не остаётся»:
        self.assertIsNone(fields.project_hours_budget)
        self.assertIsNone(fields.planned_budget_amount)

    def test_single_legal_entity_is_auto_selected(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"})
        self.assertEqual(fields.our_legal_entity_id, "7")
        self.assertEqual(fields.our_legal_entity_name, "ООО Мейнсофт")
        self.assertEqual(missing, [])

    def test_several_legal_entities_make_the_field_required(self):
        entities = [{"id": "7", "name": "ООО Мейнсофт"}, {"id": "9", "name": "ИП Цыганков"}]
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, legal_entities=entities)
        self.assertIn("our_legal_entity_id", missing)
        self.assertIsNone(fields.our_legal_entity_id)

    def test_several_legal_entities_satisfied_by_user_choice(self):
        entities = [{"id": "7", "name": "ООО Мейнсофт"}, {"id": "9", "name": "ИП Цыганков"}]
        fields, missing = _resolve(
            {"project_name": "П", "company_id": "15", "our_legal_entity_id": "9"},
            legal_entities=entities,
        )
        self.assertEqual(missing, [])
        self.assertEqual(fields.our_legal_entity_id, "9")
        self.assertEqual(fields.our_legal_entity_name, "ИП Цыганков")

    def test_empty_legal_entities_do_not_block_creation(self):
        # На портале нет ни одной компании с признаком «моя» — сотруднику
        # физически не из чего выбрать в форме. Это не ошибка данных: поле
        # остаётся необязательным, а не блокирует создание проекта.
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, legal_entities=[])
        self.assertIsNone(fields.our_legal_entity_id)
        self.assertNotIn("our_legal_entity_id", missing)

    def test_rate_missing_in_config_makes_the_field_required(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, config=_config(hourly_rate=0))
        self.assertIn("hourly_rate", missing)

    def test_rate_from_form_beats_config(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15", "hourly_rate": "2000"})
        self.assertEqual(fields.hourly_rate, 2000.0)
        self.assertEqual(missing, [])

    def test_comma_is_accepted_as_decimal_separator_in_hourly_rate(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "hourly_rate": "1500,50"})
        self.assertEqual(fields.hourly_rate, 1500.5)

    def test_comma_is_accepted_as_decimal_separator_in_project_hours_budget(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "project_hours_budget": "7,5"})
        self.assertEqual(fields.project_hours_budget, 7.5)

    def test_planned_amount_is_hours_times_rate(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "project_hours_budget": "10"})
        self.assertEqual(fields.project_hours_budget, 10.0)
        self.assertEqual(fields.planned_budget_amount, 15000.0)

    def test_planned_amount_is_none_when_rate_is_unknown(self):
        # Ставка не резолвилась ни из формы, ни из конфига — плановая сумма
        # должна остаться None, а не молча превратиться в 0 ₽: в живом
        # пересчёте формы 0 читается как факт, а не как «неизвестно».
        fields, missing = _resolve(
            {"project_name": "П", "company_id": "15", "project_hours_budget": "10"},
            config=_config(hourly_rate=0),
        )
        self.assertIsNone(fields.planned_budget_amount)
        self.assertIn("hourly_rate", missing)

    def test_end_date_follows_explicit_start_date(self):
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15", "project_start_date": "2026-01-15"}
        )
        self.assertEqual(fields.project_start_date, date(2026, 1, 15))
        self.assertEqual(fields.project_end_date, date(2027, 1, 15))

    def test_explicit_end_date_is_not_overwritten(self):
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15", "project_end_date": "2026-12-31"}
        )
        self.assertEqual(fields.project_end_date, date(2026, 12, 31))

    def test_name_and_company_are_required(self):
        _, missing = _resolve({})
        self.assertIn("project_name", missing)
        self.assertIn("company", missing)

    def test_company_name_alone_satisfies_company_requirement(self):
        _, missing = _resolve({"project_name": "П", "company_name": "АО Ромашка"})
        self.assertNotIn("company", missing)

    def test_empty_stage_options_leave_stage_blank_without_crashing(self):
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, stage_options=[])
        self.assertEqual(fields.stage, "")
        self.assertEqual(missing, [])

    def test_is_support_y_is_parsed_as_true(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "is_support": "Y"})
        self.assertTrue(fields.is_support)
