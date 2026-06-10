"""Advisory-замок на синхронизацию по аккаунту.

PostgreSQL: session-level pg_try_advisory_lock(key) с гарантированным
pg_advisory_unlock(key) в finally. Session-, а НЕ xact-уровень — потому что
боевой синк состоит из множества коротких транзакций (_save_batch) и длинных
HTTP-вызовов к Битрикс; единая гигантская транзакция (которой требует
xact-lock) сломала бы батч-дизайн и держала бы блокировку БД минутами.
Session-lock держится поверх этих транзакций; при падении процесса PG снимает
его автоматически при закрытии соединения.

Иные БД (sqlite в тестах): полный no-op (вход/выход без SQL). sqlite в тестах
однопоточный — гонок нет, поэтому no-op безопасен.

Ключи раздельные per-account по scope: timesheet-синк и project-синк трогают
разные таблицы и могут идти параллельно друг другу, но не сами с собой.
"""

import logging
from contextlib import contextmanager
from functools import wraps

from django.db import connection
from django.http import JsonResponse


logger = logging.getLogger(__name__)

SCOPE_BITS = {"timesheet": 1, "project": 2}


class SyncLockBusy(Exception):
    """Бросается, когда advisory-лок по аккаунту/скоупу уже занят."""


def _advisory_key(account_pk: int, scope: str) -> int:
    if scope not in SCOPE_BITS:
        raise ValueError(f"sync_lock: unknown scope {scope!r}")
    return (int(account_pk) << 4) | SCOPE_BITS[scope]


@contextmanager
def account_sync_lock(account, scope: str):
    """Контекст-менеджер advisory-замка. На не-postgresql — no-op.

    Бросает SyncLockBusy, если лок занят (только на postgresql).
    """
    if connection.vendor != "postgresql":
        # no-op для sqlite и прочих
        yield
        return

    key = _advisory_key(account.pk, scope)
    acquired = False
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        row = cursor.fetchone()
        acquired = bool(row and row[0])
        if not acquired:
            raise SyncLockBusy()
    try:
        yield
    finally:
        # Освобождаем в отдельном курсоре — соединение могло смениться,
        # но session-lock привязан к соединению; при штатной работе это то же
        # соединение. На случай ошибки лог не валит основной поток.
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to release advisory lock %s: %s", key, exc)


def sync_lock(scope: str):
    """Декоратор: оборачивает view в account_sync_lock; на занятом локе -> 409.

    Применять ПОСЛЕ @auth_required (нужен request.bitrix24_account).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            account = getattr(request, "bitrix24_account", None)
            try:
                with account_sync_lock(account, scope):
                    return view_func(request, *args, **kwargs)
            except SyncLockBusy:
                return JsonResponse(
                    {"error": "Синхронизация уже выполняется, подождите"},
                    status=409,
                )
        return wrapped
    return decorator
