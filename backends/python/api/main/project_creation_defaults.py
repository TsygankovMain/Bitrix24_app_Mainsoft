"""Чистый расчёт значений полей карточки проекта при создании через кнопку
«Создать проект».

Правило заказчика (§5 спеки 2026-07-28): пустых полей не остаётся — у каждого
поля есть источник значения, автоматика или пользователь. Осознанные
исключения — project_hours_budget и производная от неё planned_budget_amount:
на момент заведения проекта объём часто неизвестен, а выдуманное число попало
бы в отчёты как факт.

Модуль намеренно не знает ни про Битрикс, ни про Django ORM: те же правила
дублирует форма на фронте, и арифметику надо проверять без моков сети.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PROJECT_TYPE = "delivery"
DEFAULT_BUDGET_MODE = "hours_and_amount"


def add_one_year(value: date) -> date:
    """Дата + 1 год. 29 февраля переносится на 28-е: в невисокосном году
    такой даты нет, а падать на календарном крае нельзя."""
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


@dataclass
class ResolvedProjectFields:
    project_name: str
    company_id: Optional[str]
    company_name: str
    our_legal_entity_id: Optional[str]
    our_legal_entity_name: str
    curator_user_id: str
    curator_name: str
    project_start_date: date
    project_end_date: date
    project_hours_budget: Optional[float]
    hourly_rate: float
    planned_budget_amount: Optional[float]
    project_type: str
    budget_mode: str
    is_support: bool
    stage: str


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_float(value: Any) -> Optional[float]:
    text = _clean_str(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any, fallback: date) -> date:
    text = _clean_str(value)
    if not text:
        return fallback
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return fallback


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean_str(value).upper() in {"Y", "YES", "TRUE", "1"}


def resolve_project_fields(
    form: Dict[str, Any],
    *,
    config: Dict[str, Any],
    current_user_id: str,
    current_user_name: str,
    today: date,
    legal_entities: List[Dict[str, Any]],
    stage_options: List[Dict[str, Any]],
) -> Tuple[ResolvedProjectFields, List[str]]:
    """Считает итоговые значения полей и список недостающих обязательных.

    Ключи в списке missing: "project_name", "company", "our_legal_entity_id",
    "hourly_rate" — их фронт подсвечивает в форме.
    """
    form = form or {}
    missing: List[str] = []

    project_name = _clean_str(form.get("project_name"))
    if not project_name:
        missing.append("project_name")

    company_id = _clean_str(form.get("company_id")) or None
    company_name = _clean_str(form.get("company_name"))
    if not company_id and not company_name:
        missing.append("company")

    legal_entity_id = _clean_str(form.get("our_legal_entity_id")) or None
    legal_entity_name = _clean_str(form.get("our_legal_entity_name"))
    if legal_entity_id:
        for entity in legal_entities or []:
            if _clean_str(entity.get("id")) == legal_entity_id:
                legal_entity_name = legal_entity_name or _clean_str(entity.get("name"))
                break
    elif len(legal_entities or []) == 1:
        only = legal_entities[0]
        legal_entity_id = _clean_str(only.get("id")) or None
        legal_entity_name = _clean_str(only.get("name"))
    elif legal_entities:
        missing.append("our_legal_entity_id")

    curator_user_id = _clean_str(form.get("curator_user_id")) or _clean_str(current_user_id)
    curator_name = _clean_str(form.get("curator_name")) or _clean_str(current_user_name)

    start_date = _parse_date(form.get("project_start_date"), today)
    end_date = _parse_date(form.get("project_end_date"), add_one_year(start_date))

    hours_budget = _parse_float(form.get("project_hours_budget"))

    hourly_rate = _parse_float(form.get("hourly_rate"))
    if hourly_rate is None:
        hourly_rate = _parse_float((config or {}).get("hourly_rate"))
    if not hourly_rate:
        missing.append("hourly_rate")
        hourly_rate = 0.0

    planned_amount = None
    if hours_budget is not None:
        planned_amount = round(hours_budget * hourly_rate, 2)

    stage = _clean_str(form.get("stage"))
    if not stage and stage_options:
        stage = _clean_str(stage_options[0].get("id"))

    fields = ResolvedProjectFields(
        project_name=project_name,
        company_id=company_id,
        company_name=company_name,
        our_legal_entity_id=legal_entity_id,
        our_legal_entity_name=legal_entity_name,
        curator_user_id=curator_user_id,
        curator_name=curator_name,
        project_start_date=start_date,
        project_end_date=end_date,
        project_hours_budget=hours_budget,
        hourly_rate=hourly_rate,
        planned_budget_amount=planned_amount,
        project_type=_clean_str(form.get("project_type")) or DEFAULT_PROJECT_TYPE,
        budget_mode=_clean_str(form.get("budget_mode")) or DEFAULT_BUDGET_MODE,
        is_support=_parse_bool(form.get("is_support")),
        stage=stage,
    )
    return fields, missing
