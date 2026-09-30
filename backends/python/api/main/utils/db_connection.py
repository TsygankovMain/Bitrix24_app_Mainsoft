"""Переподключение к БД в долгих фоновых процессах."""

import logging

from django.db import connection

logger = logging.getLogger(__name__)


def ensure_db_connection() -> None:
    """Выбросить соединение с БД, если сервер его уже закрыл.

    Фоновая команда (start.sh -> sync_all_portals) держит ОДНО соединение на
    весь прогон, а у прод-БД Timeweb idle_session_timeout = 15 минут: пока
    синк одного портала долго ходит в Битрикс, не трогая БД, сервер рвёт
    соединение. Django в management-команде сам не переподключается, поэтому
    дальше падало всё: каждый следующий портал, запись ошибки в system_log и
    финальный run.save() — прогон навсегда оставался "running". Синк проектов
    так не завершился ни разу с 28.07.2026 (377 прогонов). После close()
    Django откроет новое соединение при следующем запросе.
    """
    if connection.connection is None:
        return
    try:
        usable = connection.is_usable()
    except Exception:  # noqa: BLE001
        usable = False
    if not usable:
        # Сначала close(): предупреждение пишется в system_log той же БД.
        connection.close()
        logger.warning("DB connection was closed by the server; reconnecting.")
