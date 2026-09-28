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
import re
from datetime import date, timedelta
from typing import Any, Dict, Optional

from .configuration_service import ConfigurationService
from .employee_ids import normalize_employee_id
from .models import Bitrix24Account

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")

# Больше суток в сутках не бывает. Лимит снимается настройкой портала
# allow_over_24h_per_day — для тех, кто списывает задним числом одной записью
# за несколько дней.
DAILY_HOURS_LIMIT = 24.0


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

    def _reject_if_closed(self, fields: Dict[str, Any]) -> None:
        """Запрет записи в закрытый месяц.

        Одна проверка на все пять точек списания — ровно ради этого запись и
        переносили из браузера на бэкенд 31.08.2026. В браузере такое правило
        снималось бы правкой JS, здесь его не обойти.

        Дата берётся из присланных полей по маппингу портала. Если поля даты
        нет или она пустая — не блокируем: такую запись поймает проверка перед
        закрытием как блокер «запись без даты», и правильнее показать её там,
        чем молча отказать человеку в списании.
        """
        from .period_service import PeriodService

        date_value = self._field(fields, "data")
        if not date_value:
            return

        service = PeriodService(self.account)
        period = service.closed_period_for(date_value)
        if period is not None:
            raise TimesheetWriteError(service.refusal_message(period), status=409)

    def create(self, fields: Any) -> Dict[str, Any]:
        entity_type_id = self._entity_type_id()
        fields = self._validate_fields(fields)
        self._reject_if_closed(fields)
        self._reject_if_over_daily_limit(entity_type_id, fields)

        response = self.client._bitrix_token.call_method(
            "crm.item.add",
            {"entityTypeId": entity_type_id, "fields": fields},
        )
        item_id = self._extract_item_id(response)
        audit.info(
            "Timesheet entry created by account %s (b24 user %s): item %s, task %s, project %s",
            self.account.pk, self.account.b24_user_id, item_id,
            self._field(fields, "id_zadachi"), self._field(fields, "project_id"),
        )
        self._refresh_task_directory(fields)
        return {"status": "success", "id": item_id}

    def update(self, item_id: Any, fields: Any) -> Dict[str, Any]:
        entity_type_id = self._entity_type_id()
        fields = self._validate_fields(fields)
        self._reject_if_closed(fields)

        try:
            numeric_id = int(item_id)
        except (TypeError, ValueError):
            raise TimesheetWriteError("Некорректный идентификатор записи.")

        self._reject_if_over_daily_limit(entity_type_id, fields, item_id=numeric_id)

        self.client._bitrix_token.call_method(
            "crm.item.update",
            {"entityTypeId": entity_type_id, "id": numeric_id, "fields": fields},
        )
        audit.info(
            "Timesheet entry updated by account %s (b24 user %s): item %s, task %s, project %s",
            self.account.pk, self.account.b24_user_id, numeric_id,
            self._field(fields, "id_zadachi"), self._field(fields, "project_id"),
        )
        self._refresh_task_directory(fields)
        return {"status": "success", "id": numeric_id}

    def _reject_if_over_daily_limit(
        self, entity_type_id: int, fields: Dict[str, Any], item_id: Optional[int] = None,
    ) -> None:
        """Запрет списать сотруднику больше 24 часов за одни сутки.

        Считается СУММА записей сотрудника за дату, а не одна запись: раньше
        фронт не пускал только запись больше 24 часов, и три записи по 10 часов
        проходили. Сумму берём из Битрикса, а не из локальной копии: копия
        догоняет портал фоновым синком, и две записи подряд она бы не увидела.

        Правка, которая не добавляет часов сотруднику за день (уменьшение,
        разделение, смена описания), проходит всегда — иначе запись из дня,
        где лимит уже превышен старыми данными, нельзя было бы даже исправить.

        Поля часов, сотрудника или даты не сопоставлены — не проверяем:
        посчитать нечего, а отказ в списании хуже пропущенной проверки.
        """
        if ConfigurationService._normalize_bool(self.config.get("allow_over_24h_per_day")):
            return

        mapping = self.config.get("fields_mapping") or {}
        hours_code = mapping.get("kolichestvo_chasov")
        employee_code = mapping.get("sotrudnik")
        date_code = mapping.get("data")
        if not (hours_code and employee_code and date_code):
            return

        previous: Dict[str, Any] = {}
        if item_id is not None:
            previous = self._get_item(entity_type_id, item_id)

        hours = self._to_hours(fields.get(hours_code, previous.get(hours_code)))
        employee_id = normalize_employee_id(fields.get(employee_code, previous.get(employee_code)))
        day = self._to_day(fields.get(date_code, previous.get(date_code)))
        if not employee_id or day is None:
            return

        if previous:
            same_day = (
                normalize_employee_id(previous.get(employee_code)) == employee_id
                and self._to_day(previous.get(date_code)) == day
            )
            if same_day and hours <= self._to_hours(previous.get(hours_code)):
                return

        others = self._day_hours(entity_type_id, hours_code, employee_code, date_code,
                                 employee_id, day, exclude_id=item_id)
        total = others + hours
        if total <= DAILY_HOURS_LIMIT + 1e-9:
            return

        raise TimesheetWriteError(
            f"За {day.strftime('%d.%m.%Y')} у сотрудника уже списано {self._fmt(others)} ч, "
            f"с этой записью получится {self._fmt(total)} ч — больше 24 часов в сутки. "
            "Разрешить такое списание может администратор в настройках приложения.",
            status=409,
        )

    def _get_item(self, entity_type_id: int, item_id: int) -> Dict[str, Any]:
        response = self.client._bitrix_token.call_method(
            "crm.item.get", {"entityTypeId": entity_type_id, "id": item_id},
        )
        result = response.get("result") if isinstance(response, dict) else None
        item = result.get("item") if isinstance(result, dict) else None
        return item if isinstance(item, dict) else {}

    def _day_hours(
        self, entity_type_id: int, hours_code: str, employee_code: str, date_code: str,
        employee_id: str, day: date, exclude_id: Optional[int] = None,
    ) -> float:
        """Сумма часов сотрудника за день по данным Битрикса.

        Записей у одного человека за день единицы, но постраничность всё равно
        доводим до конца: лимит, посчитанный по первой полусотне, врал бы.
        """
        filter_: Dict[str, Any] = {
            employee_code: employee_id,
            f">={date_code}": day.isoformat(),
            f"<{date_code}": (day + timedelta(days=1)).isoformat(),
        }
        if exclude_id is not None:
            filter_["!id"] = exclude_id

        total = 0.0
        start = 0
        while True:
            response = self.client._bitrix_token.call_method("crm.item.list", {
                "entityTypeId": entity_type_id,
                "select": ["id", hours_code],
                "filter": filter_,
                "start": start,
            })
            result = response.get("result") if isinstance(response, dict) else None
            items = result.get("items") if isinstance(result, dict) else None
            for item in items or []:
                total += self._to_hours(item.get(hours_code))
            next_start = response.get("next") if isinstance(response, dict) else None
            if not items or not next_start:
                return total
            start = next_start

    @staticmethod
    def _to_hours(value: Any) -> float:
        try:
            return float(str(value).replace(",", ".")) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_day(value: Any) -> Optional[date]:
        """Календарный день записи — по той дате, что видит человек.

        Часовой пояс не пересчитываем: «2026-09-28T00:00:00+03:00» — это 28-е,
        хотя в UTC это ещё 27-е. Фронт шлёт «2026-09-28» или с T00:00:00,
        Битрикс отдаёт ISO со смещением портала, в старых записях встречается
        «28.09.2026».
        """
        raw = str(value or "").strip()
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
        if match:
            year, month, day = match.groups()
        else:
            match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", raw)
            if not match:
                return None
            day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    @staticmethod
    def _fmt(hours: float) -> str:
        return f"{round(hours, 2):g}".replace(".", ",")

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
