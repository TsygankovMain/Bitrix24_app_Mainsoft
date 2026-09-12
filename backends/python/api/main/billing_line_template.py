"""Шаблон формулировки строки счёта.

Зачем. Строка счёта раньше называлась ровно так, как названа карточка
проекта. У НУОЛАБ карточка названа по клиенту, и в счёт ушло «НУОЛАБ» —
описания работ в документе не оказалось вовсе. Название работ должно приходить
из задач, а как именно оно читается — решает портал, а не код: у одних в
строке «Настройка отчётов, август 2026», у других «Настройка отчётов
(Проект X)». Поэтому формулировка вынесена в настройку приложения
(``billing_line_template``), а не зашита в сервис.

Подстановки — ровно пять, по-русски:

``{задача}``   предмет строки. При группировке по задачам это название задачи;
               при остальных — предмет соответствующей группировки (проект,
               сотрудник, «Услуги по договору»). Слот один и тот же: «то, о чём
               эта строка», а переименовывать его под каждую группировку
               значило бы держать четыре шаблона вместо одного.
``{проект}``   название проекта строки.
``{клиент}``   название клиента документа.
``{месяц}``    «август 2026» либо «август—сентябрь 2026» для периода из
               нескольких месяцев.
``{период}``   «01.08.2026—31.08.2026».

Три правила подстановки, и все три — про то, чтобы молча не испортить текст
документа.

1. НЕИЗВЕСТНАЯ подстановка остаётся в тексте как есть: ``{задание}`` так и
   уйдёт в предпросмотр строкой ``{задание}``. Стереть её значило бы отдать
   человеку правильно выглядящую строку с пропавшим куском формулировки —
   опечатку в настройке никто бы не заметил до разговора с клиентом. А
   видимая фигурная скобка в предпросмотре ловится глазом сразу.
2. ИЗВЕСТНАЯ подстановка без значения (у документа нет клиента, у строки нет
   проекта) убирается вместе с прилипшим к ней разделителем: «Задача, » и
   «Задача ()» в счёте выглядят как потерянные данные. Подставлять сюда
   «понятный текст» вроде «клиент не указан» нельзя — это печатная форма для
   клиента, и служебная пометка в наименовании работ хуже её отсутствия.
3. Если после подстановок не осталось ничего — возвращается предмет строки.
   Пустое наименование работ не имеет права уйти в счёт ни при какой настройке.
"""

import re
from datetime import date
from typing import Any, Dict, Mapping, Optional

# Значение по умолчанию: «<Название задачи>, август 2026». Оно и есть ответ на
# исходную жалобу — в наименовании работ название задачи, а не карточки.
DEFAULT_LINE_TEMPLATE = "{задача}, {месяц}"

# Поддерживаемые подстановки. Порядок — для подсказки в интерфейсе.
LINE_TEMPLATE_PLACEHOLDERS = ("задача", "проект", "клиент", "месяц", "период")

# Уровень задачи в строке (настройка ``billing_line_task_level``): какое
# именно название задачи попадает в ``{задача}``.
#
# «task» — сама задача, в которой отражены часы (лист дерева). «root» — её
# родитель ВЕРХНЕГО уровня: подзадачи схлопываются в одну строку.
#
# Константы живут здесь, а не в billing_service, чтобы их видели оба
# импортёра — и сервис, и разбор настроек (billing_settings): этот модуль
# ничего из main не импортирует и поэтому не может замкнуть импорты.
TASK_LEVEL_TASK = "task"
TASK_LEVEL_ROOT = "root"
TASK_LEVELS = (TASK_LEVEL_TASK, TASK_LEVEL_ROOT)
DEFAULT_TASK_LEVEL = TASK_LEVEL_TASK

MONTHS_NOMINATIVE = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)

# Маркер пустого значения известной подстановки. \x00 в тексте настройки
# встретиться не может, поэтому он безопасен как временная метка.
_EMPTY = "\x00"

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")

# Разделители, которые убираются вместе с опустевшей подстановкой. Символы
# перечислены обычной строкой (её же берёт strip), а класс регулярки собирается
# из неё через re.escape — иначе экранирующая обратная косая попала бы в набор
# символов для strip и обрезала бы текст по ней.
_SEPARATOR_CHARS = ",;:·|/-–—"
_SEPARATOR_CLASS = "[" + re.escape(_SEPARATOR_CHARS) + "]"
_BEFORE_EMPTY_RE = re.compile(r"[ \t]*" + _SEPARATOR_CLASS + r"[ \t]*" + _EMPTY)
_AFTER_EMPTY_RE = re.compile(_EMPTY + r"[ \t]*" + _SEPARATOR_CLASS + r"[ \t]*")
# Опустевшая подстановка внутри скобок: «Задача ()» — след пропавшего значения.
_EMPTY_BRACKETS_RE = re.compile(r"[ \t]*\([ \t]*" + _EMPTY + r"[ \t]*\)")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def month_label(period_from: Optional[date], period_to: Optional[date]) -> str:
    """Подстановка ``{месяц}``: «август 2026», «август—сентябрь 2026».

    Годы указываются оба, когда период их пересекает («декабрь 2026 — январь
    2027»): «декабрь—январь 2027» соврал бы про год начала работ.
    """
    if period_from is None and period_to is None:
        return ""
    start = period_from or period_to
    end = period_to or period_from
    if start is None or end is None:
        return ""
    if start > end:
        start, end = end, start

    start_name = MONTHS_NOMINATIVE[start.month - 1]
    end_name = MONTHS_NOMINATIVE[end.month - 1]

    if start.year == end.year:
        if start.month == end.month:
            return f"{start_name} {start.year}"
        return f"{start_name}—{end_name} {start.year}"
    return f"{start_name} {start.year} — {end_name} {end.year}"


def period_label(period_from: Optional[date], period_to: Optional[date]) -> str:
    """Подстановка ``{период}``: «01.08.2026—31.08.2026»."""
    start = period_from.strftime("%d.%m.%Y") if period_from else ""
    end = period_to.strftime("%d.%m.%Y") if period_to else ""
    if start and end:
        return start if start == end else f"{start}—{end}"
    return start or end


def normalize_line_template(value: Any) -> str:
    """Шаблон из настройки. Пусто — значение по умолчанию.

    Пустой шаблон дал бы пустое наименование работ в каждой строке счёта,
    поэтому «ничего не задано» читается как «как по умолчанию», а не как
    «оставить строки без названия».
    """
    text = _text(value)
    return text or DEFAULT_LINE_TEMPLATE


def render_line_template(
    template: Any,
    values: Mapping[str, Any],
    *,
    fallback: str = "",
) -> str:
    """Текст строки по шаблону. Правила — в докстринге модуля."""
    resolved: Dict[str, str] = {
        key: _text(value) for key, value in (values or {}).items()
    }

    def substitute(match: "re.Match[str]") -> str:
        name = match.group(1).strip().lower()
        if name not in resolved:
            # Неизвестная подстановка остаётся видимой — см. правило 1.
            return match.group(0)
        return resolved[name] or _EMPTY

    text = _PLACEHOLDER_RE.sub(substitute, normalize_line_template(template))

    if _EMPTY in text:
        text = _EMPTY_BRACKETS_RE.sub("", text)
        text = _BEFORE_EMPTY_RE.sub("", text)
        text = _AFTER_EMPTY_RE.sub("", text)
        text = text.replace(_EMPTY, "")

    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    text = text.strip(" \t" + _SEPARATOR_CHARS)

    return text or _text(fallback)
