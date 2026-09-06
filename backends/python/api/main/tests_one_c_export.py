"""Тесты отправки часов в 1С.

Проверяется чистая часть: сборка пакета из записей и разбор ответа приёмника.
Сеть здесь не участвует — она в сервисе, а формат контракта проверяется тут.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from .one_c_export import build_batch, parse_response


def _item(**kwargs):
    """Запись списания в том виде, в каком её отдаёт TimesheetItem."""
    defaults = dict(
        bitrix_id=12345,
        employee_id="17",
        hours=3.5,
        is_billable=True,
        description="Правки по замечаниям",
        task_id="9483",
        task_hierarchy_titles=["Проект", "Доработка отчёта"],
        project_item_id="207",
        project_title="Восход",
        date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class BuildBatchTests(SimpleTestCase):
    def setUp(self):
        self.card = SimpleNamespace(project_item_id="207", project_id="147",
                                    our_legal_entity_id="15", company_id="8047")
        self.projects = {"207": self.card}
        self.companies_inn = {"8047": "7719021450"}
        self.legal_inn = {"15": "7325175133"}
        self.names = {"17": "Иванов Пётр"}

    def _build(self, items):
        return build_batch(
            items=items,
            projects_by_item=self.projects,
            companies_inn=self.companies_inn,
            legal_inn=self.legal_inn,
            employee_names=self.names,
            period_from=date(2026, 8, 1),
            period_to=date(2026, 8, 31),
            sending_id="b0e1",
        )

    def test_row_carries_both_inns(self):
        """ИНН обеих сторон — ключи сопоставления в 1С, без них строка не доедет."""
        batch = self._build([_item()])

        row = batch["строки"][0]
        self.assertEqual(row["юрлицо"]["инн"], "7325175133")
        self.assertEqual(row["клиент"]["инн"], "7719021450")

    def test_fractional_hours_survive(self):
        """Полчаса — обычное списание. Округление здесь означало бы потерю часов."""
        batch = self._build([_item(hours=0.5)])

        self.assertEqual(batch["строки"][0]["часы"], 0.5)

    def test_row_identified_by_bitrix_id(self):
        """Идентификатор записи — ключ идемпотентности на стороне 1С."""
        batch = self._build([_item(bitrix_id=987)])

        self.assertEqual(batch["строки"][0]["идЗаписи"], "987")

    def test_date_goes_as_iso_day(self):
        """1С датирует документ днём: время отправлять незачем."""
        batch = self._build([_item()])

        self.assertEqual(batch["строки"][0]["дата"], "2026-08-14")

    def test_non_billable_marked(self):
        """Неоплачиваемые часы в 1С ложатся в задачу с признаком «не учитывать»."""
        batch = self._build([_item(is_billable=False)])

        self.assertFalse(batch["строки"][0]["оплачиваемые"])

    def test_row_without_project_still_sent_with_empty_inn(self):
        """Строку без проекта не выбрасываем молча: пусть 1С вернёт причину,
        и она попадёт в отчёт, — иначе час исчезнет незаметно для всех."""
        batch = self._build([_item(project_item_id="")])

        row = batch["строки"][0]
        self.assertEqual(row["клиент"]["инн"], "")
        self.assertEqual(len(batch["строки"]), 1)

    def test_task_name_prefers_hierarchy_tail(self):
        """Название задачи — последний уровень иерархии: так его видит человек."""
        batch = self._build([_item()])

        self.assertEqual(batch["строки"][0]["задача"]["название"], "Доработка отчёта")

    def test_task_path_repeats_bitrix_hierarchy(self):
        """Дерево задач в 1С должно повторять портал: иначе задачи клиента
        лягут плоским списком и найти нужную будет нельзя."""
        batch = self._build([_item(task_hierarchy_titles=[
            "Разработка Восход 2026", "Этап 2", "Доработка отчёта"])])

        задача = batch["строки"][0]["задача"]
        self.assertEqual(задача["путь"], ["Разработка Восход 2026", "Этап 2"])
        self.assertEqual(задача["название"], "Доработка отчёта")

    def test_single_level_task_has_empty_path(self):
        """Задача без родителей ложится прямо под контрагента."""
        batch = self._build([_item(task_hierarchy_titles=["Доработка отчёта"])])

        self.assertEqual(batch["строки"][0]["задача"]["путь"], [])

    def test_employee_name_is_a_hint_for_humans(self):
        """ФИО едет подсказкой для отчёта об ошибках, сопоставление — по id."""
        batch = self._build([_item()])

        self.assertEqual(batch["строки"][0]["сотрудник"]["идБитрикс"], "17")
        self.assertEqual(batch["строки"][0]["сотрудник"]["фамилияИмя"], "Иванов Пётр")

    def test_manual_mapping_wins_over_autodetected_inn(self):
        """Ради этого экран и делался: Битрикс не всегда отдаёт ИНН, и человек
        должен иметь возможность задать его сам."""
        batch = build_batch(
            items=[_item()],
            projects_by_item=self.projects,
            companies_inn={},          # автоматически ничего не нашлось
            legal_inn={},
            employee_names=self.names,
            period_from=date(2026, 8, 1),
            period_to=date(2026, 8, 31),
            sending_id="b0e1",
            overrides={"companies": {"8047": "7722377665"},
                       "legal_entities": {"15": "7325175133"}},
        )

        row = batch["строки"][0]
        self.assertEqual(row["клиент"]["инн"], "7722377665")
        self.assertEqual(row["юрлицо"]["инн"], "7325175133")

    def test_employee_mapping_names_a_person_in_1c(self):
        """Сопоставление сотрудников ведётся на портале: 1С получает готовое
        физлицо и не заглядывает в свой регистр."""
        batch = self._build_with({"employees": {"17": "Иванов Пётр Сергеевич"}})

        self.assertEqual(batch["строки"][0]["сотрудник"]["физлицо1С"], "Иванов Пётр Сергеевич")

    def test_without_mapping_employee_field_is_empty(self):
        """Пока сопоставление не задано, поле пустое — 1С ищет сама."""
        batch = self._build([_item()])

        self.assertEqual(batch["строки"][0]["сотрудник"]["физлицо1С"], "")

    def _build_with(self, overrides):
        return build_batch(
            items=[_item()],
            projects_by_item=self.projects,
            companies_inn=self.companies_inn,
            legal_inn=self.legal_inn,
            employee_names=self.names,
            period_from=date(2026, 8, 1),
            period_to=date(2026, 8, 31),
            sending_id="b0e1",
            overrides=overrides,
        )

    def test_period_and_contract_version_in_envelope(self):
        batch = self._build([_item()])

        self.assertEqual(batch["версияКонтракта"], 1)
        self.assertEqual(batch["период"], {"с": "2026-08-01", "по": "2026-08-31"})
        self.assertEqual(batch["отправка"], "b0e1")

    def test_empty_period_is_a_valid_batch(self):
        """Месяц без списаний — это ноль строк, а не ошибка."""
        batch = self._build([])

        self.assertEqual(batch["строки"], [])


class ParseResponseTests(SimpleTestCase):
    def test_counts_and_rows(self):
        parsed = parse_response({
            "ok": True,
            "принято": 2,
            "отклонено": 1,
            "документы": ["ЛУРВ-1"],
            "строки": [
                {"идЗаписи": "1", "статус": "принято", "причина": "", "текст": "ЛУРВ-1"},
                {"идЗаписи": "2", "статус": "отклонено", "причина": "сотрудник_не_сопоставлен",
                 "текст": "id=42 не связан с физлицом"},
            ],
        })

        self.assertEqual(parsed["accepted"], 2)
        self.assertEqual(parsed["rejected"], 1)
        self.assertEqual(parsed["documents"], ["ЛУРВ-1"])
        self.assertEqual(parsed["rows"][1]["reason"], "сотрудник_не_сопоставлен")

    def test_refusal_without_counts_is_not_a_success(self):
        """501 «нет расширения» приходит без счётчиков — это отказ, а не ноль строк."""
        parsed = parse_response({"ok": False, "сообщение": "В базе нет расширения IT_Lab"})

        self.assertFalse(parsed["ok"])
        self.assertIn("IT_Lab", parsed["message"])

    def test_garbage_response_does_not_explode(self):
        """Приёмник может ответить чем угодно — разбор обязан пережить это."""
        parsed = parse_response("не json")

        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["accepted"], 0)


class ProjectFallbackTests(SimpleTestCase):
    """Часы, списанные на проект без карточки, доезжают по названию проекта."""

    def _item(self, **kwargs):
        return SimpleNamespace(
            bitrix_id=7, task_id="1", employee_id="17", hours=2.0, is_billable=True,
            description="", project_item_id="", project_title="ООО «Тракшина»",
            date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc), **kwargs)

    def test_inn_is_taken_from_project_mapping(self):
        batch = build_batch(
            [self._item()], {}, {}, {}, {"17": "Иванов"},
            date(2026, 8, 1), date(2026, 8, 31), "s-1",
            overrides={"projects": {"ООО «Тракшина»": {"client_inn": "7719021450",
                                                       "legal_inn": "7325175133"}}},
        )

        row = batch["строки"][0]
        self.assertEqual(row["клиент"]["инн"], "7719021450")
        self.assertEqual(row["юрлицо"]["инн"], "7325175133")
        # Название клиента берётся из проекта: по нему 1С заведёт контрагента,
        # если такого ИНН у неё ещё нет.
        self.assertEqual(row["клиент"]["название"], "ООО «Тракшина»")

    def test_without_mapping_row_still_goes_and_gets_refused(self):
        """Несопоставленная строка не выбрасывается: отклонённое видно, потерянное — нет."""
        batch = build_batch(
            [self._item()], {}, {}, {}, {}, date(2026, 8, 1), date(2026, 8, 31), "s-2")

        self.assertEqual(len(batch["строки"]), 1)
        self.assertEqual(batch["строки"][0]["клиент"]["инн"], "")


class CounterpartyCreationFlagTests(SimpleTestCase):
    """Разрешение заводить контрагентов принимает владелец базы, а не отправитель."""

    def _batch(self, overrides=None):
        item = SimpleNamespace(
            bitrix_id=1, task_id="1", employee_id="17", hours=1.0, is_billable=True,
            description="", project_item_id="", project_title="ООО «Тракшина»",
            date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc))
        return build_batch([item], {}, {}, {}, {}, date(2026, 8, 1), date(2026, 8, 31),
                           "s", overrides=overrides)

    def test_flag_is_off_by_default(self):
        self.assertFalse(self._batch()["заводитьКонтрагентов"])

    def test_flag_travels_when_enabled(self):
        self.assertTrue(self._batch({"create_counterparties": True})["заводитьКонтрагентов"])


class CompanyTitleTests(SimpleTestCase):
    """Имя клиента — запасной ключ сопоставления, когда ИНН в CRM не заполнен."""

    def _row(self, card, titles=None):
        item = SimpleNamespace(
            bitrix_id=1, task_id="1", employee_id="17", hours=1.0, is_billable=True,
            description="", project_item_id="10", project_title="Проект",
            date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc))
        return build_batch([item], {"10": card}, {}, {}, {}, date(2026, 8, 1),
                           date(2026, 8, 31), "s",
                           overrides={"company_titles": titles or {}})["строки"][0]

    def test_identifier_instead_of_name_is_replaced_by_crm_title(self):
        """В карточке на месте имени стоит id — в пакет он попасть не должен."""
        card = SimpleNamespace(company_id="2618", company_name="2618",
                               our_legal_entity_id="15", our_legal_entity_name="Наше")
        row = self._row(card, {"2618": "ООО «Тракшина»"})
        self.assertEqual(row["клиент"]["название"], "ООО «Тракшина»")

    def test_real_name_in_card_wins_without_crm(self):
        card = SimpleNamespace(company_id="2618", company_name="ООО «Тракшина»",
                               our_legal_entity_id="15", our_legal_entity_name="Наше")
        self.assertEqual(self._row(card)["клиент"]["название"], "ООО «Тракшина»")


class DefaultLegalEntityTests(SimpleTestCase):
    """Юрлицо по умолчанию спасает часы, у которых карточки проекта нет."""

    def _row(self, overrides):
        item = SimpleNamespace(
            bitrix_id=1, task_id="1", employee_id="17", hours=1.0, is_billable=True,
            description="", project_item_id="", project_title="ООО «OPKA»",
            date_reflection=datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc))
        return build_batch([item], {}, {}, {}, {}, date(2026, 8, 1), date(2026, 8, 31),
                           "s", overrides=overrides)["строки"][0]

    def test_default_is_used_when_nothing_else_known(self):
        self.assertEqual(self._row({"default_legal_inn": "7325175133"})["юрлицо"]["инн"],
                         "7325175133")

    def test_project_mapping_wins_over_default(self):
        """Заданное для проекта важнее умолчания: умолчание — последний рубеж."""
        row = self._row({"default_legal_inn": "7325175133",
                         "projects": {"ООО «OPKA»": {"client_inn": "", "legal_inn": "7719021450"}}})
        self.assertEqual(row["юрлицо"]["инн"], "7719021450")
