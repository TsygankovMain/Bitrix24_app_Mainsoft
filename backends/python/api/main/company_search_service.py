"""Поиск компаний по мере ввода — одним запросом к Битриксу с фильтром.

Альтернатива (выгрузить справочник и фильтровать на клиенте) на боевом портале
означает 23 252 компании и 465 страниц на каждое открытие формы: ровно то, что
чинил хотфикс 2026-07-28. Поэтому ищем на стороне Битрикса.
"""
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client
from django.core.cache import cache

from .models import Bitrix24Account
from .project_board_shared import build_account_cache_key

logger = logging.getLogger(__name__)

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 50
# Верхняя отсечка на размер ответа вызывающему, а не обещание. Один вызов
# crm.company.list физически не возвращает больше своей страницы (на практике
# 50 записей) — сервис намеренно не обходит страницы (см. докстринг модуля),
# так что при limit > размера страницы Битрикса компаний всё равно придёт не
# больше, чем страница отдала.
MAX_LIMIT = 100
SEARCH_CACHE_TTL = 60 * 5
MY_COMPANIES_CACHE_TTL = 60 * 60 * 6
INN_LENGTHS = {10, 12}


def _clean_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _safe_int(value: Any, default: int) -> int:
    """`int(value)`, но никогда не бросает исключение — что угодно, что не
    разбирается в число (пустая строка, `None`, произвольный мусор), даёт
    `default` вместо падения. Перехватываются все три исключения, которые
    реально может бросить `int()` на значениях, приходящих из JSON-ответа
    Битрикса: `TypeError` (`None`, список, словарь), `ValueError`
    (нечисловая строка, `float('nan')`) и `OverflowError` (`float('inf')`/
    `float('-inf')`). Последнее — не гипотетический случай: стандартный
    json-парсер Python по умолчанию принимает `Infinity`/`-Infinity`/`NaN`
    как валидные числа, так что поле `total` в ответе `crm.company.list`
    вполне может прийти именно такими значениями."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _parse_limit(limit: Any) -> int:
    """Разбирает пользовательский `limit`, не доверяя ничему.

    Пустая строка (`?limit=` без значения в будущем HTTP-эндпоинте), `None`,
    нечисловой мусор — это не «странный лимит», а «лимит не передали»:
    подставляется `DEFAULT_LIMIT`. Валидные, но не влезающие в диапазон числа
    (0, отрицательные, больше `MAX_LIMIT`; `bool` тоже `int` в Python, так что
    `True`/`False` тоже проходят через `int()`) — отсекаются `max`/`min`.
    Никогда не бросает исключение.
    """
    return max(1, min(_safe_int(limit, DEFAULT_LIMIT), MAX_LIMIT))


def _normalize_rows(response: Dict[str, Any], method_name: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Приводит response["result"] к списку словарей, не доверяя форме ответа.

    `list(response.get("result") or [])` не бросает исключение ни на словаре
    (`list({"a": 1})` -> `["a"]`), ни на строке (`list("abc")` -> `["a", "b", "c"]`)
    — а следующий код вызывает `.get()` на элементах результата, что уже роняет
    запрос необработанным `AttributeError`. Поэтому форму проверяем сразу здесь:
    всё, что не список словарей, — признак сбоя, а не повод положить в компании
    мусорные записи вроде отдельных букв или ключей словаря.
    """
    raw_result = response.get("result")
    if raw_result is None:
        # {"result": None} — это не пустой список ("ничего не нашлось"), а
        # неожиданный ответ Битрикса. Считать его успехом опасно: search() и
        # list_my_companies() кэшируют успешный результат (второй — на
        # MY_COMPANIES_CACHE_TTL, шесть часов), и один такой ответ спрятал бы
        # уже существующие компании/юрлица на весь этот срок.
        return [], True
    if isinstance(raw_result, list):
        rows = [row for row in raw_result if isinstance(row, dict)]
        failed = len(rows) < len(raw_result)
        return rows, failed
    logger.warning("Неожиданная форма result от %s: %s", method_name, type(raw_result).__name__)
    return [], True


class CompanySearchService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
        """Ищет компании по названию, а для похожих на ИНН запросов — ещё и по ИНН.

        `failed=True` означает «не доверяй полноте списка», а НЕ «список
        пуст»: при сбое по форме ответа Битрикса (см. `_normalize_rows`) уже
        разобранные записи всё равно попадают в `companies` одновременно с
        `failed=True`. Проверяйте оба поля независимо, не выводите одно из
        другого.
        """
        query = _clean_str(query)
        limit = _parse_limit(limit)

        if len(query) < MIN_QUERY_LENGTH:
            return {"companies": [], "truncated": False, "failed": False}

        digest = hashlib.sha1(f"{query}|{limit}".encode("utf-8")).hexdigest()[:16]
        cache_key = build_account_cache_key(self.account, f"company-search:{digest}")
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        rows: List[Dict[str, Any]] = []
        failed = False
        response: Dict[str, Any] = {}
        try:
            response = self.client._bitrix_token.call_method(
                "crm.company.list",
                {"filter": {"%TITLE": query}, "select": ["ID", "TITLE"], "order": {"TITLE": "ASC"}},
            )
            rows, shape_failed = _normalize_rows(response, "crm.company.list")
            if shape_failed:
                failed = True
        except Exception as exc:
            failed = True
            logger.warning("Company search by title failed for %s: %s", query, exc)

        # Снимок «сколько строк реально вернул поиск по названию» — до того,
        # как ниже в rows допишутся синтетические записи из поиска по ИНН.
        # total/next в ответе Битрикса относятся к TITLE-фильтру, а не к
        # объединённому набору, поэтому сравнивать их нужно с этим числом.
        title_rows_count = len(rows)

        inn_by_company: Dict[str, str] = {}
        if query.isdigit() and len(query) in INN_LENGTHS:
            try:
                inn_response = self.client._bitrix_token.call_method(
                    "crm.requisite.list",
                    {
                        "filter": {"ENTITY_TYPE_ID": 4, "%RQ_INN": query},
                        "select": ["ENTITY_ID", "RQ_INN"],
                    },
                )
                # _normalize_rows фильтрует весь список разом, поэтому не
                # важно, где именно оказался мусор — до, после или между
                # валидными записями (ср. с list_my_companies() и веткой
                # crm.company.list выше, где так было не всегда: цикл падал
                # необработанным исключением на первом же плохом элементе,
                # и то, что до него успело записаться в inn_by_company,
                # переживало except — асимметрично, в зависимости от порядка).
                inn_rows, inn_shape_failed = _normalize_rows(inn_response, "crm.requisite.list")
                if inn_shape_failed:
                    failed = True
                for row in inn_rows:
                    entity_id = _clean_str(row.get("ENTITY_ID") or row.get("entityId"))
                    inn = _clean_str(row.get("RQ_INN") or row.get("rqInn"))
                    if entity_id and inn:
                        inn_by_company.setdefault(entity_id, inn)
            except Exception as exc:
                failed = True
                logger.warning("Company search by INN failed for %s: %s", query, exc)

            for entity_id, inn in inn_by_company.items():
                if not any(_clean_str(r.get("ID") or r.get("id")) == entity_id for r in rows):
                    rows.append({"ID": entity_id, "TITLE": "", "RQ_INN": inn})

        companies: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            company_id = _clean_str(row.get("ID") or row.get("id"))
            if not company_id or company_id in seen:
                continue
            seen.add(company_id)
            companies.append({
                "id": company_id,
                "name": _clean_str(row.get("TITLE") or row.get("title")) or company_id,
                "inn": inn_by_company.get(company_id) or _clean_str(row.get("RQ_INN")) or None,
            })

        # truncated — не только «набралось больше limit», но и «сам Битрикс
        # говорит, что подходящих компаний больше, чем прислал за один вызов»
        # (next — есть следующая страница, total — общее число совпадений
        # больше, чем пришло строк). Без этого при limit=50 и ровно 50
        # пришедших строках пользователь не узнаёт, что запрос надо уточнить.
        truncated = (
            len(companies) > limit
            or bool(response.get("next"))
            or _safe_int(response.get("total"), 0) > title_rows_count
        )
        payload = {"companies": companies[:limit], "truncated": truncated, "failed": failed}

        # Неудачный поиск не кэшируем: сбой Битрикса может быть временным, и
        # запирать пользователя на пять минут с пустым списком неправильно.
        if not failed:
            cache.set(cache_key, payload, SEARCH_CACHE_TTL)
        return payload

    def list_my_companies(self, bypass_cache: bool = False) -> Dict[str, Any]:
        """Свои юрлица — серверным фильтром IS_MY_COMPANY.

        ProjectCardService.get_legal_entities() делает то же самое, но выкачивая
        весь справочник портала и фильтруя в Python: на боевом это 465 страниц
        ради нескольких записей.

        Как и в `search()`: `failed=True` означает «не доверяй полноте
        списка», а НЕ «список пуст». При сбое сети `companies` действительно
        будет пуст, но при сбое по форме ответа (см. `_normalize_rows`)
        частично разобранные записи всё равно попадут в `companies`
        одновременно с `failed=True`.

        bypass_cache=True пропускает ЧТЕНИЕ кэша (используется сразу после
        принудительной инвалидации внешних project-board-кэшей, см.
        ProjectCardService.get_legal_entities/_fetch_references_with_cache —
        у этого метода собственный кэш "my-companies" на MY_COMPANIES_CACHE_TTL,
        и внешняя инвалидация по списку суффиксов о нём не знает и не должна:
        такой список — это связь по имени, которую легко забыть при следующем
        кэше). Результат успешного запроса всё равно перезаписывает кэш, так
        что обычные вызовы без флага сразу после этого читают уже свежие данные.
        """
        cache_key = build_account_cache_key(self.account, "my-companies")
        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            response = self.client._bitrix_token.call_method(
                "crm.company.list",
                {"filter": {"IS_MY_COMPANY": "Y"}, "select": ["ID", "TITLE"], "order": {"TITLE": "ASC"}},
            )
        except Exception as exc:
            logger.warning("My companies fetch failed: %s", exc)
            return {"companies": [], "failed": True}

        rows, shape_failed = _normalize_rows(response, "crm.company.list")

        companies = []
        seen = set()
        for row in rows:
            company_id = _clean_str(row.get("ID") or row.get("id"))
            if not company_id or company_id in seen:
                continue
            seen.add(company_id)
            companies.append({
                "id": company_id,
                "name": _clean_str(row.get("TITLE") or row.get("title")) or company_id,
            })

        payload = {"companies": companies, "failed": shape_failed}
        # Та же логика, что и в search(): сбой (в т.ч. по форме ответа) не
        # кэшируем, чтобы временная кривая отдача Битрикса не заперла
        # пользователя на MY_COMPANIES_CACHE_TTL с пустым списком юрлиц.
        if not shape_failed:
            cache.set(cache_key, payload, MY_COMPANIES_CACHE_TTL)
        return payload
