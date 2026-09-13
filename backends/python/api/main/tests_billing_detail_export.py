"""Детализация к счёту и акту: иерархия, названия задач, вёрстка xlsx.

Здесь закрепляется то, из-за чего выгрузку переделывали 12.09.2026:

- файл устроен как выгрузки отчётов — уровни задача → сотрудник → списание с
  подытогами и outline-группировкой, а не плоская таблица;
- в колонке задачи стоит НАЗВАНИЕ, а не идентификатор Битрикса, и берётся
  оно из первого доступного источника (снимок документа → снимок списания →
  справочник задач), а при полном промахе — говорящая заглушка с id;
- подытоги складываются в итог документа до копейки: это приложение к
  подписанному документу, расхождение здесь дороже любой опечатки.

Сквозной тест через ручку живёт в tests_billing_endpoints.DetailExportTest.
"""

import io
from datetime import date, datetime
from types import SimpleNamespace

import openpyxl
from django.test import TestCase
from django.utils import timezone

from .billing_detail_report import (
    SOURCE_ENTRY,
    SOURCE_MISSING,
    SOURCE_PORTAL_TASK,
    SOURCE_TIMESHEET,
    build_billing_detail_workbook,
    build_detail_groups,
    detail_export_filename,
    missing_title_label,
    resolve_task_titles,
)
from .models import (
    BillingDocument,
    BillingEntry,
    Bitrix24Account,
    PortalTask,
    TimesheetItem,
)
from .report_excel import render_billing_detail_workbook


def fake_entry(**kwargs):
    """Списание-снимок без базы: сборка иерархии читает только атрибуты."""
    payload = {
        "timesheet_bitrix_id": 1,
        "employee_id": "11",
        "employee_name": "Цыганков Егор",
        "date_reflection": datetime(2026, 8, 15, 0, 0),
        "hours": 2.0,
        "rate_snapshot": 2000.0,
        "amount": 4000.0,
        "task_id": "8365",
        "task_title": "Доработка отчётов",
        "description": "разработка",
    }
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def fake_document(**kwargs):
    payload = {
        "crm_account_number": "Б-00042",
        "created_at": datetime(2026, 9, 12, 10, 0),
        "status": BillingDocument.STATUS_ISSUED,
        "company_name": "ООО Клиент",
        "our_company_name": "ООО Майнсофт",
        "period_from": date(2026, 8, 1),
        "period_to": date(2026, 8, 31),
        "currency": "RUB",
        "total_hours": 2.0,
        "total_amount": 4000.0,
    }
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def rows_of(output):
    workbook = openpyxl.load_workbook(io.BytesIO(output.read()))
    return workbook.active, list(workbook.active.iter_rows(values_only=True))


class DetailGroupsTest(TestCase):
    """Сборка уровней: задача → сотрудник → списание."""

    def test_three_levels_with_subtotals(self):
        entries = [
            fake_entry(timesheet_bitrix_id=1, hours=2.0, amount=4000.0),
            fake_entry(timesheet_bitrix_id=2, hours=3.0, amount=6000.0,
                       date_reflection=datetime(2026, 8, 16, 0, 0)),
            fake_entry(timesheet_bitrix_id=3, hours=1.0, amount=2000.0,
                       employee_id="22", employee_name="Иванов Иван"),
        ]

        groups = build_detail_groups(entries)

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["name"], "Доработка отчётов")
        self.assertEqual(group["hours"], 6.0)
        self.assertEqual(group["amount"], 12000.0)
        self.assertEqual([emp["name"] for emp in group["employees"]],
                         ["Иванов Иван", "Цыганков Егор"])
        egor = group["employees"][1]
        self.assertEqual(egor["hours"], 5.0)
        self.assertEqual(egor["amount"], 10000.0)
        self.assertEqual([item["date"] for item in egor["items"]],
                         ["15.08.2026", "16.08.2026"])

    def test_entries_without_task_go_to_their_own_group_last(self):
        entries = [
            fake_entry(timesheet_bitrix_id=1, task_id="", task_title="", hours=1.5, amount=3000.0),
            fake_entry(timesheet_bitrix_id=2),
        ]

        groups = build_detail_groups(entries)

        self.assertEqual([group["name"] for group in groups],
                         ["Доработка отчётов", "Без задачи"])
        self.assertEqual(groups[-1]["task_id"], "")
        self.assertEqual(groups[-1]["hours"], 1.5)

    def test_tasks_are_sorted_by_title(self):
        entries = [
            fake_entry(timesheet_bitrix_id=1, task_id="1", task_title="Яндекс-интеграция"),
            fake_entry(timesheet_bitrix_id=2, task_id="2", task_title="Автотесты"),
        ]

        groups = build_detail_groups(entries)

        self.assertEqual([group["name"] for group in groups],
                         ["Автотесты", "Яндекс-интеграция"])

    def test_rate_is_shown_only_when_the_group_has_one(self):
        same = build_detail_groups([
            fake_entry(timesheet_bitrix_id=1, rate_snapshot=2000.0),
            fake_entry(timesheet_bitrix_id=2, rate_snapshot=2000.0),
        ])
        mixed = build_detail_groups([
            fake_entry(timesheet_bitrix_id=1, rate_snapshot=2000.0),
            fake_entry(timesheet_bitrix_id=2, rate_snapshot=2500.0),
        ])

        self.assertEqual(same[0]["rate"], 2000.0)
        self.assertIsNone(mixed[0]["rate"])

    def test_employee_without_name_keeps_its_id_visible(self):
        groups = build_detail_groups([fake_entry(employee_name="", employee_id="22")])

        self.assertEqual(groups[0]["employees"][0]["name"], "Сотрудник 22")

    def test_missing_title_falls_back_to_label_with_id(self):
        groups = build_detail_groups([fake_entry(task_title="")])

        self.assertEqual(groups[0]["name"], "Задача 8365 (название не найдено)")
        self.assertEqual(groups[0]["title_source"], SOURCE_MISSING)


class TaskTitleResolutionTest(TestCase):
    """Откуда берётся человеческое название задачи."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-detail-titles",
            is_master_account=True, domain_url="detail.bitrix24.ru",
            status="active", application_version=1,
        )

    def timesheet(self, bitrix_id, *, task_id, titles, ids=None):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=1.0, is_billable=True,
            task_hierarchy_ids=ids if ids is not None else [task_id],
            task_hierarchy_titles=titles,
            date_reflection=timezone.make_aware(datetime(2026, 8, 15, 0, 0)),
        )

    def test_snapshot_of_the_document_wins(self):
        self.timesheet(1, task_id="8365", titles=["Название после переименования"])
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Название после переименования", group_id="73",
        )

        titles = resolve_task_titles(self.account, [fake_entry(task_title="Как выставляли")])

        self.assertEqual(titles["8365"], ("Как выставляли", SOURCE_ENTRY))

    def test_timesheet_hierarchy_rescues_empty_snapshot(self):
        self.timesheet(7, task_id="8365", titles=["Проект", "Доработка отчётов"],
                       ids=["100", "8365"])

        titles = resolve_task_titles(
            self.account, [fake_entry(timesheet_bitrix_id=7, task_title="")]
        )

        self.assertEqual(titles["8365"], ("Доработка отчётов", SOURCE_TIMESHEET))

    def test_portal_task_directory_is_the_last_source(self):
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Название из справочника", group_id="73",
        )

        titles = resolve_task_titles(
            self.account, [fake_entry(timesheet_bitrix_id=99, task_title="")]
        )

        self.assertEqual(titles["8365"], ("Название из справочника", SOURCE_PORTAL_TASK))

    def test_nowhere_to_be_found_gives_a_label_with_id(self):
        titles = resolve_task_titles(
            self.account, [fake_entry(timesheet_bitrix_id=99, task_title="")]
        )

        self.assertEqual(titles["8365"], (missing_title_label("8365"), SOURCE_MISSING))
        self.assertIn("8365", titles["8365"][0])

    def test_entries_without_task_ask_nothing(self):
        titles = resolve_task_titles(self.account, [fake_entry(task_id="", task_title="")])

        self.assertEqual(titles, {})

    def test_title_from_directory_of_another_account_is_not_used(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=True, member_id="m-detail-other",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalTask.objects.create(
            bitrix24_account=other, bitrix_id="8365",
            title="Чужое название", group_id="73",
        )

        titles = resolve_task_titles(
            self.account, [fake_entry(timesheet_bitrix_id=99, task_title="")]
        )

        self.assertEqual(titles["8365"], (missing_title_label("8365"), SOURCE_MISSING))


class DetailWorkbookTest(TestCase):
    """Вёрстка файла: шапка, уровни, подытоги, итог."""

    def setUp(self):
        self.entries = [
            fake_entry(timesheet_bitrix_id=1, hours=2.0, amount=4000.0),
            fake_entry(timesheet_bitrix_id=2, hours=3.0, amount=6000.0,
                       date_reflection=datetime(2026, 8, 16, 0, 0)),
            fake_entry(timesheet_bitrix_id=3, hours=1.0, amount=2000.0,
                       task_id="9000", task_title="Настройка прав",
                       employee_id="22", employee_name="Иванов Иван"),
        ]
        self.document = fake_document(total_hours=6.0, total_amount=12000.0)
        self.groups = build_detail_groups(self.entries)

    def test_header_carries_parties_period_and_totals(self):
        _, rows = rows_of(render_billing_detail_workbook(self.document, self.groups))

        self.assertEqual(rows[0][0], "Детализация к счёту № Б-00042 от 12.09.2026")
        self.assertIn("Клиент: ООО Клиент", rows[1][0])
        self.assertIn("Наше юрлицо: ООО Майнсофт", rows[1][0])
        self.assertIn("Период: 01.08.2026 — 31.08.2026", rows[1][0])
        self.assertIn("Итого по документу: 6,0 ч · 12 000,00 RUB", rows[2][0])
        self.assertIn("задач: 2", rows[2][0])
        self.assertIn("списаний: 3", rows[2][0])

    def test_columns_are_human_and_stable(self):
        _, rows = rows_of(render_billing_detail_workbook(self.document, self.groups))

        self.assertEqual(
            list(rows[3]),
            ["Задача / сотрудник", "Дата", "Описание", "Часы", "Ставка, ₽", "Сумма, ₽"],
        )

    def test_levels_hold_task_employee_and_entries(self):
        ws, rows = rows_of(render_billing_detail_workbook(self.document, self.groups))

        self.assertEqual(rows[4][0], "Доработка отчётов")
        self.assertEqual(rows[4][3], 5.0)
        self.assertEqual(rows[4][5], 10000.0)
        self.assertEqual(rows[5][0], "Цыганков Егор")
        self.assertEqual(rows[5][3], 5.0)
        # Списание: имя пустое, зато есть дата, описание, часы, ставка, сумма.
        self.assertIsNone(rows[6][0])
        self.assertEqual(rows[6][1], "15.08.2026")
        self.assertEqual(rows[6][2], "разработка")
        self.assertEqual(rows[6][3], 2.0)
        self.assertEqual(rows[6][4], 2000.0)
        self.assertEqual(rows[6][5], 4000.0)
        # Группировка: сотрудник — первый уровень, списание — второй.
        self.assertEqual(ws.row_dimensions[5].outline_level, 0)
        self.assertEqual(ws.row_dimensions[6].outline_level, 1)
        self.assertEqual(ws.row_dimensions[7].outline_level, 2)

    def test_total_matches_the_document(self):
        _, rows = rows_of(render_billing_detail_workbook(self.document, self.groups))

        self.assertEqual(rows[-1][0], "ИТОГО")
        self.assertEqual(rows[-1][3], self.document.total_hours)
        self.assertEqual(rows[-1][5], self.document.total_amount)

    def test_subtotals_sum_up_to_the_total(self):
        _, rows = rows_of(render_billing_detail_workbook(self.document, self.groups))

        task_rows = [row for row in rows[4:-1] if row[0] in ("Доработка отчётов", "Настройка прав")]
        self.assertEqual(len(task_rows), 2)
        self.assertEqual(sum(row[3] for row in task_rows), rows[-1][3])
        self.assertEqual(sum(row[5] for row in task_rows), rows[-1][5])

    def test_mismatch_with_the_document_is_announced(self):
        document = fake_document(total_hours=99.0, total_amount=99000.0)

        _, rows = rows_of(render_billing_detail_workbook(document, self.groups))

        self.assertEqual(rows[-2][0], "ИТОГО")
        self.assertIn("расходится с итогом документа", rows[-1][0])

    def test_cancelled_document_says_so_in_the_title(self):
        document = fake_document(status=BillingDocument.STATUS_CANCELLED)

        _, rows = rows_of(render_billing_detail_workbook(document, self.groups))

        self.assertIn("ДОКУМЕНТ ОТМЕНЁН", rows[0][0])

    def test_empty_document_still_opens(self):
        document = fake_document(total_hours=0.0, total_amount=0.0)

        _, rows = rows_of(render_billing_detail_workbook(document, []))

        self.assertEqual(rows[-1][0], "ИТОГО")
        self.assertEqual(rows[-1][3], 0)


class DetailFilenameTest(TestCase):
    def test_name_carries_number_client_and_period(self):
        name = detail_export_filename(fake_document())

        self.assertEqual(
            name,
            "Детализация к счёту № Б-00042 ООО Клиент (01.08.2026 — 31.08.2026).xlsx",
        )

    def test_name_survives_missing_number_and_period(self):
        name = detail_export_filename(
            fake_document(crm_account_number="", period_from=None, period_to=None,
                          company_name="")
        )

        self.assertEqual(name, "Детализация к счёту.xlsx")

    def test_path_separators_are_scrubbed(self):
        name = detail_export_filename(fake_document(crm_account_number="Б/42"))

        self.assertNotIn("/", name)


class DetailFromDatabaseTest(TestCase):
    """Тот же путь, но на настоящих BillingDocument/BillingEntry."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-detail-db",
            is_master_account=True, domain_url="detail-db.bitrix24.ru",
            status="active", application_version=1,
        )
        self.document = BillingDocument.objects.create(
            bitrix24_account=self.account, company_id="15", company_name="ООО Клиент",
            our_company_id="7", our_company_name="ООО Майнсофт",
            period_from=date(2026, 8, 1), period_to=date(2026, 8, 31),
            crm_account_number="Б-00042", total_hours=3.0, total_amount=6000.0,
        )

    def entry(self, bitrix_id, **kwargs):
        payload = {
            "employee_id": "11", "employee_name": "Цыганков Егор",
            "date_reflection": timezone.make_aware(datetime(2026, 8, 15, 0, 0)),
            "hours": 1.5, "rate_snapshot": 2000.0, "amount": 3000.0,
            "task_id": "8365", "task_title": "", "description": "разработка",
        }
        payload.update(kwargs)
        return BillingEntry.objects.create(
            document=self.document, bitrix24_account=self.account,
            timesheet_bitrix_id=bitrix_id, **payload,
        )

    def test_workbook_of_a_stored_document(self):
        self.entry(1)
        self.entry(2, date_reflection=timezone.make_aware(datetime(2026, 8, 16, 0, 0)))
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Доработка отчётов", group_id="73",
        )

        _, rows = rows_of(build_billing_detail_workbook(self.document, self.document.entries.all()))

        self.assertEqual(rows[4][0], "Доработка отчётов")
        self.assertEqual(rows[4][3], 3.0)
        self.assertEqual(rows[-1][3], self.document.total_hours)
        self.assertEqual(rows[-1][5], self.document.total_amount)
