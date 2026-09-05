"""Исправление находок проверки прямо с экрана закрытия месяца.

Проверка (period_check_service) намеренно ничего не чинит — она только
смотрит. Но человеку, увидевшему «7 задач переехали, карточки не переписаны»,
идти чинить это руками некуда: переписать карточку списания через интерфейс
Битрикса можно, но найти нужные семь задач среди тысяч записей нельзя.
Поэтому у находки появляется кнопка, а у кнопки — этот сервис.

ЧИНИМ НЕ ВСЁ, И ЭТО ОСОЗНАННО.

Машина имеет право поправить только то, где правильный ответ известен
однозначно и не требует решения человека:

  * diverged_project — проект в карточках разошёлся с текущей группой задачи.
    Верное значение известно: группа задачи. Ровно то же самое делает фоновое
    выравнивание, кнопка лишь не заставляет его ждать.
  * no_project — проект в карточке пуст. Если задача лежит в рабочей группе,
    верное значение снова известно. Если задача не в группе (личная задача,
    задача вне проектов) — неизвестно, и мы не выдумываем.

Остальные находки кнопки НЕ получают, и вот почему:

  * no_task — запись без задачи. Куда её отнести, знает только автор списания.
  * duplicates — какая из двух одинаковых строк лишняя, машина не знает; это
    к тому же удаление, то есть потеря часов при ошибке.
  * zero_hours, long_days, silent_employees — предупреждения. Они не про
    поломку данных, чинить там нечего.

Удаление записей этот сервис не делает ни при каких кодах. Всё, что он умеет,
сводится к записи проекта в карточку — операции обратимой и оставляющей след
в таймлайне.

ПРО ЗАКРЫТЫЙ ПЕРИОД. Переписывание карточек намеренно не трогает записи
закрытых месяцев (см. project_move_service). Значит вызов на закрытом периоде
не сделал бы НИЧЕГО и молча вернул бы «исправлено 0» — худший вид ответа.
Поэтому отказываем сразу и говорим прямо: сначала переоткройте месяц.
"""

import logging
from datetime import date
from typing import Any, Dict, List

from b24pysdk import Client

from .models import Bitrix24Account, PortalTask, TimesheetItem
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")

# Находки, у которых есть кнопка. Всё остальное чинится только человеком.
FIXABLE_CODES = ("diverged_project", "no_project")

# Сколько задач разбираем за одно нажатие.
#
# Потолок диктует не наша логика, а таймаут прокси хостинга (обычно 60 секунд)
# на пути к кнопке. Замер на проде 31.08.2026: пачка из 24 задач с
# переписыванием карточек и комментариями заняла 71 секунду, то есть около
# 3 секунд на задачу. Восемь задач укладываются примерно в 25 секунд — с
# запасом. Остаток не теряется: он остаётся в проверке, и кнопку можно нажать
# ещё раз.
MAX_TASKS_PER_FIX = 8


class PeriodFixService:
    """Чинит одну находку проверки за одно нажатие."""

    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account

    def fix(self, year: int, month: int, code: str) -> Dict[str, Any]:
        """Правит находку и возвращает СВЕЖУЮ проверку, а не свой прогноз.

        Сколько записей на самом деле поправилось, честно показывает только
        перечитанная проверка: часть карточек Битрикс может отвергнуть, часть
        задач окажется без группы. Поэтому не считаем ожидаемое, а
        пересчитываем фактическое.
        """
        from .period_check_service import PeriodCheckService
        from .period_service import PeriodService

        if code not in FIXABLE_CODES:
            return {
                "status": "not_fixable",
                "code": code,
                "error": self._why_not_fixable(code),
            }

        # Переоткрытый период сюда не попадёт: карта закрытых внутри
        # PeriodService строится с reopened_at__isnull=True.
        period = PeriodService(self.account).closed_period_for(date(year, month, 1))
        if period is not None:
            return {
                "status": "period_closed",
                "code": code,
                "error": (
                    "Период закрыт: записи заморожены. Чтобы исправить их, "
                    "сначала переоткройте месяц."
                ),
            }

        moves, unfixable = self._collect_moves(year, month, code)
        attempted = len(moves)

        if moves:
            self._apply(moves)
            audit.info(
                "Period fix %s %s-%s: %s tasks rewritten, %s without group (account %s)",
                code, year, month, attempted, unfixable, self.account.pk,
            )

        check = PeriodCheckService(self.account).run(year, month)
        return {
            "status": "done",
            "code": code,
            "attempted_tasks": attempted,
            "unfixable_tasks": unfixable,
            "check": check,
        }

    # ---------- Сбор ----------

    def _collect_moves(self, year: int, month: int, code: str):
        """Готовит список переносов и считает задачи, которые чинить нечем.

        Возвращает (moves, unfixable): unfixable — задачи, у которых в
        Битриксе нет рабочей группы. Для них верного проекта не существует, и
        это не сбой, а свойство задачи: личные задачи вне проектов бывают.
        """
        entries = TimesheetItem.objects.filter(
            **scope_to_tenant(self.account),
            date_reflection__year=year,
            date_reflection__month=month,
        ).exclude(task_id="")

        if code == "no_project":
            entries = entries.filter(project_id__in=["", None])

        pairs = list(entries.values_list("task_id", "project_id").distinct())
        if not pairs:
            return [], 0

        task_ids = sorted({str(task_id) for task_id, _ in pairs})
        groups = self._groups_for(task_ids, code)

        moves: List[Dict[str, Any]] = []
        seen = set()
        unfixable = 0
        for task_id, project_id in pairs:
            task_id = str(task_id)
            if task_id in seen:
                continue
            current = groups.get(task_id, "")
            if not current:
                # Задача не в рабочей группе — верного проекта не существует.
                unfixable += 1
                seen.add(task_id)
                continue
            if str(project_id or "") == current:
                continue
            seen.add(task_id)
            moves.append({
                "task_id": task_id,
                "old_group": str(project_id or ""),
                "new_group": current,
                "raw": {},
            })
            if len(moves) >= MAX_TASKS_PER_FIX:
                break
        return moves, unfixable

    def _groups_for(self, task_ids: List[str], code: str) -> Dict[str, str]:
        """Группы задач из справочника, при необходимости дотянув недостающие.

        Для no_project дотягивание существенно: запись без проекта чаще всего
        относится к задаче, которой в справочнике ещё нет (на проде 31.08.2026
        так было у шести задач из девяти). Без этого шага кнопка честно, но
        бесполезно ответила бы «чинить нечего».

        Дотягиваем только те задачи, что реально нужны этой находке, и только
        когда их немного: справочник синхронизируется пачками по 50, и тянуть
        сотни задач внутри нажатия кнопки нельзя.
        """
        known = dict(
            PortalTask.objects.filter(
                **scope_to_tenant(self.account), bitrix_id__in=task_ids
            ).values_list("bitrix_id", "group_id")
        )
        missing = [tid for tid in task_ids if tid not in known]
        if missing and code == "no_project":
            self._sync_missing(missing[: MAX_TASKS_PER_FIX * 2])
            known = dict(
                PortalTask.objects.filter(
                    **scope_to_tenant(self.account), bitrix_id__in=task_ids
                ).values_list("bitrix_id", "group_id")
            )
        return {str(k): str(v or "") for k, v in known.items()}

    def _sync_missing(self, task_ids: List[str]) -> None:
        """Подтягивает недостающие задачи в справочник.

        Сбой не критичен: без справочника кнопка просто не найдёт, что чинить,
        и скажет об этом — это лучше, чем уронить весь запрос.
        """
        from .task_sync_service import TaskSyncService

        try:
            TaskSyncService(self.client, self.account, interactive=True).sync_task_ids(task_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Task directory refresh before fix failed: %s", exc)

    # ---------- Применение ----------

    def _apply(self, moves: List[Dict[str, Any]]) -> None:
        from .task_sync_service import TaskSyncService

        # interactive=True — мы внутри запроса пользователя, а не в фоне:
        # берём небольшую порцию карточек на задачу, чтобы уложиться в таймаут
        # прокси. Остаток доберёт фоновое выравнивание или повторное нажатие.
        TaskSyncService(
            self.client, self.account, interactive=True
        ).rewrite_project_for_tasks(moves)

    # ---------- Тексты ----------

    @staticmethod
    def _why_not_fixable(code: str) -> str:
        """Почему у находки нет кнопки — словами, а не кодом ошибки.

        Человек нажал «Исправить» там, где кнопки быть не должно (или отправил
        запрос мимо интерфейса). Ответ «неизвестный код» ему ничего не даст,
        поэтому объясняем, что делать руками.
        """
        texts = {
            "no_task": (
                "Записи без задачи может привязать только автор списания: "
                "куда отнести час, знает он один."
            ),
            "duplicates": (
                "Дубли не удаляем автоматически: какая из одинаковых строк "
                "лишняя, видно только человеку, а ошибка означает потерю часов."
            ),
            "zero_hours": "Это предупреждение, а не поломка данных — чинить нечего.",
            "long_days": "Это предупреждение, а не поломка данных — чинить нечего.",
            "silent_employees": "Это предупреждение, а не поломка данных — чинить нечего.",
        }
        return texts.get(code, "Эта находка исправляется только вручную.")
