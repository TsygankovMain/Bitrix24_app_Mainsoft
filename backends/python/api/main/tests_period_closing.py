"""Закрытие месяца: заморозка часов за период.

Решения заказчика 31.08.2026: портал целиком, опоздавшие часы требуют
переоткрытия, записи после закрытия заморожены и правке не подлежат.

Отчёт по часам — основание для счёта клиенту. Пока месяц открыт, его цифры
могут поехать: сотрудник допишет часы задним числом, кто-то перенесёт задачу
в другой проект, и приложение перепишет проект во всех её карточках. После
выставления акта это недопустимо.
"""

from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, ClosedPeriod, TimesheetItem
from .period_service import PeriodService, period_of
from .project_move_service import ProjectMoveService
from .timesheet_write_service import TimesheetWriteError, TimesheetWriteService


CONFIG = {
    "sp_entity_type_id": 1058,
    "fields_mapping": {
        "data": "ufDate",
        "id_zadachi": "ufTask",
        "project_id": "ufProject",
        "project_title": "ufProjectName",
        "project_item_id": "ufProjectItem",
    },
}


class FakeToken:
    def __init__(self):
        self.calls = []

    def call_method(self, method, params):
        self.calls.append((method, params))
        return {"result": {"item": {"id": 1}}}


class FakeClient:
    def __init__(self):
        self._bitrix_token = FakeToken()


class PeriodBoundariesTest(TestCase):
    """Месяц берётся из даты списания.

    date_reflection хранит КАЛЕНДАРНУЮ ДАТУ, а не момент: на проде 31.08.2026
    из ~7 100 записей 6 651 лежит ровно на 00:00. Дату выбирают в календаре,
    время в неё не вкладывают — поэтому месяц читается прямо из неё.
    """

    def test_midnight_gives_the_chosen_day(self):
        """Типовой случай: 99% записей выглядят именно так."""
        value = datetime(2026, 8, 31, 0, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(period_of(value), (2026, 8))

    def test_first_day_of_month_belongs_to_new_month(self):
        value = datetime(2026, 9, 1, 0, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(period_of(value), (2026, 9))

    def test_iso_string_is_accepted(self):
        """Дата приходит с фронта строкой — разбирать её должен сервис."""
        self.assertEqual(period_of("2026-08-15T10:00:00+03:00"), (2026, 8))

    def test_empty_date_has_no_period(self):
        """Запись без даты закрытым периодом не ограничивается —
        её отловит проверка перед закрытием как блокер."""
        self.assertIsNone(period_of(None))
        self.assertIsNone(period_of(""))


class ClosingAndReopeningTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-period",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        self.service = PeriodService(self.account)

    def test_closed_period_is_detected(self):
        self.service.close(2026, 8, stats={"hours": 1284.5, "entries": 7137},
                           by_id="11", by_name="Егор Цыганков")

        value = timezone.make_aware(datetime(2026, 8, 15, 10, 0))
        self.assertTrue(PeriodService(self.account).is_closed(value))

    def test_other_months_stay_open(self):
        self.service.close(2026, 8, stats={}, by_id="11")

        fresh = PeriodService(self.account)
        self.assertFalse(fresh.is_closed(timezone.make_aware(datetime(2026, 7, 15))))
        self.assertFalse(fresh.is_closed(timezone.make_aware(datetime(2026, 9, 1))))

    def test_reopened_period_is_open_again(self):
        self.service.close(2026, 8, stats={}, by_id="11")
        self.service.reopen(2026, 8, reason="Учесть 3 записи после закрытия",
                            by_id="11", by_name="Егор Цыганков")

        value = timezone.make_aware(datetime(2026, 8, 15))
        self.assertFalse(PeriodService(self.account).is_closed(value))

    def test_reopen_keeps_the_journal(self):
        """Строка остаётся как журнал события, а не удаляется."""
        self.service.close(2026, 8, stats={}, by_id="11")
        self.service.reopen(2026, 8, reason="Ошиблись с датой", by_id="303",
                            by_name="Елена Максимова")

        row = ClosedPeriod.objects.get(year=2026, month=8)
        self.assertEqual(row.reopen_reason, "Ошиблись с датой")
        self.assertEqual(row.reopened_by_name, "Елена Максимова")
        self.assertIsNotNone(row.closed_at, "факт закрытия не должен теряться")

    def test_closing_again_after_reopen(self):
        self.service.close(2026, 8, stats={}, by_id="11")
        self.service.reopen(2026, 8, reason="поправить", by_id="11")
        self.service.close(2026, 8, stats={"hours": 1292.0}, by_id="11")

        row = ClosedPeriod.objects.get(year=2026, month=8)
        self.assertIsNone(row.reopened_at, "повторное закрытие снимает признак")
        self.assertEqual(row.stats["hours"], 1292.0)
        self.assertEqual(ClosedPeriod.objects.count(), 1, "дублей быть не должно")

    def test_reopen_of_open_period_does_nothing(self):
        self.assertIsNone(self.service.reopen(2026, 8, reason="x", by_id="11"))

    def test_refusal_message_names_period_and_date(self):
        """Человек должен понимать, что произошло и к кому идти."""
        period = self.service.close(2026, 8, stats={}, by_id="11")

        text = self.service.refusal_message(period)
        self.assertIn("Август 2026", text)
        self.assertIn("администратору", text)


class WriteIsBlockedInClosedPeriodTest(TestCase):
    """Запрет записи — одна проверка на все пять точек списания.

    Ровно ради этого запись и переносили из браузера на бэкенд: в браузере
    такое правило снималось бы правкой JS.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-block",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        PeriodService(self.account).close(2026, 8, stats={}, by_id="11")
        self.client_stub = FakeClient()

    def _service(self):
        with mock.patch.object(Bitrix24Account, "client", self.client_stub):
            return TimesheetWriteService(self.account, CONFIG)

    def test_create_into_closed_month_is_refused(self):
        with self.assertRaises(TimesheetWriteError) as ctx:
            self._service().create({"ufDate": "2026-08-15T10:00:00+03:00", "ufTask": "1"})

        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("Август 2026", ctx.exception.message)
        self.assertEqual(self.client_stub._bitrix_token.calls, [],
                         "в Битрикс не должно уйти ничего")

    def test_update_into_closed_month_is_refused(self):
        with self.assertRaises(TimesheetWriteError):
            self._service().update(5, {"ufDate": "2026-08-15T10:00:00+03:00"})

    def test_open_month_passes(self):
        result = self._service().create({"ufDate": "2026-09-01T10:00:00+03:00", "ufTask": "1"})

        self.assertEqual(result["status"], "success")

    def test_entry_without_date_is_not_blocked(self):
        """Блокировать нечего: такую запись поймает проверка перед закрытием.

        Отказать человеку в списании из-за отсутствующего поля даты было бы
        хуже — он не поймёт, что делать.
        """
        result = self._service().create({"ufTask": "1"})

        self.assertEqual(result["status"], "success")


class ProjectRewriteSkipsClosedTest(TestCase):
    """Перенос задачи не трогает карточки закрытых периодов.

    Отсекаем на нашей стороне, а не упираемся в отказ прав Битрикса: иначе
    каждый прогон выравнивания давал бы пачку бесполезных обращений и мусор в
    логе.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-skip",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        # Август закрыт, сентябрь открыт.
        PeriodService(self.account).close(2026, 8, stats={}, by_id="11")
        self._entry(1, datetime(2026, 8, 15, 10, 0))   # закрытый
        self._entry(2, datetime(2026, 9, 3, 10, 0))    # открытый

    def _entry(self, bitrix_id, when):
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id="8365",
            employee_id="11", hours=1, project_id="459", project_title="Старый",
            task_hierarchy_ids=["8365"], task_hierarchy_titles=["Задача"],
            date_reflection=timezone.make_aware(when),
        )

    def test_only_open_period_cards_are_rewritten(self):
        client = FakeClient()
        service = ProjectMoveService(client, self.account, CONFIG)

        result = service.apply_move("8365", "459", "73", "Мейнсофт")

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped_closed"], 1)
        updates = [c for c in client._bitrix_token.calls if c[0] == "crm.item.update"]
        self.assertEqual([c[1]["id"] for c in updates], [2],
                         "карточка закрытого периода трогаться не должна")

    def test_task_becomes_split_between_projects(self):
        """Прямое следствие заморозки: свежие часы в новом проекте, закрытые
        остались в старом. Так и должно быть — это зафиксированная история."""
        service = ProjectMoveService(FakeClient(), self.account, CONFIG)

        result = service.apply_move("8365", "459", "73", "Мейнсофт")

        self.assertEqual(result["updated"] + result["skipped_closed"], 2)
