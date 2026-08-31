"""Перенос задачи переписывает проект в самих карточках списания.

Решение пользователя от 31.08.2026: «мы в самой метке меняем проект? Мне нужно
чтобы менялся, а для истории делаем коммент было стало».

До этого приложение подставляло актуальный проект НА ЧТЕНИИ — снимок в
карточке оставался старым. Это чинило только наши отчёты: фильтры Битрикса,
выгрузки и человек, открывший карточку, продолжали видеть прежний проект.
Теперь правда пишется в источник.
"""

from django.test import TestCase

from .models import Bitrix24Account, PortalTask, TimesheetItem
from .project_move_service import (
    MAX_ITEMS_PER_MOVE,
    MAX_ITEMS_PER_MOVE_INTERACTIVE,
    ProjectMoveService,
)
from .task_sync_service import TaskSyncService


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

    def test_interactive_cap_is_smaller(self):
        """У кнопки «Обновить» нет своего таймаута, а прокси хостинга рвёт
        соединение примерно через минуту. Сто обновлений плюс сто комментариев
        внутри запроса кнопки — это десятки секунд, поэтому интерактивный
        потолок отдельный и низкий, а остаток доделывает фон."""
        for i in range(1, 26):
            self._entry(i)
        client = FakeClient()

        result = self._service(client).apply_move(
            "8365", "459", "73", "Мейнсофт",
            max_items=MAX_ITEMS_PER_MOVE_INTERACTIVE,
        )

        self.assertEqual(result["updated"], MAX_ITEMS_PER_MOVE_INTERACTIVE)
        self.assertEqual(result["over_limit"], 25 - MAX_ITEMS_PER_MOVE_INTERACTIVE)


class ReconcileDivergenceTest(TestCase):
    """Выравнивание того, что событийный механизм пропустил.

    Переписывание срабатывает на СМЕНУ группы. Всё, что смены не застало,
    иначе расходилось бы навсегда: остаток от интерактивного вызова (кнопка
    берёт малую порцию, а справочник уже зафиксировал новую группу, и
    повторно «смена» не случится), историческое расхождение — на проде 60
    записей по 28 задачам, — и любые пропуски.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-reconcile",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def _entry(self, bitrix_id, task_id, project_id):
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=1, project_id=project_id, project_title="Старый",
            task_hierarchy_ids=[task_id], task_hierarchy_titles=["Задача"],
            date_reflection="2026-08-31T10:00:00+00:00",
        )

    def _task(self, bitrix_id, group_id):
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id,
            title="Задача", group_id=group_id,
        )

    def _service(self):
        service = TaskSyncService(client=None, account=self.account)
        service.applied = []
        service._apply_project_moves = lambda moves: service.applied.extend(moves)
        return service

    def test_diverged_task_is_picked_up(self):
        self._entry(1, "8365", "459")
        self._task("8365", "73")
        service = self._service()

        result = service.reconcile_project_divergence()

        self.assertEqual(result["tasks"], 1)
        self.assertEqual(service.applied[0]["old_group"], "459")
        self.assertEqual(service.applied[0]["new_group"], "73")

    def test_matching_task_is_left_alone(self):
        self._entry(1, "8365", "73")
        self._task("8365", "73")
        service = self._service()

        self.assertEqual(service.reconcile_project_divergence()["tasks"], 0)
        self.assertEqual(service.applied, [])

    def test_task_without_directory_row_is_skipped(self):
        """Нет группы в справочнике — сравнивать не с чем, трогать нельзя."""
        self._entry(1, "9999", "459")
        service = self._service()

        self.assertEqual(service.reconcile_project_divergence()["tasks"], 0)

    def test_limit_caps_tasks_per_run(self):
        """Фоновая уборка, ей некуда спешить: держать синк минутами незачем."""
        for i in range(1, 11):
            self._entry(i, f"task{i}", "459")
            self._task(f"task{i}", "73")
        service = self._service()

        service.reconcile_project_divergence(limit=3)

        self.assertEqual(len(service.applied), 3)


class RewriteMirrorsLocallyTest(TestCase):
    """Переписывание отражается в нашей базе, иначе выравнивание зацикливается.

    Боевой случай 31.08.2026. Выравнивание ищет расхождения, СМОТРЯ В НАШУ
    БАЗУ. Переписывание меняло карточку в Битриксе, но локальная строка
    оставалась прежней до ближайшего синка таймшитов — и следующий прогон
    видел то же расхождение и делал работу заново, снова оставляя комментарий
    на каждой карточке.

    Цикл выравнивания (10 минут) короче цикла синка (20 минут), поэтому за час
    каждая из 23 задач была переписана ПО ЧЕТЫРЕ РАЗА, и на карточках
    накопилось по четыре одинаковых комментария вместо одного.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-mirror",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        for bid in (1, 2):
            TimesheetItem.objects.create(
                bitrix24_account=self.account, bitrix_id=bid, task_id="8365",
                employee_id="11", hours=1, project_id="459",
                project_title="Мероприятие", project_item_id="253",
                task_hierarchy_ids=["8365"], task_hierarchy_titles=["Задача"],
                date_reflection="2026-08-31T10:00:00+00:00",
            )

    def test_local_rows_updated_after_successful_rewrite(self):
        ProjectMoveService(FakeClient(), self.account, CONFIG).apply_move(
            "8365", "459", "73", "Мейнсофт",
        )

        rows = TimesheetItem.objects.filter(task_id="8365")
        self.assertEqual({r.project_id for r in rows}, {"73"})
        self.assertEqual({r.project_title for r in rows}, {"Мейнсофт"})
        self.assertEqual({r.project_item_id for r in rows}, {""},
                         "ссылка на элемент старого проекта должна быть снята")

    def test_second_run_finds_nothing(self):
        """Ядро дефекта: повторный прогон не должен делать работу заново."""
        service = TaskSyncService(client=None, account=self.account)
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Задача", group_id="73",
        )

        # До переписывания расхождение есть и выравнивание его видит.
        first = service.reconcile_project_divergence()
        self.assertEqual(first["tasks"], 1)

        # Переписали — локальные строки отражены, расхождения больше нет.
        ProjectMoveService(FakeClient(), self.account, CONFIG).apply_move(
            "8365", "459", "73", "Мейнсофт",
        )

        second = service.reconcile_project_divergence()
        self.assertEqual(second["tasks"], 0,
                         "повторный прогон не должен делать работу заново")

    def test_failed_cards_are_not_mirrored(self):
        """Отражаем только то, что Битрикс принял."""
        client = FakeClient(fail_update_for=[2])

        ProjectMoveService(client, self.account, CONFIG).apply_move(
            "8365", "459", "73", "Мейнсофт",
        )

        self.assertEqual(
            TimesheetItem.objects.get(bitrix_id=1, bitrix24_account=self.account).project_id,
            "73",
        )
        self.assertEqual(
            TimesheetItem.objects.get(bitrix_id=2, bitrix24_account=self.account).project_id,
            "459",
            "непринятая карточка не должна меняться локально",
        )


class RewriteMirrorsEveryCopyOfCardTest(TestCase):
    """Копии карточки у ДРУГИХ аккаунтов портала тоже должны обновиться.

    Вторая серия того же дефекта, найдена на проде 31.08.2026 уже после первой
    правки. Одна карточка списания лежит в базе несколькими строками — по одной
    на аккаунт, которым её увидел синк (25 239 строк на 7 149 карточек, то есть
    3,5 копии в среднем, 31 аккаунт).

    Зеркало правило только копию текущего аккаунта, а выравнивание запускается
    от РАЗНЫХ аккаунтов: следующий прогон видел чужую, ещё не поправленную
    копию, считал задачу разошедшейся и переписывал те же карточки заново —
    снова с комментарием. На проде это дало новый комментарий каждые 10 минут
    на задачах 6823, 7507 и 7967.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-copy-1",
            is_master_account=True, domain_url="portal.bitrix24.ru",
            status="active", application_version=1,
        )
        # Тот же портал, другой сотрудник — своя копия той же карточки.
        self.neighbour = Bitrix24Account.objects.create(
            b24_user_id=22, is_b24_user_admin=False, member_id="m-copy-2",
            is_master_account=False, domain_url="portal.bitrix24.ru",
            status="active", application_version=1,
        )
        # Чужой портал: идентификаторы карточек уникальны только внутри
        # портала, поэтому его трогать нельзя ни при каких условиях.
        self.stranger = Bitrix24Account.objects.create(
            b24_user_id=33, is_b24_user_admin=False, member_id="m-copy-3",
            is_master_account=True, domain_url="other.bitrix24.ru",
            status="active", application_version=1,
        )
        for account in (self.account, self.neighbour, self.stranger):
            TimesheetItem.objects.create(
                bitrix24_account=account, bitrix_id=1, task_id="8365",
                employee_id="11", hours=1, project_id="459",
                project_title="Мероприятие", project_item_id="253",
                task_hierarchy_ids=["8365"], task_hierarchy_titles=["Задача"],
                date_reflection="2026-08-31T10:00:00+00:00",
            )

    def test_copy_of_another_account_is_mirrored_too(self):
        ProjectMoveService(FakeClient(), self.account, CONFIG).apply_move(
            "8365", "459", "73", "Мейнсофт",
        )

        self.assertEqual(
            TimesheetItem.objects.get(bitrix24_account=self.neighbour).project_id,
            "73",
            "чужая копия той же карточки оставила бы выравнивание в цикле",
        )

    def test_other_portal_is_never_touched(self):
        ProjectMoveService(FakeClient(), self.account, CONFIG).apply_move(
            "8365", "459", "73", "Мейнсофт",
        )

        self.assertEqual(
            TimesheetItem.objects.get(bitrix24_account=self.stranger).project_id,
            "459",
            "идентификатор карточки уникален только внутри портала",
        )
