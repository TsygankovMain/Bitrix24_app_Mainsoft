"""Проверка перед закрытием месяца.

Вариант А из обсуждения 31.08.2026 — единственный дополнительный механизм,
который заказчик взял в первую версию. Смысл: закрыть месяц с мусором внутри
хуже, чем не закрыть. После закрытия это уже не поправить, а расхождение
всплывёт при сверке с клиентом.

РАЗДЕЛЕНИЕ НА БЛОКЕРЫ И ПРЕДУПРЕЖДЕНИЯ ПРИНЦИПИАЛЬНО.

  * блокер — данные СЛОМАНЫ: час либо потеряется, либо попадёт не туда;
  * предупреждение — данные НЕОБЫЧНЫ, но так бывает законно.

Смешивать нельзя. Если показывать всё одним списком и всё равно разрешать
закрытие, люди привыкнут нажимать «закрыть» не читая — и проверка перестанет
работать ровно в тот момент, когда действительно понадобится.

Проверка ничего не чинит и ничего не меняет. Она только смотрит.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

from django.db.models import Count, Sum

from .models import Bitrix24Account, PortalTask, PortalUser, TimesheetItem
from .period_service import MONTHS
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)

# Порог «подозрительно длинного дня». Не блокер: аврал и выезд — рабочая
# реальность, а не поломка данных.
LONG_DAY_HOURS = 12

BLOCKER = "blocker"
WARNING = "warning"


class PeriodCheckService:
    def __init__(self, account: Bitrix24Account):
        self.account = account

    def _entries(self, year: int, month: int):
        return TimesheetItem.objects.filter(
            **scope_to_tenant(self.account),
            date_reflection__year=year,
            date_reflection__month=month,
        )

    def run(self, year: int, month: int) -> Dict[str, Any]:
        entries = self._entries(year, month)

        blockers: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        # ---------- Блокеры ----------

        no_project = entries.filter(project_id__in=["", None]).count()
        if no_project:
            blockers.append({
                "code": "no_project",
                "title": f"{no_project} записей без проекта",
                "why": "Не попадут ни в один счёт — час просто потеряется",
                "count": no_project,
            })

        no_task = entries.filter(task_id__in=["", None]).count()
        if no_task:
            blockers.append({
                "code": "no_task",
                "title": f"{no_task} записей без привязки к задаче",
                "why": "Нельзя ни проверить, ни объяснить клиенту",
                "count": no_task,
            })

        diverged = self._diverged_tasks(entries)
        if diverged:
            blockers.append({
                "code": "diverged_project",
                "title": f"{len(diverged)} задач переехали, карточки не переписаны",
                "why": "Отчёт разойдётся с фактическим положением задач",
                "count": len(diverged),
            })

        # ---------- Предупреждения ----------

        zero_hours = entries.filter(hours=0).count()
        if zero_hours:
            warnings.append({
                "code": "zero_hours",
                "title": f"{zero_hours} записей с нулевыми часами",
                "why": "Мусор, но на сумму не влияет",
                "count": zero_hours,
            })

        silent = self._employees_without_entries(entries)
        if silent:
            warnings.append({
                "code": "silent_employees",
                "title": f"{len(silent)} сотрудников не списали ни часа",
                "why": "Бывает законно: отпуск, больничный",
                "count": len(silent),
            })

        long_days = self._long_days(entries)
        if long_days:
            warnings.append({
                "code": "long_days",
                "title": f"{len(long_days)} дней длиннее {LONG_DAY_HOURS} часов",
                "why": "Бывает законно: аврал, выезд",
                "count": len(long_days),
            })

        duplicates = self._duplicates(entries)
        if duplicates:
            warnings.append({
                "code": "duplicates",
                "title": f"{duplicates} возможных дублей",
                "why": "Бывает законно: два одинаковых куска работы",
                "count": duplicates,
            })

        return {
            "period": {"year": year, "month": month, "title": f"{MONTHS[month]} {year}"},
            "can_close": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "stats": self._stats(entries),
        }

    # ---------- Отдельные проверки ----------

    def _diverged_tasks(self, entries) -> List[str]:
        """Задачи, чей проект в записях разошёлся с текущей группой задачи.

        Именно то, что чинит фоновое выравнивание. Если на момент закрытия
        расхождение осталось — значит выравнивание до него не дошло, и
        замораживать такой месяц рано: отчёт зафиксирует проект, который уже
        неверен.
        """
        groups = dict(
            PortalTask.objects.filter(**scope_to_tenant(self.account))
            .exclude(group_id="")
            .values_list("bitrix_id", "group_id")
        )
        if not groups:
            return []

        diverged = set()
        rows = entries.exclude(task_id="").values_list("task_id", "project_id").distinct()
        for task_id, project_id in rows.iterator():
            current = groups.get(str(task_id))
            if current and str(project_id or "") != current:
                diverged.add(str(task_id))
        return sorted(diverged)

    def _employees_without_entries(self, entries) -> List[str]:
        """Активные сотрудники портала, не списавшие в этом месяце ничего.

        Считаем только по АКТИВНЫМ: уволенный, естественно, ничего не списал,
        и напоминать о нём каждый месяц незачем.
        """
        active = set(
            PortalUser.objects.filter(**scope_to_tenant(self.account), active=True)
            .values_list("bitrix_id", flat=True)
        )
        if not active:
            return []
        logged = set(str(e) for e in entries.values_list("employee_id", flat=True).distinct())
        return sorted(uid for uid in active if str(uid) not in logged)

    def _long_days(self, entries) -> List[Dict[str, Any]]:
        rows = (
            entries.values("employee_id", "date_reflection")
            .annotate(total=Sum("hours"))
            .filter(total__gt=LONG_DAY_HOURS)
        )
        return [
            {
                "employee_id": row["employee_id"],
                "date": row["date_reflection"].date().isoformat() if row["date_reflection"] else None,
                "hours": row["total"],
            }
            for row in rows
        ]

    def _duplicates(self, entries) -> int:
        """Записи, совпадающие по задаче, дате, сотруднику и часам.

        Возвращаем ЧИСЛО ЛИШНИХ записей, а не число групп: человеку важно,
        сколько строк потенциально задваивают сумму.
        """
        rows = (
            entries.exclude(task_id="")
            .values("task_id", "date_reflection", "employee_id", "hours")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        return sum(row["n"] - 1 for row in rows)

    def _stats(self, entries) -> Dict[str, Any]:
        agg = entries.aggregate(hours=Sum("hours"), entries=Count("id"))
        return {
            "hours": float(agg["hours"] or 0),
            "entries": agg["entries"] or 0,
            "projects": entries.exclude(project_id="").values("project_id").distinct().count(),
            "employees": entries.values("employee_id").distinct().count(),
        }

    # ---------- Детализация по находке ----------

    def details(self, year: int, month: int, code: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Список записей за находкой — для ссылки «Показать».

        Ограничен limit: экран со списком нужен, чтобы понять суть проблемы и
        пойти чинить, а не чтобы пролистать тысячу строк.
        """
        entries = self._entries(year, month)

        if code == "no_project":
            rows = entries.filter(project_id__in=["", None])
        elif code == "no_task":
            rows = entries.filter(task_id__in=["", None])
        elif code == "zero_hours":
            rows = entries.filter(hours=0)
        elif code == "diverged_project":
            rows = entries.filter(task_id__in=self._diverged_tasks(entries))
        elif code == "duplicates":
            keys = (
                entries.exclude(task_id="")
                .values("task_id", "date_reflection", "employee_id", "hours")
                .annotate(n=Count("id"))
                .filter(n__gt=1)
                .values_list("task_id", flat=True)
            )
            rows = entries.filter(task_id__in=list(keys))
        else:
            return []

        return [
            {
                "bitrix_id": row.bitrix_id,
                "task_id": row.task_id,
                "employee_id": row.employee_id,
                "hours": row.hours,
                "project_title": row.project_title,
                "date": row.date_reflection.date().isoformat() if row.date_reflection else None,
            }
            for row in rows.order_by("date_reflection", "bitrix_id")[:limit]
        ]

    def late_arrivals(self, period) -> List[Dict[str, Any]]:
        """Часы, созданные в Битриксе уже ПОСЛЕ закрытия периода.

        Их нельзя ни молча принять (цифры разойдутся с актом), ни молча
        выкинуть (человек потеряет работу). Показываем списком, решение
        принимает человек — переоткрыть период или перенести в текущий.
        """
        return [
            {
                "bitrix_id": row.bitrix_id,
                "task_id": row.task_id,
                "employee_id": row.employee_id,
                "hours": row.hours,
                "date": row.date_reflection.date().isoformat() if row.date_reflection else None,
                "created_at": row.source_created_at.isoformat() if row.source_created_at else None,
            }
            for row in self._entries(period.year, period.month)
            .filter(source_created_at__gt=period.closed_at)
            .order_by("source_created_at")[:200]
        ]
