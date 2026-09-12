"""Отбор списаний для счёта: фильтр, группировки, ставки, предупреждения.

Тут закрепляется ядро функции без единого обращения к порталу. Всё, что
касается CRM, живёт в tests_billing_endpoints.

Главное, что проверяется: счёт собирается из ТЕХ ЖЕ данных, что и отчёт
(проект резолвится по трём ключам карточки), ставка берётся снимком
списания, а не текущей карточкой проекта, и каждое отклонение отбора
получает код предупреждения — «молча исключили» быть не должно.
"""

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from .billing_service import (
    BillingError,
    BillingFilter,
    BillingService,
    ERROR_LINES_MISMATCH,
    WARNING_ALREADY_INVOICED,
    WARNING_MIXED_COMPANIES,
    WARNING_NO_RATE,
    WARNING_PERIOD_OPEN,
)
from .models import (
    BillingDocument,
    BillingEntry,
    Bitrix24Account,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)
from .period_service import PeriodService


CLOSED_SETTINGS = {"allow_open_period": False, "accountants": [], "act_template_id": 0}
OPEN_SETTINGS = {"allow_open_period": True, "accountants": [], "act_template_id": 0}


class BillingFixture(TestCase):
    """Общая заготовка: портал, два проекта разных клиентов, сотрудники."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-billing",
            is_master_account=True, domain_url="billing.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="11",
            name="Егор", last_name="Цыганков",
        )
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="12",
            name="Анна", last_name="Петрова",
        )
        self.card = ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="73", project_name="Мейнсофт",
            stage="in_work", hourly_rate=2000.0,
            company_id="15", company_name="ООО Клиент",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )
        self.other_card = ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="88", project_name="Другой",
            stage="in_work", hourly_rate=1000.0,
            company_id="16", company_name="ООО Второй",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )

    def entry(self, bitrix_id, *, hours=2.0, rate=2000.0, project_id="73",
              employee_id="11", task_id="8365", day=15, month=8, billable=True,
              description="работа"):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id=employee_id, hours=hours, is_billable=billable,
            project_id=project_id, project_title="Мейнсофт" if project_id == "73" else "Другой",
            hourly_rate_snapshot=rate, description=description,
            task_hierarchy_ids=[task_id], task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, month, day, 0, 0)),
        )

    def service(self, settings=None):
        return BillingService(self.account, client=object(), settings=settings or CLOSED_SETTINGS)

    def filters(self, **kwargs):
        payload = {"date_from": "2026-08-01", "date_to": "2026-08-31"}
        payload.update(kwargs)
        return BillingFilter.from_payload(payload)

    def close_august(self):
        PeriodService(self.account).close(2026, 8, stats={}, by_id="11", by_name="Егор")


class SelectionTest(BillingFixture):
    def test_collects_billable_entries_of_one_company(self):
        self.entry(1)
        self.entry(2, hours=3.0)

        selection = self.service().collect(self.filters())

        self.assertEqual(len(selection.entries), 2)
        self.assertEqual(selection.total_hours, 5.0)
        self.assertEqual(selection.total_amount, 10000.0)
        self.assertEqual(selection.companies, [{"id": "15", "name": "ООО Клиент"}])

    def test_non_billable_is_skipped_by_default(self):
        self.entry(1)
        self.entry(2, billable=False)

        self.assertEqual(len(self.service().collect(self.filters()).entries), 1)

    def test_billable_only_can_be_switched_off(self):
        self.entry(1)
        self.entry(2, billable=False)

        selection = self.service().collect(self.filters(billable_only=False))

        self.assertEqual(len(selection.entries), 2)

    def test_period_bounds_include_last_day(self):
        """Верхняя граница — «строго меньше начала следующего дня».

        Через <= дата последнего дня отсекалась бы: полночь 31.08 не больше
        31.08, но всё, что позже, уже больше.
        """
        self.entry(1, day=31)

        self.assertEqual(len(self.service().collect(self.filters()).entries), 1)

    def test_company_filter_uses_project_card(self):
        self.entry(1, project_id="73")
        self.entry(2, project_id="88")

        selection = self.service().collect(self.filters(company_id="15"))

        self.assertEqual([row["timesheet_bitrix_id"] for row in selection.entries], [1])

    def test_employee_and_task_filters(self):
        self.entry(1, employee_id="11", task_id="100")
        self.entry(2, employee_id="12", task_id="200")

        by_employee = self.service().collect(self.filters(employee_ids=["12"]))
        by_task = self.service().collect(self.filters(task_ids=["100"]))

        self.assertEqual([row["employee_id"] for row in by_employee.entries], ["12"])
        self.assertEqual([row["task_id"] for row in by_task.entries], ["100"])

    def test_rate_falls_back_to_project_card(self):
        """Контракт, п. 5: нет снимка ставки — берём ставку карточки проекта."""
        self.entry(1, rate=None)

        selection = self.service().collect(self.filters())

        self.assertEqual(selection.entries[0]["rate_snapshot"], 2000.0)
        self.assertEqual(selection.entries[0]["amount"], 4000.0)

    def test_snapshot_rate_wins_over_card(self):
        self.entry(1, rate=3500.0)

        self.assertEqual(self.service().collect(self.filters()).entries[0]["rate_snapshot"], 3500.0)

    def test_employee_name_comes_from_local_directory(self):
        self.entry(1, employee_id="12")

        self.assertEqual(self.service().collect(self.filters()).entries[0]["employee_name"], "Петрова Анна")


class GroupingTest(BillingFixture):
    def setUp(self):
        super().setUp()
        self.entry(1, task_id="100", employee_id="11", hours=2.0)
        self.entry(2, task_id="200", employee_id="12", hours=3.0)
        self.entry(3, task_id="200", employee_id="11", hours=1.0, project_id="88", rate=1000.0)

    def test_group_by_project(self):
        selection = self.service().collect(self.filters(company_id="15"))

        self.assertEqual([line["title"] for line in selection.lines], ["Мейнсофт"])
        self.assertEqual(selection.lines[0]["hours"], 5.0)
        self.assertEqual(selection.lines[0]["amount"], 10000.0)

    def test_group_by_task(self):
        selection = self.service().collect(self.filters(company_id="15", grouping="task"))

        hours = {line["title"]: line["hours"] for line in selection.lines}
        self.assertEqual(hours, {"Задача 100": 2.0, "Задача 200": 3.0})

    def test_group_by_employee(self):
        selection = self.service().collect(self.filters(company_id="15", grouping="employee"))

        hours = {line["title"]: line["hours"] for line in selection.lines}
        self.assertEqual(hours, {"Цыганков Егор": 2.0, "Петрова Анна": 3.0})

    def test_group_single(self):
        selection = self.service().collect(self.filters(company_id="15", grouping="single"))

        self.assertEqual(len(selection.lines), 1)
        self.assertEqual(selection.lines[0]["hours"], 5.0)

    def test_line_rate_is_weighted_not_borrowed(self):
        """Ставка строки — сумма/часы, а не «ставка первой записи».

        В строке лежат списания с разными ставками; подставить любую одну
        значило бы показать в счёте цену, которая не бьётся с детализацией.
        """
        TimesheetItem.objects.filter(bitrix_id=2).update(hourly_rate_snapshot=1000.0)

        selection = self.service().collect(self.filters(company_id="15"))

        line = selection.lines[0]
        self.assertEqual(line["amount"], 7000.0)
        self.assertEqual(line["hours"], 5.0)
        self.assertEqual(line["rate"], 1400.0)

    def test_unknown_grouping_is_rejected(self):
        with self.assertRaises(BillingError) as ctx:
            self.filters(grouping="по-настроению")
        self.assertEqual(ctx.exception.code, "bad_grouping")


class WarningsTest(BillingFixture):
    def test_mixed_companies_is_blocking(self):
        self.entry(1, project_id="73")
        self.entry(2, project_id="88")

        selection = self.service().collect(self.filters())

        warning = next(w for w in selection.warnings if w["code"] == WARNING_MIXED_COMPANIES)
        self.assertTrue(warning["blocking"])

    def test_no_rate_warning(self):
        self.card.hourly_rate = 0.0
        self.card.save(update_fields=["hourly_rate"])
        self.entry(1, rate=None)

        selection = self.service().collect(self.filters())

        warning = next(w for w in selection.warnings if w["code"] == WARNING_NO_RATE)
        self.assertEqual(warning["count"], 1)
        self.assertFalse(warning["blocking"])

    def test_open_period_warning_blocks_by_default(self):
        self.entry(1)

        warning = next(
            w for w in self.service().collect(self.filters()).warnings
            if w["code"] == WARNING_PERIOD_OPEN
        )

        self.assertTrue(warning["blocking"])
        self.assertEqual(warning["periods"], ["2026-08"])

    def test_open_period_warning_is_not_blocking_when_allowed(self):
        self.entry(1)

        warning = next(
            w for w in self.service(OPEN_SETTINGS).collect(self.filters()).warnings
            if w["code"] == WARNING_PERIOD_OPEN
        )

        self.assertFalse(warning["blocking"])

    def test_closed_period_gives_no_warning(self):
        self.entry(1)
        self.close_august()

        codes = self.service().collect(self.filters()).warning_codes()

        self.assertNotIn(WARNING_PERIOD_OPEN, codes)

    def test_only_closed_periods_filter_drops_open_months(self):
        self.entry(1, month=8)
        self.entry(2, month=7, day=10)
        self.close_august()

        selection = self.service().collect(
            BillingFilter.from_payload({
                "date_from": "2026-07-01", "date_to": "2026-08-31",
                "only_closed_periods": True,
            })
        )

        self.assertEqual([row["timesheet_bitrix_id"] for row in selection.entries], [1])


class AlreadyInvoicedTest(BillingFixture):
    def _issue(self, ids):
        document = BillingDocument.objects.create(
            bitrix24_account=self.account, status=BillingDocument.STATUS_ISSUED,
            company_id="15", company_name="ООО Клиент",
        )
        for bitrix_id in ids:
            BillingEntry.objects.create(
                document=document, bitrix24_account=self.account,
                timesheet_bitrix_id=bitrix_id, is_active=True, hours=2.0,
            )
        return document

    def test_invoiced_entries_are_excluded_with_warning(self):
        self.entry(1)
        self.entry(2)
        self._issue([1])

        selection = self.service().collect(self.filters())

        self.assertEqual([row["timesheet_bitrix_id"] for row in selection.entries], [2])
        warning = next(w for w in selection.warnings if w["code"] == WARNING_ALREADY_INVOICED)
        self.assertEqual(warning["count"], 1)

    def test_cancelled_document_frees_entries(self):
        self.entry(1)
        document = self._issue([1])

        BillingService(self.account, client=object(), settings=CLOSED_SETTINGS).cancel(
            document, "ошиблись клиентом", user_id="11", user_name="Егор",
        )
        selection = self.service().collect(self.filters())

        self.assertEqual([row["timesheet_bitrix_id"] for row in selection.entries], [1])
        self.assertNotIn(WARNING_ALREADY_INVOICED, selection.warning_codes())

    def test_cancel_requires_reason(self):
        document = self._issue([1])

        with self.assertRaises(BillingError) as ctx:
            self.service().cancel(document, "  ")

        self.assertEqual(ctx.exception.code, "cancel_reason_required")

    def test_exclude_invoiced_off_keeps_them_and_blocks(self):
        self.entry(1)
        self._issue([1])

        selection = self.service().collect(self.filters(exclude_invoiced=False))

        self.assertEqual(len(selection.entries), 1)
        warning = next(w for w in selection.warnings if w["code"] == WARNING_ALREADY_INVOICED)
        self.assertTrue(warning["blocking"])


class ValidationTest(BillingFixture):
    def test_repeat_issue_of_same_entries_is_conflict_not_empty(self):
        """Контракт, п. 8: повторное выставление — 409 со ссылкой, не «нечего выставлять»."""
        self.entry(1)
        document = BillingDocument.objects.create(
            bitrix24_account=self.account, status=BillingDocument.STATUS_ISSUED,
            company_id="15",
        )
        BillingEntry.objects.create(
            document=document, bitrix24_account=self.account,
            timesheet_bitrix_id=1, is_active=True, hours=2.0,
        )

        service = self.service()
        filters = self.filters()
        selection = service.collect(filters)

        with self.assertRaises(BillingError) as ctx:
            service.validate_for_issue(selection, filters)

        self.assertEqual(ctx.exception.code, "already_invoiced")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.extra["document_ids"], [str(document.pk)])

    def test_empty_selection_is_rejected(self):
        service = self.service()
        filters = self.filters()

        with self.assertRaises(BillingError) as ctx:
            service.validate_for_issue(service.collect(filters), filters)

        self.assertEqual(ctx.exception.code, "empty_selection")

    def test_open_period_blocks_issue(self):
        self.entry(1)
        service = self.service()
        filters = self.filters()

        with self.assertRaises(BillingError) as ctx:
            service.validate_for_issue(service.collect(filters), filters)

        self.assertEqual(ctx.exception.code, WARNING_PERIOD_OPEN)

    def test_open_period_is_allowed_by_setting(self):
        self.entry(1)
        service = self.service(OPEN_SETTINGS)
        filters = self.filters()

        service.validate_for_issue(service.collect(filters), filters)  # не бросает

    def test_mixed_companies_blocks_issue(self):
        self.entry(1, project_id="73")
        self.entry(2, project_id="88")
        self.close_august()
        service = self.service()
        filters = self.filters()

        with self.assertRaises(BillingError) as ctx:
            service.validate_for_issue(service.collect(filters), filters)

        self.assertEqual(ctx.exception.code, WARNING_MIXED_COMPANIES)


class PartialIndexTest(BillingFixture):
    """Двойное выставление держит БАЗА, а не проверка в коде."""

    def _document(self, status=BillingDocument.STATUS_ISSUED):
        return BillingDocument.objects.create(
            bitrix24_account=self.account, status=status, company_id="15",
        )

    def test_two_active_entries_for_one_timesheet_are_rejected(self):
        from django.db import IntegrityError, transaction

        BillingEntry.objects.create(
            document=self._document(), bitrix24_account=self.account,
            timesheet_bitrix_id=1, is_active=True,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BillingEntry.objects.create(
                    document=self._document(), bitrix24_account=self.account,
                    timesheet_bitrix_id=1, is_active=True,
                )

    def test_inactive_entries_do_not_conflict(self):
        """Индекс частичный: у отменённых документов дублей сколько угодно."""
        for _ in range(3):
            BillingEntry.objects.create(
                document=self._document(BillingDocument.STATUS_CANCELLED),
                bitrix24_account=self.account, timesheet_bitrix_id=1, is_active=False,
            )

        self.assertEqual(BillingEntry.objects.filter(timesheet_bitrix_id=1).count(), 3)


class DriftTest(BillingFixture):
    def _document_with_entry(self, *, hours=2.0, rate=2000.0):
        document = BillingDocument.objects.create(
            bitrix24_account=self.account, status=BillingDocument.STATUS_ISSUED,
            company_id="15",
        )
        BillingEntry.objects.create(
            document=document, bitrix24_account=self.account, timesheet_bitrix_id=1,
            is_active=True, hours=hours, rate_snapshot=rate, amount=hours * rate,
            employee_name="Цыганков Егор",
        )
        return document

    def test_changed_hours_show_up(self):
        self.entry(1, hours=2.0)
        document = self._document_with_entry(hours=2.0)
        TimesheetItem.objects.filter(bitrix_id=1).update(hours=5.0)

        drift = self.service().drift(document)

        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["kind"], "changed")
        self.assertEqual(drift[0]["hours"], 2.0)
        self.assertEqual(drift[0]["current_hours"], 5.0)

    def test_changed_rate_shows_up(self):
        self.entry(1, rate=2000.0)
        document = self._document_with_entry(rate=2000.0)
        TimesheetItem.objects.filter(bitrix_id=1).update(hourly_rate_snapshot=2500.0)

        drift = self.service().drift(document)

        self.assertEqual(drift[0]["kind"], "changed")
        self.assertEqual(drift[0]["current_rate"], 2500.0)

    def test_deleted_entry_shows_up(self):
        """Синк физически удаляет пропавшее в Битриксе — документ это показывает."""
        self.entry(1)
        document = self._document_with_entry()
        TimesheetItem.objects.filter(bitrix_id=1).delete()

        drift = self.service().drift(document)

        self.assertEqual(drift[0]["kind"], "deleted")
        self.assertIsNone(drift[0]["current_hours"])

    def test_untouched_document_has_no_drift(self):
        self.entry(1, hours=2.0, rate=2000.0)
        document = self._document_with_entry()

        self.assertEqual(self.service().drift(document), [])

    def test_empty_rate_snapshot_is_not_a_change(self):
        """Пустой снимок ставки значит «бралась из карточки» — не правка списания."""
        self.entry(1, rate=None)
        document = self._document_with_entry(rate=2000.0)

        self.assertEqual(self.service().drift(document), [])


class ApprovedLinesTest(BillingFixture):
    """Строки, утверждённые человеком в мастере (поле lines[] тела выставления).

    Мастер даёт исключить строку и поправить её текст и цену. Здесь
    закрепляется, что сервер эти правки применяет, но принимает их только
    поверх отбора: через lines[] нельзя ни добавить чужой проект, ни
    приписать часы, которых никто не списывал.
    """

    def selection(self, **kwargs):
        service = self.service()
        return service, service.collect(self.filters(**kwargs))

    @staticmethod
    def approved(line, **overrides):
        """Строка в том виде, в каком её шлёт мастер (buildBillingLinesPayload)."""
        row = {
            "project_id": line["project_id"],
            "title": line["title"],
            "hours": line["hours"],
            "rate": line["rate"],
            "amount": line["amount"],
            "sort": 10,
        }
        row.update(overrides)
        return row

    def test_no_lines_field_keeps_selection_as_is(self):
        """Обратная совместимость: контракт описывает тело ручки фильтром."""
        self.entry(1)
        service, selection = self.selection()

        self.assertIs(service.apply_approved_lines(selection, None), selection)

    def test_excluded_line_drops_its_entries(self):
        self.entry(1, employee_id="11", hours=2.0)
        self.entry(2, employee_id="12", hours=3.0)
        service, selection = self.selection(grouping="employee")
        self.assertEqual(len(selection.lines), 2)
        kept = next(line for line in selection.lines if line["title"] == "Цыганков Егор")

        result = service.apply_approved_lines(selection, [self.approved(kept)])

        self.assertEqual([row["timesheet_bitrix_id"] for row in result.entries], [1])
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.total_hours, 2.0)
        self.assertEqual(result.total_amount, 4000.0)

    def test_rate_edit_recounts_line_and_total(self):
        self.entry(1, hours=2.0, rate=2000.0)
        service, selection = self.selection()

        result = service.apply_approved_lines(
            selection, [self.approved(selection.lines[0], rate=2500)],
        )

        self.assertEqual(result.lines[0]["rate"], 2500.0)
        self.assertEqual(result.lines[0]["amount"], 5000.0)
        self.assertEqual(result.total_amount, 5000.0)
        # Часы правке не подлежат: строка обязана остаться суммой списаний.
        self.assertEqual(result.total_hours, 2.0)

    def test_client_amount_is_not_trusted(self):
        """Сумма считается из часов и цены, а не берётся из тела запроса."""
        self.entry(1, hours=2.0, rate=2000.0)
        service, selection = self.selection()

        result = service.apply_approved_lines(
            selection, [self.approved(selection.lines[0], rate=2500, amount=1.0)],
        )

        self.assertEqual(result.lines[0]["amount"], 5000.0)

    def test_title_edit_is_applied(self):
        self.entry(1)
        service, selection = self.selection()

        result = service.apply_approved_lines(
            selection, [self.approved(selection.lines[0], title="Работы по договору 12/26")],
        )

        self.assertEqual(result.lines[0]["title"], "Работы по договору 12/26")

    def test_untouched_line_keeps_its_amount_to_the_kopeck(self):
        """Строку без правки цены не пересчитываем.

        Сумма строки — сумма её списаний; часы на округлённую ставку дали бы
        5000.01 там, где списаний ровно на 5000.
        """
        self.entry(1, hours=1.0, rate=1000.0)
        self.entry(2, hours=2.0, rate=2000.0)
        service, selection = self.selection()
        self.assertEqual(selection.lines[0]["amount"], 5000.0)
        self.assertEqual(selection.lines[0]["rate"], 1666.67)

        result = service.apply_approved_lines(selection, [self.approved(selection.lines[0])])

        self.assertEqual(result.lines[0]["amount"], 5000.0)
        self.assertEqual(result.total_amount, 5000.0)

    def test_foreign_project_is_rejected(self):
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], project_id="88")],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)
        self.assertEqual(ctx.exception.status, 400)

    def test_inflated_hours_are_rejected(self):
        self.entry(1, hours=2.0)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], hours=10)],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)
        self.assertIn("не больше 2 ч", ctx.exception.message)

    def test_hours_changed_since_preview_are_rejected(self):
        self.entry(1, hours=2.0)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], hours=1.5)],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_negative_hours_are_rejected(self):
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], hours=-2)],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_negative_rate_is_rejected(self):
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], rate=-100)],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_unreadable_rate_is_rejected_not_zeroed(self):
        """Мусор в цене — отказ: ноль в счёте это отданная даром работа."""
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(
                selection, [self.approved(selection.lines[0], rate="дорого")],
            )

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_lines_must_be_a_list(self):
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(selection, {"project_id": "73"})

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_all_lines_excluded_is_empty_selection(self):
        self.entry(1)
        service, selection = self.selection()

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(selection, [])

        self.assertEqual(ctx.exception.code, "empty_selection")

    def test_one_selection_line_cannot_be_billed_twice(self):
        """Дубль строки в теле не удваивает счёт: строка отбора одна."""
        self.entry(1)
        service, selection = self.selection()
        row = self.approved(selection.lines[0])

        with self.assertRaises(BillingError) as ctx:
            service.apply_approved_lines(selection, [row, dict(row)])

        self.assertEqual(ctx.exception.code, ERROR_LINES_MISMATCH)

    def test_same_project_lines_are_matched_by_title(self):
        """Группировка по сотруднику даёт две строки одного проекта."""
        self.entry(1, employee_id="11", hours=2.0)
        self.entry(2, employee_id="12", hours=3.0)
        service, selection = self.selection(grouping="employee")
        first, second = selection.lines

        result = service.apply_approved_lines(
            selection, [self.approved(first), self.approved(second, title="Егор, август")],
        )

        self.assertEqual([line["title"] for line in result.lines], [first["title"], "Егор, август"])
        self.assertEqual(result.total_hours, 5.0)
