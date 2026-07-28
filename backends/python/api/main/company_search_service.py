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
        return [], False
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
        query = _clean_str(query)
        limit = DEFAULT_LIMIT if limit is None else int(limit)
        limit = max(1, min(limit, MAX_LIMIT))

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
                for row in inn_response.get("result") or []:
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
            or int(response.get("total") or 0) > title_rows_count
        )
        payload = {"companies": companies[:limit], "truncated": truncated, "failed": failed}

        # Неудачный поиск не кэшируем: сбой Битрикса может быть временным, и
        # запирать пользователя на пять минут с пустым списком неправильно.
        if not failed:
            cache.set(cache_key, payload, SEARCH_CACHE_TTL)
        return payload

    def list_my_companies(self) -> Dict[str, Any]:
        """Свои юрлица — серверным фильтром IS_MY_COMPANY.

        ProjectCardService.get_legal_entities() делает то же самое, но выкачивая
        весь справочник портала и фильтруя в Python: на боевом это 465 страниц
        ради нескольких записей.
        """
        cache_key = build_account_cache_key(self.account, "my-companies")
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
