"""Обработчик logging, который складывает предупреждения и ошибки в system_log.

Зачем. До этого в SystemLog писал только декоратор @log_errors — то есть
исключительно НЕОБРАБОТАННЫЕ исключения вьюх (500-е). За месяц боевой работы
это дало ровно одну строку. Всё остальное, что приложение знает о своих
проблемах, уходило в stdout контейнера и пропадало:

  * `logger.warning("INN autofill failed (sync not affected): %s")` — синк молча
    не проставил ИНН;
  * `logger.exception("Timesheet sync failed for account %s")` — синк упал и
    вернул пользователю "warning" вместо данных;
  * `logger.warning("[ProjectBoard][INN] Single-lookup ... failed")` — Битрикс
    не отдал реквизит;
  * пропуски планировщика, отвалившиеся токены, деградации кэша.

Именно эти строки нужны, когда разбираешь жалобу пользователя, и именно их
не было. Обработчик закрывает разрыв: всё, что код логирует уровнем WARNING и
выше, попадает в таблицу и доступно через /api/logs/system.

Почему WARNING, а не INFO. На INFO приложение пишет много и по делу (каждая
страница синка, каждая нормализация), это десятки тысяч строк в сутки — такой
объём таблицу не лечит, а топит. Порог WARNING оставляет ровно то, что
означает "что-то пошло не так".

Безопасность обработчика важнее его полноты — логирование не имеет права
ломать запрос, ради которого оно случилось:

  * реентрантность. Запись в БД сама порождает логи (django.db.backends), и
    без защиты обработчик вызвал бы сам себя до переполнения стека. Флаг в
    threading.local() гасит вложенный вызов.
  * любые исключения проглатываются. Нет таблицы (миграции ещё не прошли),
    оборвалось соединение, БД в read-only — logging.Handler.handleError
    отрабатывает штатно, а запрос продолжается.
  * усечение. message и traceback режутся до MAX_*_LENGTH: одна аномалия с
    гигантским телом не должна раздувать строку таблицы.

Ретеншен — management-команда purge_request_logs (по умолчанию 30 дней),
запускается суточным циклом из start.sh рядом с остальными фоновыми задачами.
"""

import logging
import threading


MAX_MESSAGE_LENGTH = 8000
MAX_TRACEBACK_LENGTH = 16000
MAX_MODULE_LENGTH = 100  # SystemLog.module — CharField(max_length=100)

_state = threading.local()


_SUFFIX = "... [Truncated]"


def _truncate(value: str, limit: int) -> str:
    """Обрезает до limit ВКЛЮЧАЯ суффикс.

    Суффикс входит в бюджет, а не добавляется сверх него: module — это
    CharField(max_length=100), и лишние 15 символов маркера роняли бы вставку
    на PostgreSQL (sqlite в тестах длину не проверяет, поэтому промах вылез бы
    только в проде — на строке, которая сама по себе является сообщением об
    ошибке).
    """
    if value is None:
        return value
    if len(value) <= limit:
        return value
    if limit <= len(_SUFFIX):
        return value[:limit]
    return value[: limit - len(_SUFFIX)] + _SUFFIX


class DatabaseLogHandler(logging.Handler):
    """Пишет записи уровня WARNING и выше в main.models.SystemLog."""

    def emit(self, record: logging.LogRecord) -> None:
        # extra={"skip_db": True} — вызывающий уже сам положил строку в
        # SystemLog и логирует в консоль только для потока контейнера. Так
        # делает @log_errors: он пишет запись с человекочитаемым module
        # ("timesheet_sync"), и дубль от обработчика был бы лишним.
        if getattr(record, "skip_db", False):
            return

        # Вложенный вызов: мы уже внутри emit, и запись в БД снова что-то
        # залогировала. Тихо выходим, иначе получим бесконечную рекурсию.
        if getattr(_state, "in_emit", False):
            return

        _state.in_emit = True
        try:
            # Импорт внутри метода: settings.LOGGING собирается раньше, чем
            # готов реестр приложений, и импорт моделей на уровне модуля
            # уронил бы старт с AppRegistryNotReady.
            from main.models import SystemLog

            traceback_text = None
            if record.exc_info:
                traceback_text = _truncate(self.format_exception(record), MAX_TRACEBACK_LENGTH)

            SystemLog.objects.create(
                level=record.levelname,
                module=_truncate(self._build_module(record), MAX_MODULE_LENGTH),
                message=_truncate(record.getMessage(), MAX_MESSAGE_LENGTH),
                traceback=traceback_text,
            )
        except Exception:
            # Сбой логирования не должен влиять на запрос. handleError уважает
            # logging.raiseExceptions, то есть в тестах шумит, а в проде молчит.
            self.handleError(record)
        finally:
            _state.in_emit = False

    def format_exception(self, record: logging.LogRecord) -> str:
        formatter = self.formatter or logging.Formatter()
        return formatter.formatException(record.exc_info)

    @staticmethod
    def _build_module(record: logging.LogRecord) -> str:
        """`main.timesheet_sync_service:_sync_incremental:321` — где именно."""
        return f"{record.name}:{record.funcName}:{record.lineno}"
