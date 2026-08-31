"""Перенос задачи -> проект переписывается в самих карточках списания.

Решение пользователя от 31.08.2026. До этого приложение подставляло актуальный
проект НА ЧТЕНИИ: снимок в карточке оставался старым, а отчёт показывал
текущий. Это чинило только наши отчёты — фильтры Битрикса, выгрузки, соседние
интеграции и человек, открывший карточку, продолжали видеть прежний проект.

Теперь правда пишется в источник: когда задача переехала в другую рабочую
группу, все её карточки списания обновляются, а в таймлайн каждой ложится
комментарий «было -> стало».

Про авторство. Синк работает без пользовательского контекста, под токеном
представителя портала, поэтому и правка, и комментарий будут от его имени.
Подменить автора в Битриксе нельзя (проверено шестью способами на
portal.tvermilk24.ru 28.08.2026: AUTHOR_ID в fields и верхним уровнем,
crm.timeline.comment.update, crm.activity.add, createdBy/updatedBy в
crm.item.update). Поэтому не боремся с платформой, а пишем правду В ТЕКСТ
комментария: кто на самом деле перенёс задачу, известно из самой задачи
(changedBy) и подставляется в текст.

Про закрытые периоды. Когда период закрыт правами Битрикса, обновление
карточки будет отвергнуто — и это правильное поведение, история заморожена.
Такие отказы НЕ глушатся: они собираются в результат и логируются, чтобы
расхождение между задачей и записями было видно сразу, а не обнаруживалось
через полгода.

Про объём. На проде в среднем 4 записи на задачу, то есть типовой перенос —
это единицы вызовов. Но есть хвост: у задачи 4627 их 260, и таких задач с
более чем 50 записями двадцать. Поэтому объём одного переноса ограничен
MAX_ITEMS_PER_MOVE: что не поместилось, остаётся на прежнем проекте и
попадает в отчёт о переносе, а не переписывается втихую наполовину.
"""

import logging
from typing import Any, Dict, List, Optional

from .models import Bitrix24Account, TimesheetItem
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")

# Потолки карточек на один перенос — РАЗНЫЕ для кнопки и фона, и это важно.
#
# У кнопки «Обновить» нет своего таймаута: браузер ждёт сколько угодно, сервер
# рвёт на 300 секундах, а между ними стоит прокси хостинга со своим лимитом
# (обычно 60 секунд). Сто обновлений плюс сто комментариев внутри одного
# запроса кнопки — это десятки секунд, то есть риск получить ошибку шлюза при
# том, что на сервере всё продолжит выполняться. Поэтому в интерактивном пути
# берём небольшую порцию, а остальное доделывает фон, где 300 секунд есть
# гарантированно.
MAX_ITEMS_PER_MOVE = 100
MAX_ITEMS_PER_MOVE_INTERACTIVE = 10


class ProjectMoveService:
    def __init__(self, client, account: Bitrix24Account, config: Dict[str, Any]):
        self.client = client
        self.account = account
        self.config = config or {}
        self.mapping = self.config.get("fields_mapping") or {}

    def _field(self, key: str) -> str:
        return str(self.mapping.get(key) or "").strip()

    def _entity_type_id(self) -> int:
        try:
            return int(self.config.get("sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            return 0

    def apply_move(
        self,
        task_id: str,
        old_group: str,
        new_group: str,
        new_group_name: str = "",
        moved_by_name: str = "",
        moved_at: str = "",
        max_items: int = MAX_ITEMS_PER_MOVE,
    ) -> Dict[str, Any]:
        """Переписывает проект во всех карточках задачи и комментирует каждую.

        Возвращает сводку с числом обновлённых и списком отказов — вызывающий
        обязан её залогировать, иначе смысл сбора отказов теряется.
        """
        entity_type_id = self._entity_type_id()
        field_project_id = self._field("project_id")
        if not entity_type_id or not field_project_id:
            # Без маппинга писать некуда. Не ошибка: портал может быть
            # настроен не полностью.
            return {"updated": 0, "failed": [], "skipped": "not_configured"}

        queryset = TimesheetItem.objects.filter(
            **scope_to_tenant(self.account), task_id=str(task_id)
        )
        # Закрытый период трогать нельзя: часы за него уже легли в счёт.
        # Отсекаем на НАШЕЙ стороне, а не упираемся в отказ прав Битрикса —
        # иначе каждый прогон выравнивания давал бы пачку бесполезных
        # обращений и мусор в логе. Задача при этом окажется «разорванной»:
        # свежие часы в новом проекте, закрытые остались в старом. Так и
        # должно быть — это зафиксированная история, а не ошибка.
        from .period_service import PeriodService

        periods = PeriodService(self.account)
        closed_ids = set()
        if periods.list_periods():
            for bid, dt in queryset.values_list("bitrix_id", "date_reflection"):
                if periods.is_closed(dt):
                    closed_ids.add(bid)
            if closed_ids:
                queryset = queryset.exclude(bitrix_id__in=closed_ids)
        # Точный COUNT, а не длина среза: в отчёте о переносе нужно ЧИСЛО
        # оставшихся записей, иначе «не поместилось» ни о чём не говорит.
        # Запрос дешёвый, task_id индексирован.
        total = queryset.count()
        if not total:
            return {"updated": 0, "failed": [], "total": 0}

        over_limit = max(0, total - max_items)
        items = list(
            queryset.values_list("bitrix_id", "project_title")[:max_items]
        )

        fields = {field_project_id: new_group}
        field_project_title = self._field("project_title")
        if field_project_title and new_group_name:
            fields[field_project_title] = new_group_name
        # project_item_id — снимок элемента СП СТАРОГО проекта. Оставить его
        # значило бы получить карточку, которая ссылается на группу одного
        # проекта и на элемент другого; чистим.
        field_project_item = self._field("project_item_id")
        if field_project_item:
            fields[field_project_item] = ""

        updated = 0
        failed: List[Dict[str, str]] = []

        for bitrix_id, old_title in items:
            try:
                self.client._bitrix_token.call_method(
                    "crm.item.update",
                    {"entityTypeId": entity_type_id, "id": int(bitrix_id), "fields": fields},
                )
            except Exception as exc:  # noqa: BLE001
                # Самый ожидаемый отказ — закрытый период: права Битрикса не
                # дадут тронуть старую карточку. Это не сбой, а сработавшая
                # защита, но знать о ней нужно.
                failed.append({"item": str(bitrix_id), "error": str(exc)[:200]})
                continue

            updated += 1
            # Передаём имя КАК ЕСТЬ: подставлять сюда new_group нельзя, иначе
            # фолбэк «группа N» внутри _comment никогда не сработает и в
            # истории окажется голый идентификатор без пояснения.
            self._comment(
                entity_type_id, bitrix_id, old_title, new_group_name,
                old_group, new_group, moved_by_name, moved_at,
            )

        summary = {
            "updated": updated,
            "failed": failed,
            "over_limit": over_limit,
            "skipped_closed": len(closed_ids),
        }
        audit.info(
            "Project rewrite for task %s: group %s -> %s, updated %s, failed %s, "
            "over limit %s, skipped in closed periods %s",
            task_id, old_group or "—", new_group or "—", updated, len(failed),
            over_limit, len(closed_ids),
        )
        if failed:
            logger.warning(
                "Project rewrite for task %s: %s cards not updated (first: %s)",
                task_id, len(failed), failed[0].get("error"),
            )
        return summary

    def _comment(
        self, entity_type_id: int, bitrix_id: Any, old_title: Optional[str],
        new_title: str, old_group: str, new_group: str,
        moved_by_name: str, moved_at: str,
    ) -> None:
        """Комментарий «было -> стало» в таймлайн карточки.

        Отдельно от обновления и с проглатыванием ошибки: комментарий —
        история, а не данные. Если он не встал, карточка всё равно уже
        переписана, и ронять из-за этого перенос неправильно.
        """
        was = (old_title or "").strip() or f"группа {old_group or '—'}"
        became = (new_title or "").strip() or f"группа {new_group or '—'}"
        text = f"Проект изменён автоматически: было «{was}», стало «{became}»."
        if moved_by_name:
            who = f" Задачу перенёс {moved_by_name}"
            text += who + (f" {moved_at}." if moved_at else ".")
        text += " Часы и дата списания не менялись."

        try:
            self.client._bitrix_token.call_method(
                "crm.timeline.comment.add",
                {
                    "fields": {
                        "ENTITY_ID": int(bitrix_id),
                        "ENTITY_TYPE_ID": entity_type_id,
                        "COMMENT": text,
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Timeline comment failed for item %s: %s", bitrix_id, exc)
