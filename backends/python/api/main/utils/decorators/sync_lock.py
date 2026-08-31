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

scope="project_create" (кнопка «Создать проект», main.project_creation_service.
ProjectCreationService.create) — намеренно ОТДЕЛЬНЫЙ от scope="project"
(фоновая ProjectSyncService.sync() из sync_scheduler_service и
_save_configuration_with_project_sync). Создание одного проекта — короткая
операция по нажатию кнопки, а полный синк на крупном портале может идти
секундами и дольше; общий scope означал бы, что кнопка ждёт чужую
синхронизацию портала, а синхронизация пропускает цикл из-за чужого нажатия
кнопки. Обе накладки не нужны, когда данные реально не пересекаются в моменте.

У этого scope ЕЩЁ ОДНО отличие от timesheet/project/users — выбор субъекта
лока (см. _lock_subject_pk): Bitrix24Account в этом приложении — запись НА
СОТРУДНИКА (уникальность по паре «пользователь + домен», у каждого свои
токены), а не на портал/компанию. Кнопку «Создать проект» могут нажать два
РАЗНЫХ сотрудника одного портала одновременно, поэтому её защита от гонки
обязана сериализовать их ОБОИХ на одном субъекте — портале — независимо от
USE_PORTAL_SCOPING. Если бы это, как у остальных scope, включалось только
флагом, защита молча исчезла бы на любом окружении, где флаг не выставлен
(его боевое значение задаётся переменной окружения вне репозитория и нигде
не закреплено тестом), и ни один тест бы не покраснел.
"""

import hashlib
import logging
from contextlib import contextmanager
from functools import wraps

from django.conf import settings
from django.db import connection
from django.http import JsonResponse


logger = logging.getLogger(__name__)

SCOPE_BITS = {"timesheet": 1, "project": 2, "users": 3, "project_create": 4, "tasks": 5}


class SyncLockBusy(Exception):
    """Бросается, когда advisory-лок по аккаунту/скоупу уже занят."""


def _advisory_key(account_pk, scope: str) -> int:
    """Стабильный signed int64-ключ для pg_try_advisory_lock(bigint).

    PK аккаунта — UUID (128 бит), поэтому int(pk) << 4 переполняет bigint и
    PostgreSQL отвергает вызов (инцидент 2026-06-10: 500 на каждом синке).
    Хэшируем str(pk) в 8 байт blake2b — детерминированно между процессами
    (воркеры gunicorn, cron-команда), в отличие от солёного hash().
    Младшие 4 бита зарезервированы под scope, как и в исходной схеме.
    """
    if scope not in SCOPE_BITS:
        raise ValueError(f"sync_lock: unknown scope {scope!r}")
    digest = hashlib.blake2b(str(account_pk).encode("utf-8"), digest_size=8).digest()
    base = int.from_bytes(digest, "big", signed=True)
    # base & ~0xF чистит младшие 4 бита, не выводя из диапазона int64.
    return (base & ~0xF) | SCOPE_BITS[scope]


def _lock_subject_pk(account, scope: str):
    """Субъект advisory-замка. Условие зависит от scope:

    - scope="project_create": portal.pk при наличии portal, иначе account.pk
      — БЕЗУСЛОВНО, независимо от USE_PORTAL_SCOPING. Кнопку «Создать проект»
      могут нажать два разных сотрудника (два разных Bitrix24Account) одного
      портала одновременно, и защита от этой гонки не имеет права молча
      зависеть от флага, который нигде не закреплён тестом (см. докстринг
      модуля). Другими словами: для этого scope выбор субъекта — не то же
      самое условие, что ниже, а отдельная, более строгая ветка.
    - Остальные scope (timesheet/project/users): portal.pk при включённом
      portal-скоупинге и наличии portal, иначе account.pk (унаследованное
      поведение, БИТ-в-БИТ — не менять, на нём завязаны другие тесты).

    Под portal-скоупингом синк логически идёт по компании (один представитель
    синкает данные всей компании в общие portal-таблицы), поэтому замок должен
    быть «по компании», а не по учётке."""
    if scope == "project_create":
        portal = getattr(account, "portal", None)
        if portal is not None:
            return portal.pk
        return account.pk
    if bool(getattr(settings, "USE_PORTAL_SCOPING", False)):
        portal = getattr(account, "portal", None)
        if portal is not None:
            return portal.pk
    return account.pk


@contextmanager
def account_sync_lock(account, scope: str):
    """Контекст-менеджер advisory-замка. На не-postgresql — no-op.

    Бросает SyncLockBusy, если лок занят (только на postgresql).
    """
    if connection.vendor != "postgresql":
        # no-op для sqlite и прочих
        yield
        return

    key = _advisory_key(_lock_subject_pk(account, scope), scope)
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
