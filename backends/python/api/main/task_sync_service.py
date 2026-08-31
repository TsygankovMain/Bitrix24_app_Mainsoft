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
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Set

from b24pysdk import Client
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Bitrix24Account, PortalTask, TimesheetItem
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)
# События, которые обязаны быть видны в system_log, но ошибками не являются
# (порог общего db-обработчика — WARNING, см. settings.LOGGING).
audit = logging.getLogger("main.audit")

# Перекрытие для выборки изменённых задач: правка, случившаяся в ту же
# секунду, что и наша запись, иначе потерялась бы.
CHANGED_OVERLAP = timedelta(minutes=5)


def _clean_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text in {"0", "None", "null"}:
        return ""
    return text


class TaskSyncService:
    MAX_CHANGED_PAGES = 20  # страховка, если фильтр >CHANGED_DATE не применился
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

    def sync_task_ids(self, task_ids: List[str]) -> Dict[str, int]:
        """Точечное обновление справочника по конкретным задачам.

        Нужно, потому что полный прогон идёт по расписанию, а справочник
        строится из УЖЕ синхронизированных списаний. Задача, на которую часы
        списали только что, попадает в него лишь следующим циклом — и до тех
        пор отчёт по ней откатывается на снимок, то есть «следовать за
        задачей» не работает ровно для самых свежих записей. На проде
        31.08.2026 таких задач набралось семь за пятнадцать минут.

        Зовётся при записи часов через бэкенд: там id задачи известен, а
        стоимость — один crm-вызов на пачку до 50 задач.
        """
        cleaned = [_clean_id(t) for t in task_ids]
        cleaned = [t for t in cleaned if t]
        if not cleaned:
            return {"synced": 0, "created": 0, "updated": 0}
        return self._save_batch(self._fetch_tasks(sorted(set(cleaned))))

    def sync_missing_task_ids(self, limit: int = 200) -> Dict[str, int]:
        """Дотягивает задачи, которые есть в списаниях, но не в справочнике.

        Зовётся после синхронизации таймшитов — в том числе с кнопки
        «Обновить». Без этого кнопка обновляла только сами списания, а
        справочник ждал своего цикла: пользователь списывал часы, переносил
        задачу, жал «Обновить» и не видел никакой реакции, потому что задачи
        в справочнике ещё не было (боевая проверка 31.08.2026, задача 8365 —
        запись доехала на минуту позже прогона задач и разминулась с ним).

        Дёшево в типичном случае: если не хватает нечего, это один SELECT без
        единого обращения к Битриксу. limit ограничивает разовый объём, чтобы
        кнопка не превращалась в полный обход после долгого простоя —
        остальное доберёт фоновый цикл.
        """
        known = set(
            PortalTask.objects.filter(**scope_to_tenant(self.account)).values_list(
                "bitrix_id", flat=True
            )
        )
        missing = [tid for tid in self.collect_referenced_task_ids() if tid not in known]
        if not missing:
            return {"synced": 0, "created": 0, "updated": 0}

        if len(missing) > limit:
            logger.info(
                "Task directory: %s tasks missing, syncing first %s (rest on next cycle).",
                len(missing), limit,
            )
            missing = missing[:limit]
        return self.sync_task_ids(missing)

    def sync_changed_since(self, overlap: timedelta = CHANGED_OVERLAP) -> Dict[str, int]:
        """Дотягивает задачи, ИЗМЕНЁННЫЕ в Битриксе с момента последней записи.

        Закрывает дыру, которую sync_missing_task_ids не покрывает по своей
        природе: она тянет только ОТСУТСТВУЮЩИЕ задачи, а перенос касается
        задачи, которая в справочнике уже есть. Из-за этого кнопка «Обновить»
        не показывала реального положения: пользователь переносил задачу в
        другой проект, жал «Обновить» и не видел изменений, потому что перенос
        ждал десятиминутного фонового цикла (боевая проверка 31.08.2026,
        задача 8365 — перенесена в 14:51:52, справочник знал прежнюю группу
        ещё с 14:43:43).

        Полный обход ради кнопки не годится: 1 592 задачи это ~17 секунд.
        Поэтому спрашиваем у Битрикса только изменившиеся — фильтр
        >CHANGED_DATE. Обычно это единицы задач и один запрос, то есть
        стоимость кнопки почти не меняется, а перенос виден сразу.

        Маркер — максимальный updated_at справочника: время, когда мы в
        последний раз что-то записали. Из него вычитается перекрытие, чтобы не
        потерять правку, случившуюся в ту же секунду. Пустой справочник ->
        выходим: наполнять его целиком должен фоновый прогон, а не кнопка.
        """
        marker = (
            PortalTask.objects.filter(**scope_to_tenant(self.account))
            .aggregate(last=Max("updated_at"))
            .get("last")
        )
        if marker is None:
            return {"synced": 0, "created": 0, "updated": 0}

        since = marker - overlap
        raw_tasks = self._fetch_changed_tasks(since)
        if not raw_tasks:
            return {"synced": 0, "created": 0, "updated": 0}
        return self._save_batch(raw_tasks)

    def _apply_project_moves(self, moves: List[Dict[str, Any]]) -> None:
        """Переписывает проект в карточках списаний переехавших задач.

        Изолировано от синка справочника: справочник уже сохранён, и если
        переписывание карточек упадёт (закрытый период, отказ Битрикса,
        отсутствие маппинга), актуальные группы задач всё равно останутся в
        базе — отчёт подставит верный проект на чтении, как и раньше.

        Имя новой группы и того, кто перенёс задачу, берём из сырого ответа
        tasks.task.list: он отдаёт вложенный объект group и changedBy, а
        значит второй запрос ради текста комментария не нужен.
        """
        try:
            from .configuration_service import ConfigurationService
            from .project_move_service import ProjectMoveService

            config = ConfigurationService(self.client, self.account).get_configuration_sync()
            mover = ProjectMoveService(self.client, self.account, config)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project rewrite skipped (setup failed): %s", exc)
            return

        # Имена групп резолвим один раз на все переносы: в списочном ответе
        # tasks.task.list вложенного объекта group нет, только GROUP_ID.
        # Берём ИМЯ ГРУППЫ БИТРИКСА, а не название карточки проекта: карточек
        # на одну группу бывает несколько (на проде 21 такая группа, у одной
        # их три), и подставлять произвольную в комментарий «стало» нельзя.
        group_names = self._resolve_group_names(
            {m["new_group"] for m in moves if m.get("new_group")}
        )

        for move in moves:
            raw = move.get("raw") or {}
            try:
                mover.apply_move(
                    task_id=move["task_id"],
                    old_group=move["old_group"],
                    new_group=move["new_group"],
                    new_group_name=group_names.get(move["new_group"], ""),
                    moved_by_name=self._resolve_user_name(raw.get("changedBy") or raw.get("CHANGED_BY")),
                    moved_at=str(raw.get("changedDate") or raw.get("CHANGED_DATE") or "")[:19].replace("T", " "),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Project rewrite failed for task %s: %s", move.get("task_id"), exc,
                )

    def _resolve_group_names(self, group_ids: Set[str]) -> Dict[str, str]:
        """Названия рабочих групп Битрикса по их id, одним запросом.

        Нужны для текста комментария «стало «Мейнсофт»». Именно имя ГРУППЫ, а
        не карточки проекта: карточек на одну группу бывает несколько, и
        подставлять произвольную в историю нельзя.

        Сбой не критичен: без имени комментарий скажет «группа 73» — хуже
        читается, но не врёт.
        """
        ids = sorted(gid for gid in group_ids if gid)
        if not ids:
            return {}
        try:
            response = self.client._bitrix_token.call_method(
                "sonet_group.get",
                {"FILTER": {"ID": ids}, "SELECT": ["ID", "NAME"]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Group names lookup failed: %s", exc)
            return {}

        rows = response.get("result") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            return {}
        names: Dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            gid = _clean_id(row.get("ID") or row.get("id"))
            name = str(row.get("NAME") or row.get("name") or "").strip()
            if gid and name:
                names[gid] = name
        return names

    def _resolve_user_name(self, user_id: Any) -> str:
        """Имя сотрудника для текста комментария — из локального справочника.

        Специально без обращения к Битриксу: комментарий это оформление, и
        платить за него лишним запросом на каждую переехавшую задачу незачем.
        Нет в справочнике — пишем идентификатор, это лучше пустоты.
        """
        uid = _clean_id(user_id)
        if not uid:
            return ""
        try:
            from .models import PortalUser

            row = PortalUser.objects.filter(
                **scope_to_tenant(self.account), bitrix_id=uid
            ).values_list("name", "last_name").first()
        except Exception:  # noqa: BLE001
            return f"пользователь {uid}"
        if not row:
            return f"пользователь {uid}"
        full = " ".join(part for part in row if part).strip()
        return full or f"пользователь {uid}"

    def _fetch_changed_tasks(self, since) -> List[Dict[str, Any]]:
        """tasks.task.list с фильтром по дате изменения, постранично.

        Пагинация через start, а не keyset: выборка мала по определению
        (изменения за минуты), а MAX_CHANGED_PAGES страхует от вырожденного
        случая, когда фильтр вдруг не применился и Битрикс отдаёт всё подряд.
        """
        collected: List[Dict[str, Any]] = []
        start = 0
        for page in range(self.MAX_CHANGED_PAGES):
            try:
                response = self.client._bitrix_token.call_method(
                    "tasks.task.list",
                    {
                        "filter": {">CHANGED_DATE": since.isoformat()},
                        "select": ["ID", "TITLE", "GROUP_ID", "CHANGED_BY", "CHANGED_DATE"],
                        "start": start,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Task sync: changed-since fetch failed for account %s: %s",
                    self.account.pk, exc,
                )
                break

            tasks = self._extract_tasks(response)
            if not tasks:
                break
            collected.extend(tasks)

            next_value = response.get("next") if isinstance(response, dict) else None
            if next_value in (None, "", False):
                break
            try:
                next_start = int(next_value)
            except (TypeError, ValueError):
                break
            if next_start <= start:
                break
            start = next_start
        else:
            logger.warning(
                "Task sync: changed-since hit page cap (%s) for account %s; "
                "filter may not have applied.",
                self.MAX_CHANGED_PAGES, self.account.pk,
            )

        return collected

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
                        "select": ["ID", "TITLE", "GROUP_ID", "CHANGED_BY", "CHANGED_DATE"],
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
        # Сырые ответы Битрикса по id: из них берём имя группы и того, кто
        # перенёс задачу, для текста комментария «было -> стало».
        raw_by_id = {_clean_id(t.get("id") or t.get("ID")): t for t in raw_tasks}
        moves: List[Dict[str, Any]] = []
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
                previous = getattr(existing_row, field_name)
                if previous != field_value:
                    # Перенос задачи в другой проект — ключевое событие для
                    # отчётов: именно из-за него часы меняют проект. Логируем
                    # отдельно и явно, иначе «почему цифры поехали» приходится
                    # выяснять сопоставлением выгрузок.
                    if field_name == "group_id":
                        audit.info(
                            "Task %s moved: group %s -> %s (account %s)",
                            bitrix_id, previous or "—", field_value or "—", self.account.pk,
                        )
                        # Проект переписывается в САМИХ карточках списания, а
                        # не только подставляется в отчёте: иначе фильтры
                        # Битрикса, выгрузки и человек, открывший карточку,
                        # продолжали бы видеть прежний проект. Собираем здесь,
                        # применяем после сохранения справочника — до тех пор
                        # старое значение ещё нужно как «было».
                        moves.append({
                            "task_id": bitrix_id,
                            "old_group": previous or "",
                            "new_group": field_value or "",
                            "raw": raw_by_id.get(bitrix_id, {}),
                        })
                    elif field_name == "title":
                        audit.info(
                            "Task %s renamed: %r -> %r (account %s)",
                            bitrix_id, previous, field_value, self.account.pk,
                        )
                    setattr(existing_row, field_name, field_value)
                    has_changes = True
            if has_changes:
                existing_row.updated_at = now
                to_update.append(existing_row)

        if to_create:
            PortalTask.objects.bulk_create(to_create, batch_size=self.BULK_BATCH_SIZE)
        if to_update:
            PortalTask.objects.bulk_update(to_update, self.UPSERT_FIELDS, batch_size=self.BULK_BATCH_SIZE)

        if moves:
            self._apply_project_moves(moves)

        return {"synced": len(prepared), "created": len(to_create), "updated": len(to_update)}
