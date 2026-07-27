"""Помощник скоупинга «tenant» (этап 3 перестройки мультитенантности).

scope_to_tenant(account, write=False) возвращает kwargs для .filter()/создания.
Поведение управляется флагом settings.USE_PORTAL_SCOPING (дефолт False):

- Флаг OFF  -> {"bitrix24_account": account}  (текущее поведение, БИТ-в-БИТ).
- Флаг ON, portal есть, write=False -> {"portal": account.portal}  (чтение по компании).
- Флаг ON, portal есть, write=True  -> {"portal": account.portal, "bitrix24_account": account}
  (двойная запись: новые записи получают и portal, и account — для аудита «кто синкнул»
  и для возможности отката на account-скоупинг до этапа 4).
- Флаг ON, portal пуст (None) -> {"bitrix24_account": account}  (фолбэк, переходный период
  пока backfill не добил аккаунт).

Использование в точках скоупинга:
    TimesheetItem.objects.filter(**scope_to_tenant(self.account))
    TimesheetItem.objects.filter(**scope_to_tenant(self.account), bitrix_id__in=ids)
    TimesheetItem(**scope_to_tenant(self.account, write=True), bitrix_id=bid, **defaults)
"""
from typing import Any, Dict

from django.conf import settings


def portal_scoping_enabled() -> bool:
    """Публичный хелпер флага — переиспользуется вне модуля (например,
    sync_scheduler_service при выборе множества аккаунтов для scope="timesheet")."""
    return bool(getattr(settings, "USE_PORTAL_SCOPING", False))


def scope_to_tenant(account: Any, *, write: bool = False) -> Dict[str, Any]:
    """Возвращает kwargs скоупинга для TimesheetItem/ProjectCard."""
    if account is None:
        # Защита: без аккаунта возвращаем заведомо пустой фильтр на account
        # (вызывающий код и так не должен звать без аккаунта).
        return {"bitrix24_account": account}

    if not portal_scoping_enabled():
        return {"bitrix24_account": account}

    portal = getattr(account, "portal", None)
    if portal is None:
        # Фолбэк: portal ещё не проставлен (backfill не добил) — ведём себя как раньше.
        return {"bitrix24_account": account}

    if write:
        # Двойная запись: и portal, и account.
        return {"portal": portal, "bitrix24_account": account}
    return {"portal": portal}
