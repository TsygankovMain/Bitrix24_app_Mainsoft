"""Демо-данные для мастера выставления: команда billing_demo_data.

Что здесь закрепляется, кроме арифметики.

1. Сгенерированное ПОПАДАЕТ В ОТБОР BillingService — проверяется через сам
   сервис, а не сверкой полей. Демо, которое лежит в базе, но мастер его не
   видит, бесполезно, а разойтись легко: проект резолвится по трём ключам
   карточки, и достаточно не заполнить project_item_id.
2. --purge удаляет ТОЛЬКО демо. Команда чистит по двум признакам разом
   (диапазон id и префикс описания), и тесты держат оба: запись с демо-id без
   префикса и запись с префиксом вне диапазона должны выжить.
3. --dry-run не пишет ничего. Отдельный тест, потому что «план» и «запись»
   здесь один код, и потерять ветку легко.
4. Повторный прогон отказывает. Идемпотентность выбрана отказом, а не
   пропуском: молча дописать второй комплект демо-часов в отбор счёта хуже,
   чем не запуститься.
"""

from datetime import datetime, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .billing_service import BillingFilter, BillingService
from .management.commands.billing_demo_data import DEMO_ID_BASE, DEMO_PREFIX, DEMO_STATS_FLAG
from .models import (
    Bitrix24Account,
    ClosedPeriod,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)
from .period_service import PeriodService


DEMO_SETTINGS = {"allow_open_period": False, "accountants": [], "act_template_id": 0}


class DemoCommandFixture(TestCase):
    """Портал с двумя клиентами, тремя карточками и одной РЕАЛЬНОЙ записью."""

    def setUp(self):
        self.admin = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-demo",
            is_master_account=True, domain_url="demo.bitrix24.ru",
            status="active", application_version=1,
        )
        self.colleague = Bitrix24Account.objects.create(
            b24_user_id=12, is_b24_user_admin=False, member_id="m-demo",
            is_master_account=False, domain_url="demo.bitrix24.ru",
            status="active", application_version=1,
        )
        self.stranger = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-other",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )

        for account in (self.admin, self.colleague):
            PortalUser.objects.create(
                bitrix24_account=account, bitrix_id="11",
                name="Егор", last_name="Цыганков",
            )
            PortalUser.objects.create(
                bitrix24_account=account, bitrix_id="12",
                name="Анна", last_name="Петрова",
            )
            ProjectCard.objects.create(
                bitrix24_account=account, project_id="73", project_item_id="730",
                project_name="Мейнсофт", stage="in_work", hourly_rate=2000.0,
                company_id="15", company_name="ООО Клиент",
                our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
            )
            ProjectCard.objects.create(
                bitrix24_account=account, project_id="74", project_item_id="740",
                project_name="Мейнсофт-2", stage="in_work", hourly_rate=1500.0,
                company_id="15", company_name="ООО Клиент",
                our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
            )
            ProjectCard.objects.create(
                bitrix24_account=account, project_id="88", project_item_id="880",
                project_name="Второй", stage="in_work", hourly_rate=1000.0,
                company_id="16", company_name="ООО Второй",
                our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
            )
            # Карточка без клиента: демо на неё вешаться не должно.
            ProjectCard.objects.create(
                bitrix24_account=account, project_id="99", project_item_id="990",
                project_name="Без клиента", stage="in_work", hourly_rate=3000.0,
            )

        self.real = TimesheetItem.objects.create(
            bitrix24_account=self.admin, bitrix_id=4242, task_id="8365",
            employee_id="11", hours=7.0, is_billable=True,
            project_id="73", project_item_id="730", project_title="Мейнсофт",
            hourly_rate_snapshot=2000.0, description="настоящая работа",
            task_hierarchy_ids=["8365"], task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, 8, 10, 0, 0)),
        )

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command("billing_demo_data", *args, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def generate(self, *extra):
        return self.run_command(
            "--domain", "demo.bitrix24.ru",
            "--months", "2026-08",
            "--entries-per-month", "40",
            "--projects", "3",
            "--clients", "2",
            *extra,
        )

    def demo_items(self, account=None):
        return TimesheetItem.objects.filter(
            bitrix24_account=account or self.admin,
            description__startswith=DEMO_PREFIX,
        )

    def service(self, account=None):
        return BillingService(account or self.admin, client=object(), settings=DEMO_SETTINGS)

    def filters(self, **kwargs):
        payload = {"date_from": "2026-08-01", "date_to": "2026-08-31"}
        payload.update(kwargs)
        return BillingFilter.from_payload(payload)


class GenerationTest(DemoCommandFixture):
    def test_creates_requested_number_of_entries_for_every_account(self):
        self.generate()

        self.assertEqual(self.demo_items(self.admin).count(), 40)
        self.assertEqual(self.demo_items(self.colleague).count(), 40)

    def test_other_portals_are_untouched(self):
        self.generate()

        self.assertFalse(TimesheetItem.objects.filter(bitrix24_account=self.stranger).exists())

    def test_demo_entries_are_marked_by_id_range_and_prefix(self):
        self.generate()

        for item in self.demo_items():
            self.assertGreaterEqual(item.bitrix_id, DEMO_ID_BASE)
            self.assertTrue(item.description.startswith(DEMO_PREFIX))

    def test_entries_land_on_august_working_days_only(self):
        self.generate()

        for item in self.demo_items():
            day = timezone.localtime(item.date_reflection)
            self.assertEqual((day.year, day.month), (2026, 8))
            self.assertLess(day.weekday(), 5)

    def test_hours_are_plausible_half_hour_steps(self):
        self.generate()

        for item in self.demo_items():
            self.assertGreaterEqual(item.hours, 0.5)
            self.assertLessEqual(item.hours, 8.0)
            self.assertEqual(round(item.hours * 2) % 1, 0)

    def test_some_entries_are_non_billable_and_some_have_no_rate_snapshot(self):
        self.generate()

        items = list(self.demo_items())
        self.assertTrue(any(not item.is_billable for item in items))
        self.assertTrue(any(item.is_billable for item in items))
        self.assertTrue(any(item.hourly_rate_snapshot is None for item in items))
        self.assertTrue(any(item.hourly_rate_snapshot is not None for item in items))

    def test_only_cards_with_company_are_used(self):
        self.generate()

        used = set(self.demo_items().values_list("project_id", flat=True))
        self.assertNotIn("99", used)
        self.assertTrue(used.issubset({"73", "74", "88"}))

    def test_entries_spread_over_requested_projects(self):
        self.generate()

        used = set(self.demo_items().values_list("project_id", flat=True))
        self.assertEqual(used, {"73", "74", "88"})

    def test_future_months_are_skipped(self):
        """Списаний «из будущего» не бывает: месяц вперёд остаётся пустым."""
        today = timezone.localdate()
        ahead = (today.replace(day=1) + timedelta(days=40)).replace(day=1)

        output = self.run_command(
            "--domain", "demo.bitrix24.ru",
            "--months", f"{ahead.year}-{ahead.month:02d}",
            "--entries-per-month", "10",
        )

        self.assertEqual(self.demo_items().count(), 0)
        self.assertIn("рабочих дней в прошлом нет", output)

    def test_unknown_domain_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command("--domain", "nowhere.bitrix24.ru")

    def test_domain_is_required(self):
        with self.assertRaises(CommandError):
            self.run_command()


class SelectionTest(DemoCommandFixture):
    """Главное: мастер выставления видит сгенерированное."""

    def test_preview_returns_lines_and_totals_for_the_client(self):
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(self.filters(company_id="15"))

        self.assertTrue(selection.lines)
        self.assertGreater(selection.total_hours, 0)
        self.assertGreater(selection.total_amount, 0)
        self.assertEqual(selection.companies, [{"id": "15", "name": "ООО Клиент"}])

    def test_preview_totals_match_the_generated_hours(self):
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(self.filters(company_id="16"))
        expected = sum(
            item.hours
            for item in self.demo_items().filter(project_id="88", is_billable=True)
        )

        self.assertEqual(selection.total_hours, round(expected, 2))
        self.assertEqual(selection.total_amount, round(expected * 1000.0, 2))

    def test_lines_are_grouped_per_project_of_one_client(self):
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(
            self.filters(company_id="15", grouping="project"),
        )

        self.assertEqual(
            sorted(line["subject"] for line in selection.lines),
            ["Мейнсофт", "Мейнсофт-2"],
        )

    def test_entries_without_snapshot_take_the_card_rate(self):
        self.generate("--close-month", "2026-08")
        rates = {"73": 2000.0, "74": 1500.0, "88": 1000.0}
        no_snapshot = list(self.demo_items().filter(
            hourly_rate_snapshot__isnull=True, is_billable=True, project_id="73",
        ))
        self.assertTrue(no_snapshot)

        selection = self.service().collect(self.filters(company_id="15"))
        by_id = {item["timesheet_bitrix_id"]: item for item in selection.entries}

        for item in no_snapshot:
            self.assertEqual(by_id[item.bitrix_id]["rate_snapshot"], rates[item.project_id])

    def test_no_rate_warning_does_not_appear(self):
        """Ставка есть у каждой демо-записи — предупреждения быть не должно."""
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(self.filters(company_id="15"))

        self.assertNotIn("no_rate", selection.warning_codes())

    def test_mixed_companies_blocks_until_client_is_chosen(self):
        """Без фильтра по клиенту в отборе два клиента — это и должно мешать."""
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(self.filters())

        self.assertIn("mixed_companies", selection.warning_codes())


class ClosePeriodTest(DemoCommandFixture):
    def test_close_month_makes_the_period_closed(self):
        self.generate("--close-month", "2026-08")

        self.assertTrue(PeriodService(self.admin).is_closed(
            timezone.make_aware(datetime(2026, 8, 20, 0, 0))
        ))
        self.assertTrue(PeriodService(self.colleague).is_closed(
            timezone.make_aware(datetime(2026, 8, 20, 0, 0))
        ))

    def test_closed_period_carries_the_standard_stats_snapshot(self):
        self.generate("--close-month", "2026-08")

        period = ClosedPeriod.objects.get(bitrix24_account=self.admin, year=2026, month=8)

        self.assertEqual(period.stats["entries"], self.demo_items().count() + 1)
        self.assertAlmostEqual(
            period.stats["hours"],
            sum(item.hours for item in self.demo_items()) + 7.0,
            places=2,
        )
        self.assertIn("employees", period.stats)
        self.assertIn("projects", period.stats)
        self.assertTrue(period.stats[DEMO_STATS_FLAG])

    def test_selection_only_closed_periods_sees_the_month(self):
        self.generate("--close-month", "2026-08")

        selection = self.service().collect(
            self.filters(company_id="15", only_closed_periods=True)
        )

        self.assertTrue(selection.entries)
        self.assertNotIn("period_open", selection.warning_codes())

    def test_without_close_month_the_period_stays_open(self):
        self.generate()

        self.assertFalse(ClosedPeriod.objects.exists())
        selection = self.service().collect(self.filters(company_id="15"))
        self.assertIn("period_open", selection.warning_codes())


class PurgeTest(DemoCommandFixture):
    def test_purge_removes_demo_entries_and_periods(self):
        self.generate("--close-month", "2026-08")

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.assertEqual(self.demo_items(self.admin).count(), 0)
        self.assertEqual(self.demo_items(self.colleague).count(), 0)
        self.assertFalse(ClosedPeriod.objects.exists())

    def test_purge_keeps_real_entries(self):
        self.generate()

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.real.refresh_from_db()
        self.assertEqual(self.real.hours, 7.0)
        self.assertEqual(TimesheetItem.objects.filter(bitrix24_account=self.admin).count(), 1)

    def test_purge_keeps_a_real_entry_that_landed_in_the_demo_id_range(self):
        """Один признак — не основание удалять: id в диапазоне, описание чужое."""
        intruder = TimesheetItem.objects.create(
            bitrix24_account=self.colleague, bitrix_id=DEMO_ID_BASE + 5, task_id="1",
            employee_id="11", hours=1.0, is_billable=True, project_id="73",
            project_title="Мейнсофт", description="настоящая запись портала",
            date_reflection=timezone.make_aware(datetime(2026, 8, 11, 0, 0)),
        )

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.assertTrue(TimesheetItem.objects.filter(pk=intruder.pk).exists())

    def test_purge_keeps_an_entry_with_demo_prefix_outside_the_id_range(self):
        marked = TimesheetItem.objects.create(
            bitrix24_account=self.admin, bitrix_id=777, task_id="1",
            employee_id="11", hours=1.0, is_billable=True, project_id="73",
            project_title="Мейнсофт", description=f"{DEMO_PREFIX}набрано руками",
            date_reflection=timezone.make_aware(datetime(2026, 8, 11, 0, 0)),
        )

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.assertTrue(TimesheetItem.objects.filter(pk=marked.pk).exists())

    def test_purge_keeps_periods_closed_by_a_human(self):
        PeriodService(self.admin).close(2026, 7, stats={"hours": 10.0}, by_id="11", by_name="Егор")

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.assertTrue(ClosedPeriod.objects.filter(year=2026, month=7).exists())

    def test_purge_of_other_portal_data_does_not_happen(self):
        foreign = TimesheetItem.objects.create(
            bitrix24_account=self.stranger, bitrix_id=DEMO_ID_BASE + 1, task_id="1",
            employee_id="11", hours=1.0, is_billable=True, project_id="73",
            project_title="Мейнсофт", description=f"{DEMO_PREFIX}чужой портал",
            date_reflection=timezone.make_aware(datetime(2026, 8, 11, 0, 0)),
        )

        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.assertTrue(TimesheetItem.objects.filter(pk=foreign.pk).exists())


class DryRunTest(DemoCommandFixture):
    def test_dry_run_writes_nothing(self):
        output = self.generate("--close-month", "2026-08", "--dry-run")

        self.assertEqual(self.demo_items().count(), 0)
        self.assertFalse(ClosedPeriod.objects.exists())
        self.assertIn("--dry-run", output)

    def test_dry_run_still_shows_the_plan(self):
        output = self.generate("--close-month", "2026-08", "--dry-run")

        self.assertIn("ООО Клиент", output)
        self.assertIn("Август 2026", output)

    def test_dry_run_does_not_freeze_sync(self):
        self.generate("--dry-run", "--freeze-sync")

        self.admin.refresh_from_db()
        self.assertIsNone(self.admin.sync_disabled_until)

    def test_dry_run_does_not_delete(self):
        self.generate()
        before = self.demo_items().count()

        self.run_command("--domain", "demo.bitrix24.ru", "--purge", "--dry-run")

        self.assertEqual(self.demo_items().count(), before)


class IdempotencyTest(DemoCommandFixture):
    def test_second_run_is_refused(self):
        self.generate()

        with self.assertRaises(CommandError) as caught:
            self.generate()

        self.assertIn("--purge", str(caught.exception))
        self.assertEqual(self.demo_items().count(), 40)

    def test_replace_regenerates_without_duplicates(self):
        self.generate()

        self.generate("--replace")

        self.assertEqual(self.demo_items().count(), 40)

    def test_purge_then_generate_works(self):
        self.generate()
        self.run_command("--domain", "demo.bitrix24.ru", "--purge")

        self.generate()

        self.assertEqual(self.demo_items().count(), 40)

    def test_same_seed_gives_the_same_data(self):
        self.generate()
        first = sorted(self.demo_items().values_list("bitrix_id", "hours", "project_id"))

        self.generate("--replace")
        second = sorted(self.demo_items().values_list("bitrix_id", "hours", "project_id"))

        self.assertEqual(first, second)

    def test_foreign_entry_in_the_id_range_stops_generation(self):
        TimesheetItem.objects.create(
            bitrix24_account=self.admin, bitrix_id=DEMO_ID_BASE + 3, task_id="1",
            employee_id="11", hours=1.0, is_billable=True, project_id="73",
            project_title="Мейнсофт", description="запись портала",
            date_reflection=timezone.make_aware(datetime(2026, 8, 11, 0, 0)),
        )

        with self.assertRaises(CommandError) as caught:
            self.generate()

        self.assertIn("--id-base", str(caught.exception))


class FreezeSyncTest(DemoCommandFixture):
    def test_freeze_sync_pauses_every_account_of_the_portal(self):
        self.generate("--freeze-sync")

        for account in (self.admin, self.colleague):
            account.refresh_from_db()
            self.assertIsNotNone(account.sync_disabled_until)
            self.assertGreater(
                account.sync_disabled_until, timezone.now() + timedelta(days=300)
            )

    def test_freeze_sync_leaves_other_portals_alone(self):
        self.generate("--freeze-sync")

        self.stranger.refresh_from_db()
        self.assertIsNone(self.stranger.sync_disabled_until)

    def test_sync_warning_is_printed_even_without_the_flag(self):
        output = self.generate()

        self.assertIn("физически удаляет", output)
        self.assertIn("--freeze-sync", output)


class ReportTest(DemoCommandFixture):
    def test_report_names_hours_money_clients_and_next_steps(self):
        output = self.generate("--close-month", "2026-08")

        self.assertIn("ООО Клиент", output)
        self.assertIn("ООО Второй", output)
        self.assertIn("Мейнсофт-2", output)
        self.assertIn("billing_feature --domain demo.bitrix24.ru --state on", output)
        self.assertIn("Август 2026", output)

    def test_report_warns_when_nothing_was_closed(self):
        output = self.generate()

        self.assertIn("Закрытых периодов нет", output)
