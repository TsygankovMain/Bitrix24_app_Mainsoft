"""Закрытие месяца: единственное место, где решается, закрыт ли период.

Все проверки закрытости идут через is_closed/closed_period_for — и запись
часов, и переписывание проекта при переносе задачи, и фоновое выравнивание,
и резолв проекта на чтении. Разводить эту логику по местам нельзя: разойдётся
при первом же переоткрытии.

Про часовой пояс — проверено на данных, а не на предположении.
date_reflection хранит КАЛЕНДАРНУЮ ДАТУ списания, а не момент: на проде
31.08.2026 из ~7 100 записей 6 651 имеет время ровно 00:00, остальные — редкие
исключения с реальным временем. То есть дату выбирают в календаре, а время
в неё не вкладывают.

Поэтому месяц берётся прямо из даты через timezone.localtime (TIME_ZONE в
проекте — UTC, см. settings): для записи, лежащей на полуночи, это даёт ровно
тот день, который человек выбрал, и смена TIME_ZONE на московскую ничего не
изменит — полночь UTC остаётся тем же числом и в MSK.

Расхождение возможно только у тех редких записей, где время всё-таки
проставлено, и только если оно попадает в трёхчасовое окно на границе месяца.
Известное ограничение; чинить его имеет смысл, только если такие записи
появятся массово.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.utils import timezone

from .models import Bitrix24Account, ClosedPeriod
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)
audit = logging.getLogger("main.audit")


def period_of(value: Any) -> Optional[tuple]:
    """(год, месяц) для даты списания, по местному времени портала.

    None для пустого значения: запись без даты закрытым периодом не
    ограничивается — её отловит проверка перед закрытием как блокер.
    """
    if not value:
        return None
    if isinstance(value, str):
        parsed = timezone.datetime.fromisoformat(value.replace("Z", "+00:00")) \
            if "T" in value or "-" in value else None
        if parsed is None:
            return None
        value = parsed
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return (value.year, value.month)
    # date без времени
    return (value.year, value.month)


class PeriodService:
    def __init__(self, account: Bitrix24Account):
        self.account = account
        self._cache: Optional[Dict[tuple, ClosedPeriod]] = None

    def _closed_map(self) -> Dict[tuple, ClosedPeriod]:
        """Карта закрытых периодов. Кэшируется на время жизни сервиса:
        при выравнивании расхождений проверка идёт по сотням записей."""
        if self._cache is None:
            self._cache = {
                (row.year, row.month): row
                for row in ClosedPeriod.objects.filter(
                    **scope_to_tenant(self.account), reopened_at__isnull=True
                )
            }
        return self._cache

    def closed_period_for(self, value: Any) -> Optional[ClosedPeriod]:
        """Закрытый период, которому принадлежит дата. None — период открыт."""
        key = period_of(value)
        if key is None:
            return None
        return self._closed_map().get(key)

    def is_closed(self, value: Any) -> bool:
        return self.closed_period_for(value) is not None

    def refusal_message(self, period: ClosedPeriod) -> str:
        """Текст отказа для пользователя.

        Называет конкретный период и дату закрытия, а не «операция
        запрещена»: человек должен понимать, что именно произошло и к кому
        идти.
        """
        closed_at = timezone.localtime(period.closed_at).strftime("%d.%m.%Y")
        return (
            f"{MONTHS[period.month]} {period.year} закрыт {closed_at}. "
            "Списать часы за этот период нельзя — обратитесь к администратору."
        )

    # ---------- Закрытие и переоткрытие ----------

    def close(self, year: int, month: int, stats: Dict[str, Any],
              by_id: str = "", by_name: str = "") -> ClosedPeriod:
        """Закрывает период. Идемпотентно: повторный вызов вернёт существующий.

        Переоткрытый период закрывается заново — поля переоткрытия при этом
        чистятся, а сам факт остаётся в логе аудита. Хранить всю цепочку
        закрытий-переоткрытий в этой таблице не нужно: это журнал событий, а
        для него есть system_log.
        """
        period, created = ClosedPeriod.objects.update_or_create(
            **scope_to_tenant(self.account, write=True),
            year=year, month=month,
            defaults={
                "closed_at": timezone.now(),
                "closed_by": str(by_id or ""),
                "closed_by_name": by_name or "",
                "stats": stats or {},
                "reopened_at": None,
                "reopened_by": "",
                "reopened_by_name": "",
                "reopen_reason": "",
            },
        )
        self._cache = None
        audit.info(
            "Period closed: %s-%02d by %s (%s), %s hours in %s entries",
            year, month, by_name or "—", by_id or "—",
            (stats or {}).get("hours", "—"), (stats or {}).get("entries", "—"),
        )
        return period

    def reopen(self, year: int, month: int, reason: str,
               by_id: str = "", by_name: str = "") -> Optional[ClosedPeriod]:
        """Переоткрывает период. Причина обязательна — см. докстринг модели."""
        period = ClosedPeriod.objects.filter(
            **scope_to_tenant(self.account), year=year, month=month,
            reopened_at__isnull=True,
        ).first()
        if period is None:
            return None

        period.reopened_at = timezone.now()
        period.reopened_by = str(by_id or "")
        period.reopened_by_name = by_name or ""
        period.reopen_reason = reason
        period.save(update_fields=[
            "reopened_at", "reopened_by", "reopened_by_name", "reopen_reason", "updated_at",
        ])
        self._cache = None
        audit.info(
            "Period reopened: %s-%02d by %s (%s), reason: %s",
            year, month, by_name or "—", by_id or "—", reason,
        )
        return period

    def list_periods(self) -> List[ClosedPeriod]:
        return list(ClosedPeriod.objects.filter(**scope_to_tenant(self.account)))


MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
