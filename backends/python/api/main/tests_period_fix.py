"""Исправление находок проверки прямо с экрана закрытия месяца.

Запрос пользователя от 31.08.2026: «я бы хотел чтобы была возможность сразу
делать исправления по замечаниям».

Главное, что закрепляют эти тесты, — ГРАНИЦА автоматического исправления.
Машина правит только то, где верный ответ известен однозначно (проект берётся
из рабочей группы задачи). Всё, что требует решения человека — запись без
задачи, выбор лишней строки из пары дублей, — кнопки не получает и получить
не должно: ошибка там означает потерянные часы.
"""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, ClosedPeriod, PortalTask, TimesheetItem
from .period_fix_service import MAX_TASKS_PER_FIX, PeriodFixService


class PeriodFixServiceTest(TestCase):
    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-fix",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    # ---------- Данные ----------

    def _entry(self, bitrix_id, task_id="8365", project_id="459",
               date="2026-08-10T10:00:00+00:00"):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=1, project_id=project_id,
            project_title="Проект", task_hierarchy_ids=[task_id],
            task_hierarchy_titles=["Задача"], date_reflection=date,
        )

    def _task(self, bitrix_id, group_id):
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id,
            title="Задача", group_id=group_id,
        )

    def _service(self):
        """Сервис с подменённым применением: проверяем ЧТО решено чинить.

        Само переписывание карточек покрыто tests_project_move — дублировать
        его здесь незачем, а вот список собранных переносов это и есть предмет
        проверки.
        """
        service = PeriodFixService(client=None, account=self.account)
        service.applied = []
        service._apply = lambda moves: service.applied.extend(moves)
        return service

    # ---------- Расхождение проекта ----------

    def test_diverged_task_is_rewritten_to_current_group(self):
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["attempted_tasks"], 1)
        self.assertEqual(service.applied[0]["old_group"], "459")
        self.assertEqual(service.applied[0]["new_group"], "73")

    def test_matching_task_is_left_alone(self):
        self._entry(1, task_id="8365", project_id="73")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["attempted_tasks"], 0)
        self.assertEqual(service.applied, [])

    def test_other_months_are_not_touched(self):
        """Чиним ТОЛЬКО выбранный период.

        Иначе кнопка на августе молча переписывала бы карточки за май, и
        человек не понимал бы, откуда в закрытом месяце новые комментарии.
        """
        self._entry(1, task_id="8365", project_id="459", date="2026-07-10T10:00:00+00:00")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["attempted_tasks"], 0)

    def test_task_without_group_counts_as_unfixable(self):
        """Задача вне рабочей группы — верного проекта не существует.

        Это не сбой и не повод молчать: человек должен видеть, что часть
        находки кнопкой не лечится, иначе он будет жать её до бесконечности.
        """
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["attempted_tasks"], 0)
        self.assertEqual(result["unfixable_tasks"], 1)

    def test_batch_is_capped(self):
        """Порция ограничена: за кнопкой стоит таймаут прокси, а не наша воля."""
        for i in range(MAX_TASKS_PER_FIX + 4):
            task_id = f"90{i:02d}"
            self._entry(i + 1, task_id=task_id, project_id="459")
            self._task(task_id, "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["attempted_tasks"], MAX_TASKS_PER_FIX)

    # ---------- Записи без проекта ----------

    def test_empty_project_is_filled_from_task_group(self):
        self._entry(1, task_id="8365", project_id="")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "no_project")

        self.assertEqual(result["attempted_tasks"], 1)
        self.assertEqual(service.applied[0]["new_group"], "73")

    def test_missing_task_is_pulled_into_directory_first(self):
        """Задачи может не быть в справочнике — тогда сперва тянем её.

        На проде 31.08.2026 так было у шести задач из девяти: без этого шага
        кнопка честно, но бесполезно отвечала бы «чинить нечего».
        """
        self._entry(1, task_id="8365", project_id="")
        service = self._service()

        def pull(task_ids):
            self._task("8365", "73")

        service._sync_missing = pull
        result = service.fix(2026, 8, "no_project")

        self.assertEqual(result["attempted_tasks"], 1)
        self.assertEqual(service.applied[0]["new_group"], "73")

    def test_entries_with_project_are_not_touched_by_no_project(self):
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "no_project")

        self.assertEqual(result["attempted_tasks"], 0)

    # ---------- Границы ----------

    def test_closed_period_is_refused_instead_of_doing_nothing(self):
        """Отказ вслух, а не тихое «исправлено 0».

        Переписывание намеренно не трогает записи закрытых месяцев, поэтому на
        закрытом периоде кнопка не сделала бы НИЧЕГО и отчиталась бы успехом —
        худший из возможных ответов.
        """
        ClosedPeriod.objects.create(
            bitrix24_account=self.account, year=2026, month=8, stats={},
            closed_at=timezone.now(), closed_by="11", closed_by_name="Егор",
        )
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["status"], "period_closed")
        self.assertEqual(service.applied, [])

    def test_reopened_period_is_fixable_again(self):
        ClosedPeriod.objects.create(
            bitrix24_account=self.account, year=2026, month=8, stats={},
            closed_at=timezone.now(), closed_by="11", closed_by_name="Егор",
            reopened_at=timezone.now(), reopen_reason="правка",
        )
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["attempted_tasks"], 1)

    def test_entries_without_task_are_never_fixed_automatically(self):
        """Куда отнести час, знает только автор списания."""
        service = self._service()

        result = service.fix(2026, 8, "no_task")

        self.assertEqual(result["status"], "not_fixable")
        self.assertIn("автор списания", result["error"])
        self.assertEqual(service.applied, [])

    def test_duplicates_are_never_deleted_automatically(self):
        """Удаление лишней строки из пары дублей — потеря часов при ошибке."""
        service = self._service()

        result = service.fix(2026, 8, "duplicates")

        self.assertEqual(result["status"], "not_fixable")
        self.assertEqual(service.applied, [])

    def test_warnings_have_no_button(self):
        for code in ("zero_hours", "long_days", "silent_employees"):
            with self.subTest(code=code):
                result = self._service().fix(2026, 8, code)
                self.assertEqual(result["status"], "not_fixable")

    def test_result_carries_fresh_check(self):
        """Ответ содержит перечитанную проверку, а не наш прогноз.

        Сколько на самом деле поправилось, видно только по свежей проверке:
        часть карточек Битрикс может отвергнуть.
        """
        self._entry(1, task_id="8365", project_id="459")
        self._task("8365", "73")
        service = self._service()

        result = service.fix(2026, 8, "diverged_project")

        self.assertIn("check", result)
        self.assertIn("blockers", result["check"])
        self.assertEqual(result["check"]["period"]["year"], 2026)


class PeriodFixRewritesRealCardsTest(TestCase):
    """Сквозная проверка: сервис действительно доходит до переписывания.

    Остальные тесты подменяют _apply, чтобы смотреть на решение. Здесь
    убеждаемся, что настоящий путь ведёт в TaskSyncService, — иначе подмена
    проверяла бы фикцию.
    """

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-fix-real",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )
        TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=1, task_id="8365",
            employee_id="11", hours=1, project_id="459", project_title="Проект",
            task_hierarchy_ids=["8365"], task_hierarchy_titles=["Задача"],
            date_reflection="2026-08-10T10:00:00+00:00",
        )
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="8365",
            title="Задача", group_id="73",
        )

    def test_moves_reach_task_sync_service(self):
        with patch(
            "main.task_sync_service.TaskSyncService.rewrite_project_for_tasks"
        ) as rewrite:
            result = PeriodFixService(client=None, account=self.account).fix(
                2026, 8, "diverged_project",
            )

        self.assertEqual(result["status"], "done")
        rewrite.assert_called_once()
        moves = rewrite.call_args[0][0]
        self.assertEqual(moves[0]["task_id"], "8365")
        self.assertEqual(moves[0]["new_group"], "73")
