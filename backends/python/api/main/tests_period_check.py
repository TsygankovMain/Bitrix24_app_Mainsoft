"""Проверка перед закрытием месяца.

Вариант А из обсуждения 31.08.2026 — единственный дополнительный механизм,
взятый в первую версию. Смысл: закрыть месяц с мусором внутри хуже, чем не
закрыть, потому что потом это уже не поправить.

Ключевое требование, которое здесь и закрепляется: блокеры и предупреждения
не смешиваются. Блокер — данные сломаны, час потеряется. Предупреждение —
данные необычны, но так бывает законно. Если показывать одним списком и всё
равно разрешать закрытие, люди привыкнут нажимать «закрыть» не читая.
"""

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, PortalTask, PortalUser, TimesheetItem
from .period_check_service import LONG_DAY_HOURS, PeriodCheckService
from .period_service import PeriodService


class PeriodCheckTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-check",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.service = PeriodCheckService(self.account)

    def _entry(self, bitrix_id, *, day=15, hours=1.0, task_id="8365",
               project_id="73", employee_id="11", month=8):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id=employee_id, hours=hours, project_id=project_id,
            project_title="Мейнсофт", task_hierarchy_ids=[task_id] if task_id else [],
            task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, month, day, 0, 0)),
        )

    def _run(self):
        return self.service.run(2026, 8)

    # ---------- Чистый месяц ----------

    def test_clean_month_can_be_closed(self):
        self._entry(1)
        self._entry(2)

        result = self._run()

        self.assertTrue(result["can_close"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["stats"]["entries"], 2)
        self.assertEqual(result["stats"]["hours"], 2.0)

    def test_other_months_are_not_counted(self):
        self._entry(1, month=8)
        self._entry(2, month=7)
        self._entry(3, month=9)

        self.assertEqual(self._run()["stats"]["entries"], 1)

    # ---------- Блокеры ----------

    def test_entry_without_project_blocks(self):
        self._entry(1)
        self._entry(2, project_id="")

        result = self._run()

        self.assertFalse(result["can_close"])
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("no_project", codes)

    def test_entry_without_task_blocks(self):
        self._entry(1, task_id="")

        result = self._run()

        self.assertFalse(result["can_close"])
        self.assertIn("no_task", [b["code"] for b in result["blockers"]])

    def test_diverged_project_blocks(self):
        """Задача переехала, а карточки остались на старом проекте.

        Замораживать такой месяц рано: отчёт зафиксирует проект, который уже
        неверен. Именно это чинит фоновое выравнивание — значит оно не
        успело.
        """
        self._entry(1, project_id="459")
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Задача", group_id="73",
        )

        result = self._run()

        self.assertFalse(result["can_close"])
        self.assertIn("diverged_project", [b["code"] for b in result["blockers"]])

    def test_matching_project_does_not_block(self):
        self._entry(1, project_id="73")
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Задача", group_id="73",
        )

        self.assertTrue(self._run()["can_close"])

    # ---------- Предупреждения ----------

    def test_warnings_do_not_block(self):
        """Главное свойство разделения: необычное не мешает закрыть."""
        self._entry(1, hours=0)

        result = self._run()

        self.assertTrue(result["can_close"], "нулевые часы — не блокер")
        self.assertIn("zero_hours", [w["code"] for w in result["warnings"]])

    def test_silent_active_employee_is_warned(self):
        self._entry(1, employee_id="11")
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="303",
            name="Елена", last_name="Максимова", active=True,
        )

        result = self._run()

        self.assertTrue(result["can_close"])
        self.assertIn("silent_employees", [w["code"] for w in result["warnings"]])

    def test_fired_employee_is_not_warned(self):
        """Уволенный, естественно, ничего не списал — напоминать незачем."""
        self._entry(1, employee_id="11")
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="303",
            name="Бывший", last_name="Сотрудник", active=False,
        )

        self.assertNotIn("silent_employees", [w["code"] for w in self._run()["warnings"]])

    def test_long_day_is_warned(self):
        self._entry(1, hours=LONG_DAY_HOURS + 1)

        self.assertIn("long_days", [w["code"] for w in self._run()["warnings"]])

    def test_long_day_counts_sum_per_day(self):
        """Порог на СУММУ за день, а не на одну запись."""
        self._entry(1, hours=7)
        self._entry(2, hours=7)

        self.assertIn("long_days", [w["code"] for w in self._run()["warnings"]])

    def test_duplicates_counted_as_extra_rows(self):
        """Считаем лишние строки, а не группы: человеку важно, сколько строк
        потенциально задваивают сумму."""
        for bid in (1, 2, 3):
            self._entry(bid, hours=2.0, day=10)

        result = self._run()

        dup = next(w for w in result["warnings"] if w["code"] == "duplicates")
        self.assertEqual(dup["count"], 2, "три одинаковых записи — две лишних")

    # ---------- Детализация ----------

    def test_details_lists_offending_entries(self):
        self._entry(1, project_id="")
        self._entry(2, project_id="73")

        rows = self.service.details(2026, 8, "no_project")

        self.assertEqual([r["bitrix_id"] for r in rows], [1])

    def test_details_of_unknown_code_is_empty(self):
        self._entry(1)
        self.assertEqual(self.service.details(2026, 8, "чепуха"), [])


class LateArrivalsTest(TestCase):
    """Часы, созданные в Битриксе уже после закрытия периода.

    Их нельзя ни молча принять — цифры разойдутся с актом, ни молча выкинуть —
    человек потеряет работу. Показываем списком, решение за человеком.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-late",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.period = PeriodService(self.account).close(2026, 7, stats={}, by_id="11")

    def _entry(self, bitrix_id, created_at):
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id="1",
            employee_id="11", hours=4, project_id="73", project_title="Мейнсофт",
            task_hierarchy_ids=["1"], task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(datetime(2026, 7, 28, 0, 0)),
            source_created_at=created_at,
        )

    def test_entry_created_after_closing_is_listed(self):
        self._entry(1, self.period.closed_at + timezone.timedelta(days=2))

        rows = PeriodCheckService(self.account).late_arrivals(self.period)

        self.assertEqual([r["bitrix_id"] for r in rows], [1])

    def test_entry_created_before_closing_is_not_listed(self):
        self._entry(2, self.period.closed_at - timezone.timedelta(days=1))

        self.assertEqual(PeriodCheckService(self.account).late_arrivals(self.period), [])
