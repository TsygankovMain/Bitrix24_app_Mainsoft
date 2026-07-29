"""Чистый расчёт значений полей карточки проекта при создании через кнопку
«Создать проект».

Правило заказчика (§5 спеки 2026-07-28): пустых полей не остаётся — у каждого
поля есть источник значения, автоматика или пользователь. Полный список
осознанных исключений — в докстринге resolve_project_fields.

Модуль намеренно не знает ни про Битрикс, ни про Django ORM: те же правила
дублирует форма на фронте, и арифметику надо проверять без моков сети.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .inn_validation import validate_inn

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
    inn: str
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


def _is_automatic_stage_option(option: Dict[str, Any]) -> bool:
    """True, если элемент stage_options — одна из автоматических стадий

    (PROJECT_AUTO_STAGES в project_board_shared.py: «Нет списаний 1/3
    месяца» — их выставляет фоновая автоматика, а не человек, и на них
    нельзя завести новый проект). Модуль намеренно не импортирует
    PROJECT_AUTO_STAGES оттуда — тот файл тянет Django ORM/кэш, а этот
    модуль обязан остаться проверяемым без Django (см. докстринг модуля).
    Вместо списка литералов — признаки, которые ставят ОБА поставщика
    stage_options (_fetch_project_stage_options и _build_legacy_stage_options
    в project_board_service.py) на каждый элемент без исключения:
    kind="auto" — основной сигнал; can_drop=False — запасной, на случай
    структуры без "kind" вовсе.

    Ровно эта пара атрибутов (kind="auto", can_drop=False) стоит у
    деградировавшего списка, который _fetch_project_stage_options отдаёт при
    сбое живого запроса статусов воронки (сеть/лимиты/рестарт воркера) —
    исключение проглатывается, а список остаётся непустым. Это и есть
    первопричина бага, который закрывает _first_manual_stage_id ниже.
    """
    kind = _clean_str(option.get("kind")).lower()
    if kind:
        return kind == "auto"
    return option.get("can_drop") is False


def _first_manual_stage_id(stage_options: List[Dict[str, Any]]) -> str:
    """Первая РУЧНАЯ стадия из stage_options — не первый элемент списка.

    stage_options может быть непустым и при этом не содержать НИ ОДНОЙ
    стадии, на которую можно поставить новый проект: _fetch_project_stage_options
    вправе вернуть список только из автоматических стадий (см. докстринг
    _is_automatic_stage_option). Взять stage_options[0] "в лоб" в этом
    случае значит подставить проекту автостадию — а она уйдёт и в
    локальную таблицу, и (build_card_fields в project_creation_service.py)
    в карточку CRM клиента, откуда её не вытащить мышью: карточка падает в
    автоколонку воронки.

    Ручной стадии нет вовсе (воронка не настроена, stage_options пуст, или
    отдала только автостадии) — возвращаем "": build_card_fields пустые
    значения не пишет, и Битрикс сам поставит стартовую стадию своей
    воронки при создании карточки. Это и есть требование спеки («стадия
    проставляется автоматически»), а не костыль в обход неё.
    """
    for option in stage_options or []:
        if not _is_automatic_stage_option(option):
            return _clean_str(option.get("id"))
    return ""


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

    Ключи в списке missing: "project_name", "company", "inn",
    "our_legal_entity_id" — их фронт подсвечивает в форме.

    Исключения из правила «пустых полей не остаётся» (см. докстринг модуля),
    перечислены полностью:
    - project_hours_budget — на момент заведения проекта объём часто
      неизвестен, а выдуманное число попало бы в отчёты как факт;
    - hourly_rate — поле убрано с формы 29.07.2026 по решению заказчика, а в
      настройках портала ставки может не быть. Требовать значение, которое
      сотруднику нечем ввести, значит запретить создание проектов совсем:
      ответ приходил с missing_fields=["hourly_rate"] и всеми четырьмя
      шагами в "пропущено", без единого действия на экране, которое это
      чинит. Неизвестная ставка остаётся неизвестной;
    - planned_budget_amount — производная от часов и ставки: остаётся None,
      если неизвестна любая из двух величин;
    - our_legal_entity_id — остаётся None без записи в missing, если на
      портале нет ни одного своего юрлица (legal_entities пуст): выбирать
      физически не из чего, поэтому поле не блокирует создание проекта;
    - stage — остаётся пустой строкой, если среди stage_options нет ни
      одной РУЧНОЙ стадии: воронка смарт-процесса ещё не настроена
      (stage_options пуст) либо живой запрос статусов воронки к Битриксу
      сбоил и вернул только автоматические стадии (см. докстринг
      _first_manual_stage_id) — в обоих случаях подставлять первый попавшийся
      элемент нельзя, а падать на пустом/деградировавшем портале нельзя тоже.

    ИНН (решение заказчика 29.07.2026, inn-brief.md) — обязателен РОВНО когда
    форма создаёт НОВУЮ компанию: company_id не передан, а company_name есть
    (это и есть пара с действием «Создать компанию «…»» на фронте). Во всех
    остальных случаях — компания уже выбрана по id (существующая — реквизиты
    не наша забота, см. докстринг ensure_company/ensure_requisite в
    project_creation_service.py), либо не выбрана вовсе (тогда уже блокирует
    "company", дублировать ошибку через "inn" незачем) — fields.inn всегда
    "", даже если в payload случайно долетело значение: это не проверка "поле
    пустое", а сознательный сброс на не-нашей ветке (см. тест
    test_inn_is_ignored_for_existing_company_even_if_sent).
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

    # ИНН — только на ветке "создаём новую компанию" (company_id отсутствует,
    # company_name есть). Для company_id-ветки (компания уже выбрана) поле
    # сбрасывается в "" безусловно, даже если payload его прислал — не наша
    # забота трогать реквизиты чужой/уже существующей компании (см. докстринг
    # выше и ensure_company/ensure_requisite в project_creation_service.py).
    inn = ""
    if not company_id and company_name:
        inn = _clean_str(form.get("inn"))
        if validate_inn(inn) is not None:
            missing.append("inn")

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
    elif len(legal_entities or []) > 1:
        # Ровно 0 сюда не попадает намеренно: если на портале нет ни одного
        # своего юрлица, выбирать не из чего и поле не должно блокировать
        # создание проекта (см. докстринг resolve_project_fields).
        missing.append("our_legal_entity_id")

    curator_user_id = _clean_str(form.get("curator_user_id")) or _clean_str(current_user_id)
    curator_name = _clean_str(form.get("curator_name")) or _clean_str(current_user_name)

    start_date = _parse_date(form.get("project_start_date"), today)
    end_date = _parse_date(form.get("project_end_date"), add_one_year(start_date))

    hours_budget = _parse_float(form.get("project_hours_budget"))

    # Ставка НЕ обязательна (решение заказчика 29.07.2026). Поле убрано с
    # формы, а в настройках портала ставки может не быть — тогда заполнить её
    # физически нечем, и требование блокировало создание проекта навсегда:
    # ответ приходил с missing_fields=["hourly_rate"], все четыре шага —
    # "пропущено", и на экране не было ни одного действия, которое это чинит.
    # Ведёт себя как project_hours_budget рядом: неизвестна — остаётся
    # неизвестной, в отчёты не попадает выдуманное число.
    hourly_rate = _parse_float(form.get("hourly_rate"))
    if hourly_rate is None:
        hourly_rate = _parse_float((config or {}).get("hourly_rate"))
    hourly_rate_is_known = bool(hourly_rate)
    if not hourly_rate_is_known:
        hourly_rate = 0.0

    planned_amount = None
    if hours_budget is not None and hourly_rate_is_known:
        planned_amount = round(hours_budget * hourly_rate, 2)

    stage = _clean_str(form.get("stage"))
    if not stage:
        stage = _first_manual_stage_id(stage_options)

    fields = ResolvedProjectFields(
        project_name=project_name,
        company_id=company_id,
        company_name=company_name,
        inn=inn,
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
