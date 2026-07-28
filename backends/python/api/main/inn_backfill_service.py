"""
Сервис дозаполнения ИНН в карточках списания времени.

Цепочка: карточка списания (элемент СП) → проект (ProjectCard по project_item_id/project_id)
→ company_id (клиент) / our_legal_entity_id (наше юрлицо) → ИНН (резолв из реквизитов,
кэш ProjectCardService.get_companies()/get_legal_entities()) → запись в поля
OUR_INN/CLIENT_INN элемента СП через crm.item.update.

Поля OUR_INN/CLIENT_INN существуют в СП, но не заполняются автоматически — этот сервис
закрывает разрыв (Спринт 2, вариант A: пишем ИНН обратно в Bitrix).
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from .project_board_service import ProjectCardService
from .project_board_shared import get_project_card_queryset

PAGE_SIZE = 50
THROTTLE_DELAY = 0.5  # сек между crm.item.update (как в timesheet_sync_service)
MAX_APPLY_BATCH = 100  # защита бэка: не более N записей за один HTTP-запрос (фронт шлёт чанками)
AUTOFILL_LIMIT = 30    # максимум авто-простановок за один синк (остальное — через UI)

# Статусы строки дозаполнения
STATUS_READY = "ready"          # все пустые поля имеют ИНН из проекта → можно проставить авто
STATUS_ATTENTION = "attention"  # проект есть, но какого-то ИНН нет → ручной ввод
STATUS_NO_PROJECT = "no_project"  # карточка не привязана к проекту → ручной ввод


# ---------- Чистые функции (тестируемые без I/O) ----------

def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_blank(value: Any) -> bool:
    """Пусто ли значение поля ИНН в карточке (None / '' / пробелы / [] )."""
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return _clean(value) == ""


def has_resolved_inn(mapping: Dict[str, str]) -> bool:
    """Есть ли в карте id -> ИНН хотя бы один реально резолвившийся ИНН.

    Отличие от простого `bool(mapping)`/пустоты словаря: словарь может быть
    непустым (ключи компаний/юрлиц из карточек проектов есть), но каждое
    значение — пустая строка, если источник карты не отдаёт ИНН вовсе.
    Именно так выглядит `_inn_maps()` после перехода ProjectCardService на
    локальную базу (Task 3 плана "справочники из локальной базы"), пока сам
    `_inn_maps()` явно не запросит полный обход портала: `bool({"C1": ""})`
    — `True`, поэтому проверка "словарь пуст" такую деградацию не ловит."""
    return any(_clean(v) for v in mapping.values())


def build_project_lookup(cards) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Строит индексы ProjectCard: по project_item_id и по project_id."""
    by_item: Dict[str, Any] = {}
    by_id: Dict[str, Any] = {}
    for card in cards:
        item_key = _clean(getattr(card, "project_item_id", ""))
        id_key = _clean(getattr(card, "project_id", ""))
        if item_key and item_key not in by_item:
            by_item[item_key] = card
        if id_key and id_key not in by_id:
            by_id[id_key] = card
    return by_item, by_id


def resolve_card_inn(card, companies_inn: Dict[str, str], legal_inn: Dict[str, str]) -> Tuple[str, str]:
    """ИНН (наш, клиента) для проекта карточки. '' если не резолвится."""
    if card is None:
        return "", ""
    our = legal_inn.get(_clean(getattr(card, "our_legal_entity_id", "")), "")
    client = companies_inn.get(_clean(getattr(card, "company_id", "")), "")
    return _clean(our), _clean(client)


def classify_row(our_blank: bool, client_blank: bool,
                 suggest_our: str, suggest_client: str,
                 has_project: bool) -> str:
    """Статус строки: можно ли проставить автоматически."""
    if not has_project:
        return STATUS_NO_PROJECT
    # для каждого ПУСТОГО поля должно быть предложенное значение
    missing_our = our_blank and not suggest_our
    missing_client = client_blank and not suggest_client
    if missing_our or missing_client:
        return STATUS_ATTENTION
    return STATUS_READY


# ---------- Сервис с I/O ----------

class InnBackfillService:
    def __init__(self, client, account, config: Optional[Dict[str, Any]] = None):
        self.client = client
        self.account = account
        self.config = config or {}
        self.entity_type_id = int(self.config.get("sp_entity_type_id") or 0)
        self.mapping: Dict[str, str] = self.config.get("fields_mapping", {}) or {}

    # --- маппинг полей СП ---
    def field(self, key: str) -> str:
        return _clean(self.mapping.get(key))

    def date_field(self) -> str:
        return self.field("data") or "CREATED_TIME"

    def ensure_inn_fields(self) -> Optional[str]:
        """Проверка, что поля ИНН созданы и замаплены. Возвращает текст ошибки или None."""
        if not self.entity_type_id:
            return "Смарт-процесс не настроен. Перейдите в Настройки и выберите смарт-процесс."
        if not self.field("our_inn") and not self.field("client_inn"):
            return ("Поля «Наш ИНН»/«ИНН клиента» не созданы в смарт-процессе списания. "
                    "Создайте их в Настройках (создание полей), затем повторите.")
        return None

    # --- чтение карточек из Bitrix ---
    def _fetch_cards(self, date_from: str, date_to: str) -> List[Dict[str, Any]]:
        field_date = self.date_field()
        select = ["id", field_date]
        for key in ("our_inn", "client_inn", "project_id", "project_item_id",
                    "sotrudnik", "id_zadachi", "title_zadach_ierarhiya", "opisanie"):
            code = self.field(key)
            if code and code not in select:
                select.append(code)

        crm_filter: Dict[str, Any] = {}
        if date_from:
            crm_filter[f">={field_date}"] = date_from
        if date_to:
            crm_filter[f"<={field_date}"] = date_to

        items: List[Dict[str, Any]] = []
        start = 0
        while True:
            response = self.client._bitrix_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": self.entity_type_id,
                    "filter": crm_filter,
                    "select": select,
                    "start": start,
                },
            )
            result = response.get("result", {}) if isinstance(response, dict) else {}
            batch = result.get("items", [])
            items.extend(batch)
            total = response.get("total", result.get("total", 0)) if isinstance(response, dict) else 0
            start += PAGE_SIZE
            if not batch or len(batch) < PAGE_SIZE or start >= total:
                break
        return items

    def _inn_maps(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Карта company_id/legal_entity_id -> ИНН для дозаполнения.

        Единственное место во всём приложении, которому оправдан явный
        полный постраничный обход справочника компаний Битрикса
        (ProjectCardService.get_full_company_directory) вместо быстрого
        get_companies() (локальная база, без ИНН — см. Task 3 плана
        "справочники из локальной базы"): это админское действие
        (Scan/Apply с экрана настроек дозаполнения ИНН), запускается
        вручную самим администратором, а не при открытии приложения и не
        на пользовательском пути (доска/meta/главный экран/резолверы
        имён — им обход запрещён, см. project_board_service.py), и ему
        по сути нужны ИНН всех компаний портала разом, а не только тех,
        что уже встречались в карточках проектов.

        "Свои" юрлица за тем же обходом — get_legal_entities() тоже не
        отдаёт ИНН (свой быстрый серверный фильтр IS_MY_COMPANY=Y, без
        обхода и без реквизитов), поэтому вместо отдельного вызова
        отбираем их из ТОГО ЖЕ полного справочника по признаку
        is_my_company: это поле есть только в результате обхода Битрикса
        (_fetch_companies_live), в локальной проекции карточек его нет.
        """
        board = ProjectCardService(self.client, self.account)
        directory = board.get_full_company_directory()
        companies = {_clean(c.get("id")): _clean(c.get("inn")) for c in directory if c.get("id")}
        legal = {
            _clean(c.get("id")): _clean(c.get("inn"))
            for c in directory
            if c.get("id") and c.get("is_my_company")
        }
        return companies, legal

    def _resolve_employee_names(self, ids: List[str]) -> Dict[str, str]:
        try:
            from .services import BitrixDataService
            return BitrixDataService(self.client, self.config, self.account).fetch_users(ids) or {}
        except Exception:
            return {}

    # --- SCAN ---
    def scan(self, date_from: str, date_to: str,
             project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        cards_qs = get_project_card_queryset(self.account)
        by_item, by_id = build_project_lookup(cards_qs)
        companies_inn, legal_inn = self._inn_maps()

        f_our, f_client = self.field("our_inn"), self.field("client_inn")
        f_pid, f_pitem = self.field("project_id"), self.field("project_item_id")
        f_emp, f_task = self.field("sotrudnik"), self.field("title_zadach_ierarhiya")
        f_desc, f_date = self.field("opisanie"), self.date_field()
        project_filter = {str(p) for p in (project_ids or []) if str(p).strip()}

        raw = self._fetch_cards(date_from, date_to)

        kpi = {"total": 0, "without_inn": 0, "resolvable": 0, "attention": 0}
        emp_ids: set = set()
        rows: List[Dict[str, Any]] = []
        with_project = 0

        for it in raw:
            kpi["total"] += 1
            cur_our = it.get(f_our) if f_our else None
            cur_client = it.get(f_client) if f_client else None
            our_blank, client_blank = is_blank(cur_our), is_blank(cur_client)
            if not (our_blank or client_blank):
                continue
            kpi["without_inn"] += 1

            proj_item = _clean(it.get(f_pitem)) if f_pitem else ""
            proj_id = _clean(it.get(f_pid)) if f_pid else ""
            card = by_item.get(proj_item) or by_id.get(proj_id)
            if project_filter and (not card or _clean(getattr(card, "project_id", "")) not in project_filter):
                continue
            if card is not None:
                with_project += 1

            suggest_our, suggest_client = resolve_card_inn(card, companies_inn, legal_inn)
            suggest_our = suggest_our if our_blank else ""
            suggest_client = suggest_client if client_blank else ""
            status = classify_row(our_blank, client_blank, suggest_our, suggest_client, card is not None)
            if status == STATUS_READY:
                kpi["resolvable"] += 1
            else:
                kpi["attention"] += 1

            emp_val = _clean(it.get(f_emp)) if f_emp else ""
            if emp_val:
                emp_ids.add(emp_val)
            task_title = it.get(f_task) if f_task else None
            if isinstance(task_title, list):
                task_title = task_title[-1] if task_title else ""

            rows.append({
                "bitrix_id": it.get("id") or it.get("ID"),
                "date": it.get(f_date),
                "employee_id": emp_val,
                "employee_name": "",
                "task": _clean(task_title) or _clean(it.get(f_desc) if f_desc else ""),
                "project_id": _clean(getattr(card, "project_id", "")) if card else proj_id,
                "project_name": (_clean(getattr(card, "project_name", "")) if card else "") or "Без проекта",
                "our_blank": our_blank,
                "client_blank": client_blank,
                "suggest_our_inn": suggest_our,
                "suggest_client_inn": suggest_client,
                "status": status,
            })

        names = self._resolve_employee_names(list(emp_ids)) if emp_ids else {}
        for r in rows:
            r["employee_name"] = _clean(names.get(r["employee_id"])) or r["employee_id"]

        # группировка по project_id (одноимённые проекты не схлопываются; "без проекта" — отдельный ключ)
        groups: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            gkey = r["project_id"] or "__no_project__"
            grp = groups.setdefault(gkey, {
                "key": gkey,
                "project_id": r["project_id"],
                "project_name": r["project_name"],
                "our_inn": r["suggest_our_inn"],
                "client_inn": r["suggest_client_inn"],
                "count": 0,
                "rows": [],
            })
            grp["count"] += 1
            grp["our_inn"] = grp["our_inn"] or r["suggest_our_inn"]
            grp["client_inn"] = grp["client_inn"] or r["suggest_client_inn"]
            grp["rows"].append(r)

        # деградация резолва: карточки с проектами есть, но ни одного ИНН из реквизитов не получено.
        # has_resolved_inn(), а не "словарь непуст": после Task 3 плана companies_inn/legal_inn
        # всегда содержат ключи компаний из карточек, даже когда ИНН для них не резолвился
        # (значения — пустые строки) — простая проверка bool(mapping) такую деградацию не ловит.
        warning = None
        if with_project > 0 and not (has_resolved_inn(companies_inn) or has_resolved_inn(legal_inn)):
            warning = ("Не удалось получить ИНН из реквизитов Bitrix (crm.requisite.list). "
                       "Проверьте реквизиты компаний/юрлиц или повторите позже.")

        return {"kpi": kpi, "groups": list(groups.values()), "warning": warning}

    # --- APPLY ---
    def apply(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """items: [{bitrix_id, our_inn?, client_inn?}]. Пишет только непустые значения.

        Защита от таймаута: не более MAX_APPLY_BATCH за вызов; лишнее отбрасывается
        (truncated=True), фронт обязан слать чанками.

        Батчинг: до 50 crm.item.update за один HTTP-запрос (call_batch).
        При исключении вызова call_batch — фолбэк на пер-элементный crm.item.update для чанка.
        Пауза THROTTLE_DELAY делается только МЕЖДУ чанками (не между элементами).
        """
        items = list(items or [])
        truncated = len(items) > MAX_APPLY_BATCH
        if truncated:
            items = items[:MAX_APPLY_BATCH]

        f_our, f_client = self.field("our_inn"), self.field("client_inn")
        updated = 0
        failed: List[Dict[str, Any]] = []

        # --- 1. Предобработка: собираем валидные (bitrix_id, fields) ---
        valid: List[tuple] = []
        for item in items:
            bitrix_id = item.get("bitrix_id") or item.get("id")
            fields: Dict[str, Any] = {}
            our_inn = _clean(item.get("our_inn"))
            client_inn = _clean(item.get("client_inn"))
            if our_inn and f_our:
                fields[f_our] = our_inn
            if client_inn and f_client:
                fields[f_client] = client_inn
            if not bitrix_id or not fields:
                continue
            valid.append((bitrix_id, fields))

        # --- 2. Разбиваем на чанки по 50 и батчим ---
        CHUNK_SIZE = 50
        chunks = [valid[i: i + CHUNK_SIZE] for i in range(0, len(valid), CHUNK_SIZE)]

        for chunk_idx, chunk in enumerate(chunks):
            # Пауза между чанками (не перед первым)
            if chunk_idx > 0:
                time.sleep(THROTTLE_DELAY)

            methods = {
                str(bitrix_id): (
                    "crm.item.update",
                    {"entityTypeId": self.entity_type_id, "id": int(bitrix_id), "fields": flds},
                )
                for bitrix_id, flds in chunk
            }

            try:
                resp = self.client._bitrix_token.call_batch(methods, halt=False)
                # Форма ответа батча: resp["result"]["result"][key] — успех,
                # resp["result"]["result_error"][key] — ошибка (подтверждено по SDK и timesheet_sync_service.py)
                result_map = resp.get("result", {})
                successes = result_map.get("result", {}) or {}
                errors = result_map.get("result_error", {}) or {}
                for bitrix_id, _ in chunk:
                    key = str(bitrix_id)
                    if key in errors:
                        err = errors[key]
                        failed.append({
                            "bitrix_id": bitrix_id,
                            "error": str(err) if not isinstance(err, str) else err,
                        })
                    else:
                        # Если ключа нет ни в errors, ни в successes — считаем успехом:
                        # Bitrix может вернуть пустой result для успешного update
                        updated += 1

            except Exception as exc:  # noqa: BLE001 — фолбэк на пер-элементный update
                logger.warning(
                    "call_batch failed for chunk %d/%d (%d items): %s. "
                    "Falling back to per-element crm.item.update.",
                    chunk_idx + 1, len(chunks), len(chunk), exc,
                )
                for bitrix_id, flds in chunk:
                    try:
                        self.client._bitrix_token.call_method(
                            "crm.item.update",
                            {"entityTypeId": self.entity_type_id, "id": int(bitrix_id), "fields": flds},
                        )
                        updated += 1
                    except Exception as inner_exc:  # noqa: BLE001
                        failed.append({"bitrix_id": bitrix_id, "error": str(inner_exc)})

        return {"status": "success", "updated": updated, "failed": failed, "truncated": truncated}

    # --- AUTOFILL (вызывается из синхронизации для новых карточек) ---
    def autofill(self, cards_info: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Резолвит ИНН из проекта для новых карточек и пишет его (поля заведомо пусты).

        cards_info: [{bitrix_id, project_id, project_item_id}]. Ограничено AUTOFILL_LIMIT
        за один вызов — остальное пользователь дозаполнит через UI.
        """
        if not cards_info:
            return {"updated": 0, "resolved": 0, "over_limit": 0}
        if self.ensure_inn_fields():
            return {"updated": 0, "resolved": 0, "over_limit": 0, "skipped": "inn_fields_not_configured"}

        by_item, by_id = build_project_lookup(get_project_card_queryset(self.account))
        companies_inn, legal_inn = self._inn_maps()

        items: List[Dict[str, Any]] = []
        for ci in cards_info:
            card = by_item.get(_clean(ci.get("project_item_id"))) or by_id.get(_clean(ci.get("project_id")))
            our, client = resolve_card_inn(card, companies_inn, legal_inn)
            if our or client:
                items.append({"bitrix_id": ci.get("bitrix_id"), "our_inn": our, "client_inn": client})

        over_limit = max(0, len(items) - AUTOFILL_LIMIT)
        items = items[:AUTOFILL_LIMIT]
        res = self.apply(items) if items else {"updated": 0}
        return {"updated": res.get("updated", 0), "resolved": len(items), "over_limit": over_limit}

    # --- PROJECT_ITEMS ---
    def project_items(self, project_id: str, date_from: str, date_to: str,
                      our_inn: str, client_inn: str, overwrite: bool) -> Dict[str, Any]:
        """Резолвит карточки проекта за период и формирует items для простановки.
        overwrite=False -> только пустые поля; True -> перезаписать непустые."""
        our_inn = _clean(our_inn)
        client_inn = _clean(client_inn)
        target = _clean(project_id)
        raw = self._fetch_cards(date_from, date_to)
        by_item, by_id = build_project_lookup(get_project_card_queryset(self.account))
        f_our, f_client = self.field("our_inn"), self.field("client_inn")
        f_pid, f_pitem = self.field("project_id"), self.field("project_item_id")
        items: List[Dict[str, Any]] = []
        for it in raw:
            proj_item = _clean(it.get(f_pitem)) if f_pitem else ""
            proj_id_v = _clean(it.get(f_pid)) if f_pid else ""
            card = by_item.get(proj_item) or by_id.get(proj_id_v)
            card_pid = _clean(getattr(card, "project_id", "")) if card else proj_id_v
            if card_pid != target:
                continue
            our_blank = is_blank(it.get(f_our)) if f_our else True
            client_blank = is_blank(it.get(f_client)) if f_client else True
            entry: Dict[str, Any] = {"bitrix_id": it.get("id") or it.get("ID")}
            if our_inn and (overwrite or our_blank):
                entry["our_inn"] = our_inn
            if client_inn and (overwrite or client_blank):
                entry["client_inn"] = client_inn
            if entry.get("our_inn") or entry.get("client_inn"):
                items.append(entry)
        return {"items": items, "total": len(items)}

    # --- PROJECTS_HEALTH ---
    def projects_health(self) -> Dict[str, Any]:
        """Список проектов, которым не хватает данных для ИНН."""
        companies_inn, legal_inn = self._inn_maps()
        out: List[Dict[str, Any]] = []
        for card in get_project_card_queryset(self.account):
            company_id = _clean(getattr(card, "company_id", ""))
            legal_id = _clean(getattr(card, "our_legal_entity_id", ""))
            client_inn = companies_inn.get(company_id, "")
            our_inn = legal_inn.get(legal_id, "")
            has_company = bool(company_id)
            has_legal = bool(legal_id)
            if has_company and has_legal and client_inn and our_inn:
                continue
            out.append({
                "project_id": _clean(getattr(card, "project_id", "")),
                "project_name": _clean(getattr(card, "project_name", "")) or "Без названия",
                "has_company": has_company,
                "has_legal_entity": has_legal,
                "client_inn": _clean(client_inn),
                "our_inn": _clean(our_inn),
            })
        return {"projects": out}
