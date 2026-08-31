"""Синк справочника задач Bitrix24 -> PortalTask: актуальные название и группа.

Устройство повторяет UserSyncService (см. его докстринг): полный upsert без
инкремента и без удаления осиротевших записей — задача, пропавшая из ответа
Битрикса, сохраняет последнее известное состояние.

Отличие одно и существенное: пользователей на портале десятки-сотни, и их
можно тянуть целиком, а задач на боевом портале десятки тысяч. Поэтому здесь
выборка ПО СПИСКУ ID — только те задачи, что реально встречаются в списаниях
(TimesheetItem.task_id и цепочки task_hierarchy_ids). На проде это 1 582
задачи против всего портала, то есть 32 страницы по 50 вместо неизвестно
скольких. Задача, появившаяся в списаниях только что, попадёт в справочник
следующим прогоном, а до тех пор отчёт покажет снимок с карточки — деградация
мягкая и не заметная глазу.

Метод — tasks.task.list с фильтром по ID и select [ID, TITLE, GROUP_ID].
GROUP_ID это рабочая группа Битрикса, она же project_id в наших карточках
проектов и в timesheet_item (сверено на проде: 25 = ИТ-ЛАБ, 415 = ПВД
сопровождение, 425 = ВСС).

Ответ tasks.task.* приходит в camelCase (result.tasks[].id/title/groupId), но
Битрикс исторически неоднороден, поэтому ключи читаются в обоих написаниях —
тем же приёмом, что в project_board_service._fetch_companies_live.
"""

import logging
from typing import Any, Dict, Iterable, List, Set

from b24pysdk import Client
from django.db import transaction
from django.utils import timezone

from .models import Bitrix24Account, PortalTask, TimesheetItem
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)


def _clean_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text in {"0", "None", "null"}:
        return ""
    return text


class TaskSyncService:
    CHUNK_SIZE = 50      # столько ID уходит в один tasks.task.list
    MAX_CHUNKS = 400     # предохранитель фонового джоба: 400*50 = 20 000 задач
    BULK_BATCH_SIZE = 200
    UPSERT_FIELDS = ["title", "group_id", "updated_at"]

    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account

    def sync(self) -> Dict[str, int]:
        task_ids = self.collect_referenced_task_ids()
        if not task_ids:
            return {"synced": 0, "created": 0, "updated": 0}
        raw_tasks = self._fetch_tasks(task_ids)
        return self._save_batch(raw_tasks)

    def collect_referenced_task_ids(self) -> List[str]:
        """ID задач, встречающихся в списаниях: и сама задача, и вся её цепочка.

        Иерархия нужна потому, что отчёт строит дерево по task_hierarchy_ids —
        значит актуальное название требуется и для промежуточных узлов, а не
        только для листа.
        """
        ids: Set[str] = set()
        rows = TimesheetItem.objects.filter(**scope_to_tenant(self.account)).values(
            "task_id", "task_hierarchy_ids"
        )
        for row in rows.iterator():
            task_id = _clean_id(row.get("task_id"))
            if task_id:
                ids.add(task_id)
            for chain_id in row.get("task_hierarchy_ids") or []:
                chain_id = _clean_id(chain_id)
                if chain_id:
                    ids.add(chain_id)
        return sorted(ids)

    def _fetch_tasks(self, task_ids: List[str]) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        for chunk_index, chunk in enumerate(self._chunks(task_ids)):
            if chunk_index >= self.MAX_CHUNKS:
                logger.warning(
                    "Task sync: hit MAX_CHUNKS (%s) for account %s; %s ids left unfetched.",
                    self.MAX_CHUNKS, self.account.pk, len(task_ids) - chunk_index * self.CHUNK_SIZE,
                )
                break
            try:
                response = self.client._bitrix_token.call_method(
                    "tasks.task.list",
                    {
                        "filter": {"ID": chunk},
                        "select": ["ID", "TITLE", "GROUP_ID"],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                # Сбой одной пачки не должен ронять весь прогон: остальные
                # задачи всё равно обновятся, а эта пачка подтянется следующим.
                logger.warning("Task sync: chunk fetch failed for account %s: %s", self.account.pk, exc)
                continue
            collected.extend(self._extract_tasks(response))
        return collected

    def _chunks(self, values: List[str]) -> Iterable[List[str]]:
        for start in range(0, len(values), self.CHUNK_SIZE):
            yield values[start:start + self.CHUNK_SIZE]

    @staticmethod
    def _extract_tasks(response: Any) -> List[Dict[str, Any]]:
        if not isinstance(response, dict):
            return []
        result = response.get("result")
        if isinstance(result, dict):
            tasks = result.get("tasks")
            if isinstance(tasks, list):
                return tasks
            return []
        if isinstance(result, list):
            return result
        return []

    @transaction.atomic
    def _save_batch(self, raw_tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        prepared: List[tuple] = []
        seen: Set[str] = set()
        for task in raw_tasks:
            bitrix_id = _clean_id(task.get("id") or task.get("ID"))
            if not bitrix_id or bitrix_id in seen:
                continue
            seen.add(bitrix_id)
            title = task.get("title") or task.get("TITLE") or ""
            group_id = _clean_id(task.get("groupId") or task.get("GROUP_ID"))
            prepared.append((bitrix_id, {"title": str(title)[:500], "group_id": group_id}))

        if not prepared:
            return {"synced": 0, "created": 0, "updated": 0}

        now = timezone.now()
        existing = {
            row.bitrix_id: row
            for row in PortalTask.objects.filter(
                **scope_to_tenant(self.account),
                bitrix_id__in=[bid for bid, _ in prepared],
            )
        }

        to_create: List[PortalTask] = []
        to_update: List[PortalTask] = []

        for bitrix_id, defaults in prepared:
            existing_row = existing.get(bitrix_id)
            if existing_row is None:
                to_create.append(
                    PortalTask(
                        **scope_to_tenant(self.account, write=True),
                        bitrix_id=bitrix_id,
                        created_at=now,
                        updated_at=now,
                        **defaults,
                    )
                )
                continue

            has_changes = False
            for field_name, field_value in defaults.items():
                if getattr(existing_row, field_name) != field_value:
                    setattr(existing_row, field_name, field_value)
                    has_changes = True
            if has_changes:
                existing_row.updated_at = now
                to_update.append(existing_row)

        if to_create:
            PortalTask.objects.bulk_create(to_create, batch_size=self.BULK_BATCH_SIZE)
        if to_update:
            PortalTask.objects.bulk_update(to_update, self.UPSERT_FIELDS, batch_size=self.BULK_BATCH_SIZE)

        return {"synced": len(prepared), "created": len(to_create), "updated": len(to_update)}
