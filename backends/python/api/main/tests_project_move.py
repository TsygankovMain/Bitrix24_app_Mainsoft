"""Перенос задачи переписывает проект в самих карточках списания.

Решение пользователя от 31.08.2026: «мы в самой метке меняем проект? Мне нужно
чтобы менялся, а для истории делаем коммент было стало».

До этого приложение подставляло актуальный проект НА ЧТЕНИИ — снимок в
карточке оставался старым. Это чинило только наши отчёты: фильтры Битрикса,
выгрузки и человек, открывший карточку, продолжали видеть прежний проект.
Теперь правда пишется в источник.
"""

from django.test import TestCase

from .models import Bitrix24Account, TimesheetItem
from .project_move_service import MAX_ITEMS_PER_MOVE, ProjectMoveService


CONFIG = {
    "sp_entity_type_id": 1058,
    "fields_mapping": {
        "project_id": "ufProject",
        "project_title": "ufProjectName",
        "project_item_id": "ufProjectItem",
        "id_zadachi": "ufTask",
    },
}


class FakeToken:
    def __init__(self, fail_update_for=()):
        self.calls = []
        self.fail_update_for = set(str(i) for i in fail_update_for)

    def call_method(self, method, params):
        self.calls.append((method, params))
        if method == "crm.item.update" and str(params.get("id")) in self.fail_update_for:
            raise RuntimeError("Access denied: period is closed")
        return {"result": {}}


class FakeClient:
    def __init__(self, fail_update_for=()):
        self._bitrix_token = FakeToken(fail_update_for)


class ProjectMoveServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-move",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _entry(self, bitrix_id, task_id="8365", project_title="Мероприятие"):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=1, project_id="459", project_title=project_title,
            task_hierarchy_ids=[task_id], task_hierarchy_titles=["Задача"],
            date_reflection="2026-08-31T10:00:00+00:00",
        )

    def _service(self, client=None):
        return ProjectMoveService(client or FakeClient(), self.account, CONFIG)

    def test_all_cards_of_task_are_rewritten(self):
        for i in (1, 2, 3):
            self._entry(i)
        client = FakeClient()

        result = self._service(client).apply_move(
            "8365", old_group="459", new_group="73", new_group_name="Мейнсофт",
        )

        self.assertEqual(result["updated"], 3)
        updates = [c for c in client._bitrix_token.calls if c[0] == "crm.item.update"]
        self.assertEqual(len(updates), 3)
        self.assertEqual(updates[0][1]["fields"]["ufProject"], "73")
        self.assertEqual(updates[0][1]["fields"]["ufProjectName"], "Мейнсофт")

    def test_stale_project_item_id_is_cleared(self):
        """project_item_id — снимок элемента СП СТАРОГО проекта.

        Оставить его значило бы получить карточку, которая ссылается на группу
        одного проекта и на элемент другого.
        """
        self._entry(1)
        client = FakeClient()

        self._service(client).apply_move("8365", "459", "73", "Мейнсофт")

        fields = client._bitrix_token.calls[0][1]["fields"]
        self.assertEqual(fields["ufProjectItem"], "")

    def test_comment_records_before_and_after(self):
        self._entry(1, project_title="Мероприятие «Честный знак»")
        client = FakeClient()

        self._service(client).apply_move(
            "8365", "459", "73", "Мейнсофт",
            moved_by_name="Егор Цыганков", moved_at="2026-08-31 17:51:52",
        )

        comments = [c for c in client._bitrix_token.calls if c[0] == "crm.timeline.comment.add"]
        self.assertEqual(len(comments), 1)
        text = comments[0][1]["fields"]["COMMENT"]
        self.assertIn("было «Мероприятие «Честный знак»»", text)
        self.assertIn("стало «Мейнсофт»", text)
        self.assertIn("Егор Цыганков", text)
        self.assertIn("Часы и дата списания не менялись", text)

    def test_closed_period_refusal_is_reported_not_swallowed(self):
        """Закрытый период — сработавшая защита, но знать о ней нужно.

        Иначе расхождение между задачей и её записями обнаружится через
        полгода, при сверке с клиентом.
        """
        for i in (1, 2, 3):
            self._entry(i)
        client = FakeClient(fail_update_for=[2])

        result = self._service(client).apply_move("8365", "459", "73", "Мейнсофт")

        self.assertEqual(result["updated"], 2)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["item"], "2")
        self.assertIn("closed", result["failed"][0]["error"])

    def test_failed_card_gets_no_comment(self):
        """Комментарий про смену проекта на карточке, которую не сменили, — ложь."""
        self._entry(1)
        client = FakeClient(fail_update_for=[1])

        self._service(client).apply_move("8365", "459", "73", "Мейнсофт")

        comments = [c for c in client._bitrix_token.calls if c[0] == "crm.timeline.comment.add"]
        self.assertEqual(comments, [])

    def test_volume_is_capped(self):
        """Хвост распределения длинный: у задачи 4627 на проде 260 записей."""
        for i in range(1, MAX_ITEMS_PER_MOVE + 6):
            self._entry(i)
        client = FakeClient()

        result = self._service(client).apply_move("8365", "459", "73", "Мейнсофт")

        self.assertEqual(result["updated"], MAX_ITEMS_PER_MOVE)
        self.assertEqual(result["over_limit"], 5)

    def test_other_tasks_are_untouched(self):
        self._entry(1, task_id="8365")
        self._entry(2, task_id="9999")
        client = FakeClient()

        self._service(client).apply_move("8365", "459", "73", "Мейнсофт")

        updates = [c for c in client._bitrix_token.calls if c[0] == "crm.item.update"]
        self.assertEqual([c[1]["id"] for c in updates], [1])

    def test_unconfigured_portal_is_skipped_quietly(self):
        self._entry(1)
        service = ProjectMoveService(FakeClient(), self.account, {"sp_entity_type_id": 0})

        result = service.apply_move("8365", "459", "73", "Мейнсофт")

        self.assertEqual(result["skipped"], "not_configured")

    def test_comment_falls_back_to_group_id(self):
        """Имя группы не резолвилось — пишем идентификатор, а не пустоту."""
        self._entry(1, project_title="")
        client = FakeClient()

        self._service(client).apply_move("8365", "459", "73", new_group_name="")

        text = [c for c in client._bitrix_token.calls
                if c[0] == "crm.timeline.comment.add"][0][1]["fields"]["COMMENT"]
        self.assertIn("группа 459", text)
        self.assertIn("группа 73", text)
