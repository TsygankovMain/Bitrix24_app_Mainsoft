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

    def test_rate_missing_everywhere_does_not_block_creation(self):
        # Решение заказчика 29.07.2026: поле ставки убрано с формы. Если её
        # нет и в настройках портала, заполнить значение физически нечем —
        # требование блокировало бы создание проектов навсегда (все четыре
        # шага "пропущено" и ни одного действия на экране, которое чинит).
        fields, missing = _resolve({"project_name": "П", "company_id": "15"}, config=_config(hourly_rate=0))
        self.assertNotIn("hourly_rate", missing)
        self.assertEqual(missing, [])

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
        # Неизвестная ставка больше не попадает в missing (см. тест выше):
        # плановая сумма остаётся None, но создание проекта не блокируется.
        self.assertNotIn("hourly_rate", missing)

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

    def test_only_automatic_stage_options_leave_stage_blank(self):
        # Точное репро находки ревью (блокер 1): _fetch_project_stage_options
        # (project_board_service.py) при сбое живого запроса к статусам
        # воронки глотает исключение и всё равно отдаёт НЕПУСТОЙ список — обе
        # автостадии PROJECT_AUTO_STAGES с kind="auto"/can_drop=False. Взятие
        # stage_options[0] "в лоб" подставило бы проекту стадию вида
        # "Нет списаний 1 месяц" — она пишется и в локальную таблицу, и (через
        # build_card_fields) в карточку CRM клиента, откуда её не вытащить
        # мышью. Правильный исход — пустая стадия: Битрикс сам поставит
        # стартовую стадию своей воронки при создании карточки.
        degenerate_stage_options = [
            {
                "id": "Нет списаний 1 месяц",
                "title": "Нет списаний 1 месяц",
                "kind": "auto",
                "can_drop": False,
            },
            {
                "id": "Нет списаний 3 месяца",
                "title": "Нет списаний 3 месяца",
                "kind": "auto",
                "can_drop": False,
            },
        ]
        fields, missing = _resolve(
            {"project_name": "П", "company_id": "15"}, stage_options=degenerate_stage_options
        )
        self.assertEqual(fields.stage, "")
        self.assertEqual(missing, [])

    def test_first_manual_stage_is_preferred_over_leading_automatic_stage(self):
        # Автостадия может оказаться ПЕРВОЙ в списке (порядок из Битрикса не
        # гарантирован) — резолвер обязан пропустить её и найти следующую
        # ручную, а не слепо брать stage_options[0].
        mixed_stage_options = [
            {"id": "Нет списаний 1 месяц", "title": "Нет списаний 1 месяц", "kind": "auto", "can_drop": False},
            {"id": "DT180_7:NEW", "title": "Новый", "kind": "manual", "can_drop": True},
        ]
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15"}, stage_options=mixed_stage_options
        )
        self.assertEqual(fields.stage, "DT180_7:NEW")

    def test_kind_missing_falls_back_to_can_drop_flag(self):
        # Не всякий источник stage_options обязан класть "kind" (сама функция
        # намеренно не требует конкретной формы структуры сверх этих двух
        # необязательных атрибутов) — can_drop=False работает как запасной
        # признак автостадии и без "kind".
        stage_options = [
            {"id": "Нет списаний 1 месяц", "can_drop": False},
            {"id": "DT180_7:NEW", "title": "Новый", "can_drop": True},
        ]
        fields, _ = _resolve(
            {"project_name": "П", "company_id": "15"}, stage_options=stage_options
        )
        self.assertEqual(fields.stage, "DT180_7:NEW")

    def test_is_support_y_is_parsed_as_true(self):
        fields, _ = _resolve({"project_name": "П", "company_id": "15", "is_support": "Y"})
        self.assertTrue(fields.is_support)


class InnRequirementTest(SimpleTestCase):
    """ИНН обязателен ровно при создании НОВОЙ компании (решение заказчика
    29.07.2026, inn-brief.md): company_id отсутствует, а company_name
    заполнено — то есть форма находится в паре с действием «Создать
    компанию «…»». Для уже выбранной компании (company_id есть) ИНН не
    запрашивается и не трогается — см. докстринг ensure_company/
    ensure_requisite в project_creation_service.py."""

    VALID_INN = "7707083893"  # проверенный валидный ИНН юрлица (10 цифр)

    def test_missing_inn_blocks_new_company_creation(self):
        _, missing = _resolve({"project_name": "П", "company_name": "АО Ромашка"})
        self.assertIn("inn", missing)

    def test_non_ascii_digit_inn_blocks_new_company_creation(self):
        # Контрольная сумма ИНН сознательно не проверяется (см. докстринг
        # inn_validation.py) — "٧٧٠٧٠٨٣٨٩٣" (аравийско-индийские цифры того
        # же числа 7707083893, что и VALID_INN этого класса) проверяет то, что
        # реально осталось главной защитой этого модуля: состав символов.
        # Без неё такая строка выглядела бы валидным ИНН и дошла бы до
        # реквизита в CRM клиента, не находясь потом обычным поиском (см.
        # tests_inn_validation.test_unicode_digit_lookalikes_are_rejected_
        # not_crash) — эта проверка убеждается, что защита реально
        # прокидывается через resolve_project_fields, а не работает только
        # внутри validate_inn самого по себе.
        _, missing = _resolve(
            {"project_name": "П", "company_name": "АО Ромашка", "inn": "٧٧٠٧٠٨٣٨٩٣"}
        )
        self.assertIn("inn", missing)

    def test_wrong_length_inn_blocks_new_company_creation(self):
        _, missing = _resolve(
            {"project_name": "П", "company_name": "АО Ромашка", "inn": "123"}
        )
        self.assertIn("inn", missing)

    def test_valid_inn_satisfies_the_requirement(self):
        fields, missing = _resolve(
            {"project_name": "П", "company_name": "АО Ромашка", "inn": self.VALID_INN}
        )
        self.assertNotIn("inn", missing)
        self.assertEqual(fields.inn, self.VALID_INN)

    def test_inn_whitespace_is_trimmed(self):
        fields, missing = _resolve(
            {"project_name": "П", "company_name": "АО Ромашка", "inn": f"  {self.VALID_INN}  "}
        )
        self.assertNotIn("inn", missing)
        self.assertEqual(fields.inn, self.VALID_INN)

    def test_inn_not_required_when_existing_company_is_selected_by_id(self):
        _, missing = _resolve(
            {"project_name": "П", "company_id": "15", "company_name": "АО Ромашка"}
        )
        self.assertNotIn("inn", missing)

    def test_inn_is_ignored_for_existing_company_even_if_sent(self):
        # Оборонительная проверка "не трогается": даже если инн случайно
        # долетел в payload вместе с company_id (обрывок формы, баг фронта),
        # чистая функция обязана его не заметить — это не наша зона (см.
        # "Решение" в inn-brief.md).
        fields, missing = _resolve(
            {
                "project_name": "П",
                "company_id": "15",
                "company_name": "АО Ромашка",
                "inn": self.VALID_INN,
            }
        )
        self.assertNotIn("inn", missing)
        self.assertEqual(fields.inn, "")

    def test_inn_not_required_when_company_is_entirely_missing(self):
        # И company_id, и company_name пусты — "company" уже блокирует
        # создание, дублировать ошибку через "inn" не нужно: до выбора
        # компании поле ИНН на форме не появляется вовсе (inn-brief.md,
        # "Что ещё затрагивается").
        _, missing = _resolve({"project_name": "П"})
        self.assertIn("company", missing)
        self.assertNotIn("inn", missing)

    def test_blank_inn_field_default_is_empty_string_not_none(self):
        # ResolvedProjectFields.inn — всегда str (как остальные строковые
        # поля датакласса), никогда None, чтобы вызывающему не нужно было
        # ветвиться на случай None.
        fields, _ = _resolve({"project_name": "П", "company_id": "15"})
        self.assertEqual(fields.inn, "")
