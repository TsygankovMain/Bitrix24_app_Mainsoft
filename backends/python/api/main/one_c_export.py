"""Отправка списанных часов в 1С: сборка пакета и разбор ответа.

Здесь только чистая часть — ни сети, ни базы. Приложение отвечает за состав и
нормализацию данных (кто, кому, сколько часов, по какому ИНН), 1С — за
сопоставление со своими справочниками. Поэтому ИНН обеих сторон резолвится
здесь: в 1С нет ни проектов портала, ни его компаний.

Формат пакета описан в проектном решении
«Передача часов из Учёта трудозатрат в 1С:Бухгалтерию», раздел 4.
"""
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

CONTRACT_VERSION = 1

# Причины отказа, которые возвращает приёмник. Список закрытый: приложение
# показывает их человеку, и появление нового кода — повод обновить обе стороны.
REASON_LABELS = {
    "сотрудник_не_сопоставлен": "Сотрудник не связан с физлицом в 1С",
    "клиент_не_найден": "Клиент не найден в 1С по ИНН",
    "юрлицо_не_найдено": "Наше юрлицо не найдено в 1С по ИНН",
    "нет_инн": "У проекта не заполнен ИНН клиента или нашего юрлица",
    "ошибка_записи": "1С не смогла записать документ",
    "уже_принята": "Строка уже принята прежней отправкой",
    "осталась_в_1С": "Строка была принята раньше, но в этой отправке её нет",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _day(value: Any) -> str:
    """Дата отражения — днём: документ учёта времени датируется днём, не секундой."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _clean(value)
    return text[:10] if len(text) >= 10 else ""


def _task_titles(item: Any) -> List[str]:
    """Иерархия задачи из Битрикса: от верхней задачи к нижней."""
    titles = getattr(item, "task_hierarchy_titles", None) or []
    if not isinstance(titles, list):
        return []
    return [_clean(t) for t in titles if _clean(t)]


def _task_name(item: Any) -> str:
    """Название задачи: последний уровень иерархии — так её видит человек
    в Битриксе. Если иерархии нет, годится название проекта."""
    titles = _task_titles(item)
    if titles:
        return titles[-1]
    return _clean(getattr(item, "project_title", ""))


def _task_path(item: Any) -> List[str]:
    """Путь до задачи: родительские задачи без самой задачи.

    В 1С по нему выстраивается такое же дерево, как в Битриксе, — иначе все
    задачи клиента лежали бы плоским списком, и найти нужную стало бы нельзя.
    """
    return _task_titles(item)[:-1]


def build_batch(
    items: Iterable[Any],
    projects_by_item: Mapping[str, Any],
    companies_inn: Mapping[str, str],
    legal_inn: Mapping[str, str],
    employee_names: Mapping[str, str],
    period_from: date,
    period_to: date,
    sending_id: str,
    tasks_root: str = "Б-24",
) -> Dict[str, Any]:
    """Собирает пакет часов за период.

    Строки без проекта не выбрасываются: пусть 1С вернёт причину, и она попадёт
    в отчёт. Молча потерянный час хуже отклонённого — отклонённый видно.
    """
    rows: List[Dict[str, Any]] = []

    for item in items:
        card = projects_by_item.get(_clean(getattr(item, "project_item_id", "")))
        our = _clean(legal_inn.get(_clean(getattr(card, "our_legal_entity_id", "")), "")) if card else ""
        client = _clean(companies_inn.get(_clean(getattr(card, "company_id", "")), "")) if card else ""

        employee_id = _clean(getattr(item, "employee_id", ""))

        rows.append({
            "идЗаписи": _clean(getattr(item, "bitrix_id", "")),
            "дата": _day(getattr(item, "date_reflection", None)),
            "часы": float(getattr(item, "hours", 0) or 0),
            "сотрудник": {
                "идБитрикс": employee_id,
                "фамилияИмя": _clean(employee_names.get(employee_id, "")),
            },
            "клиент": {
                "инн": client,
                "название": _clean(getattr(card, "company_name", "")) if card else "",
            },
            "юрлицо": {
                "инн": our,
                "название": _clean(getattr(card, "our_legal_entity_name", "")) if card else "",
            },
            "задача": {
                "идБитрикс": _clean(getattr(item, "task_id", "")),
                "название": _task_name(item),
                "путь": _task_path(item),
            },
            "комментарий": _clean(getattr(item, "description", "")),
            "оплачиваемые": bool(getattr(item, "is_billable", False)),
        })

    return {
        "версияКонтракта": CONTRACT_VERSION,
        "период": {"с": period_from.isoformat(), "по": period_to.isoformat()},
        "отправка": sending_id,
        "кореньЗадач": tasks_root,
        "строки": rows,
    }


def parse_response(payload: Any) -> Dict[str, Any]:
    """Разбирает ответ приёмника.

    Ответ приходит из чужой системы, поэтому разбор обязан пережить что угодно:
    отказ без счётчиков, мусор вместо JSON, отсутствующие поля.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "accepted": 0,
        "rejected": 0,
        "documents": [],
        "rows": [],
        "message": "",
    }

    if not isinstance(payload, dict):
        result["message"] = "Приёмник ответил не объектом JSON"
        return result

    result["ok"] = bool(payload.get("ok", False))
    result["message"] = _clean(payload.get("сообщение"))
    result["accepted"] = int(payload.get("принято") or 0)
    result["rejected"] = int(payload.get("отклонено") or 0)

    documents = payload.get("документы")
    if isinstance(documents, list):
        result["documents"] = [_clean(d) for d in documents]

    rows = payload.get("строки")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            reason = _clean(row.get("причина"))
            result["rows"].append({
                "entry_id": _clean(row.get("идЗаписи")),
                "status": _clean(row.get("статус")),
                "reason": reason,
                "reason_label": REASON_LABELS.get(reason, reason),
                "text": _clean(row.get("текст")),
            })

    return result


def summarize(parsed: Mapping[str, Any]) -> str:
    """Короткая строка для журнала и для человека."""
    if not parsed.get("ok"):
        return parsed.get("message") or "Отправка не принята"
    return "принято {accepted}, отклонено {rejected}, документов {docs}".format(
        accepted=parsed.get("accepted", 0),
        rejected=parsed.get("rejected", 0),
        docs=len(parsed.get("documents") or []),
    )
