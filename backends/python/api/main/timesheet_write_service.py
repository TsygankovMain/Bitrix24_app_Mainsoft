"""Создание и правка карточек списания времени через наш бэкенд.

Зачем это здесь, а не во фронте. До этой правки часы писались из браузера
напрямую в Битрикс — `$b24.callMethod('crm.item.add', …)` в task.vue,
embedded.vue (создание и «разделение») и reports/project-report.client.vue.
Наш Django о таких записях не знал вовсе, поэтому серверной проверки на них
наложить было НЕЧЕГО: любое правило (в первую очередь закрытие месяца) жило бы
только в браузере и снималось бы правкой JS. Перенос сюда даёт единственное
место, где такие правила можно проверять по-настоящему.

Авторство при этом НЕ теряется, и это здесь главное. Bitrix24Account в этом
приложении — запись НА СОТРУДНИКА (unique_together по паре b24_user_id +
domain_url, у каждого свои OAuth-токены), а `account.client` ходит именно его
ключом. Значит вызов из бэкенда создаёт карточку от имени того же человека,
что нажал кнопку, и права Битрикса применяются к нему же.

Это принципиально отличается от схемы с общим вебхуком, где автор записи
всегда равен владельцу ключа и подменить его нельзя ничем (проверено на
portal.tvermilk24.ru 28.08.2026: AUTHOR_ID в fields, AUTHOR_ID верхним
уровнем, crm.timeline.comment.update, crm.activity.add, createdBy/updatedBy в
crm.item.update — все шесть способов игнорируются платформой). Если бы
приложение ходило вебхуком, перенос записи на бэкенд обезличил бы все
списания и сломал бы ровно тот механизм закрытия периодов правами, ради
которого всё затевается.

Что сервис делает сверх простого проксирования:

  * entityTypeId берётся из СЕРВЕРНОЙ конфигурации, а не из тела запроса.
    Раньше его присылал браузер, то есть клиент мог писать в любой
    смарт-процесс портала, куда у пользователя есть доступ.
  * поля пустого/некорректного типа отсекаются до вызова Битрикса, чтобы
    ошибка была понятной, а не «Bad Request» из SDK.

Сборка самих полей (контекст проекта, ИНН, снимок ставки, иерархия задач)
пока остаётся на фронте и приезжает готовым словарём. Это осознанный первый
шаг: он переносит ТОЧКУ КОНТРОЛЯ, не переписывая заодно всю логику обогащения,
которая завязана на данные, доступные только в контексте фрейма. Переносить её
следующими шагами можно по частям, не ломая работающее.
"""

import logging
from typing import Any, Dict, Optional

from .configuration_service import ConfigurationService
from .models import Bitrix24Account

logger = logging.getLogger(__name__)


class TimesheetWriteError(Exception):
    """Ошибка, которую нужно показать пользователю как есть."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class TimesheetWriteService:
    def __init__(self, account: Bitrix24Account, config: Optional[Dict[str, Any]] = None):
        self.account = account
        self.client = account.client
        self.config = config if config is not None else ConfigurationService(self.client, account).get_configuration_sync()

    def _entity_type_id(self) -> int:
        """ID смарт-процесса списаний — только из серверной конфигурации."""
        raw = self.config.get("sp_entity_type_id")
        try:
            entity_type_id = int(raw or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        if entity_type_id <= 0:
            raise TimesheetWriteError(
                "Смарт-процесс списаний не настроен. Откройте настройки приложения.",
                status=409,
            )
        return entity_type_id

    @staticmethod
    def _validate_fields(fields: Any) -> Dict[str, Any]:
        if not isinstance(fields, dict) or not fields:
            raise TimesheetWriteError("Не переданы поля записи.")
        return fields

    def create(self, fields: Any) -> Dict[str, Any]:
        entity_type_id = self._entity_type_id()
        fields = self._validate_fields(fields)

        response = self.client._bitrix_token.call_method(
            "crm.item.add",
            {"entityTypeId": entity_type_id, "fields": fields},
        )
        item_id = self._extract_item_id(response)
        logger.info(
            "Timesheet entry created by account %s (b24 user %s): item %s, task %s, project %s",
            self.account.pk, self.account.b24_user_id, item_id,
            self._field(fields, "id_zadachi"), self._field(fields, "project_id"),
        )
        self._refresh_task_directory(fields)
        return {"status": "success", "id": item_id}

    def update(self, item_id: Any, fields: Any) -> Dict[str, Any]:
        entity_type_id = self._entity_type_id()
        fields = self._validate_fields(fields)

        try:
            numeric_id = int(item_id)
        except (TypeError, ValueError):
            raise TimesheetWriteError("Некорректный идентификатор записи.")

        self.client._bitrix_token.call_method(
            "crm.item.update",
            {"entityTypeId": entity_type_id, "id": numeric_id, "fields": fields},
        )
        logger.info(
            "Timesheet entry updated by account %s (b24 user %s): item %s, task %s, project %s",
            self.account.pk, self.account.b24_user_id, numeric_id,
            self._field(fields, "id_zadachi"), self._field(fields, "project_id"),
        )
        self._refresh_task_directory(fields)
        return {"status": "success", "id": numeric_id}

    def _field(self, fields: Dict[str, Any], mapping_key: str) -> Any:
        """Значение поля по логическому ключу маппинга — только для логов."""
        code = (self.config.get("fields_mapping") or {}).get(mapping_key)
        return fields.get(code) if code else None

    def _refresh_task_directory(self, fields: Dict[str, Any]) -> None:
        """Дотягивает задачу записи в PortalTask сразу, не дожидаясь цикла.

        Без этого справочник узнаёт о задаче только следующим фоновым
        прогоном (раз в 10 минут), а до тех пор отчёт по свежей записи
        откатывается на снимок — то есть «следовать за задачей» не работает
        именно для того, что человек только что внёс, и выглядит как поломка.

        Ошибки проглатываются намеренно: справочник — вспомогательный слой,
        и его сбой не должен ронять уже состоявшуюся запись часов.
        """
        task_id = self._field(fields, "id_zadachi")
        if not task_id:
            return
        try:
            from .task_sync_service import TaskSyncService

            TaskSyncService(self.client, self.account).sync_task_ids([str(task_id)])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Task directory refresh failed for task %s: %s", task_id, exc)

    @staticmethod
    def _extract_item_id(response: Any) -> Optional[int]:
        """id созданной записи. crm.item.add отдаёт result.item.id, но
        встречается и плоский result.id — читаем оба (тот же приём, что во
        фронтовом extractCreatedItemId)."""
        if not isinstance(response, dict):
            return None
        result = response.get("result")
        if not isinstance(result, dict):
            return None
        item = result.get("item")
        raw_id = item.get("id") if isinstance(item, dict) else result.get("id")
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return None
