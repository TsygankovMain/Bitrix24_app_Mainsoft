"""Оркестратор кнопки «Создать проект»: компания -> группа в Задачах ->
карточка смарт-процесса.

Шаги идут строго по порядку, потому что карточка ссылается на первые две
сущности. Каждый шаг идемпотентен: сначала ищет, потом создаёт, — чтобы
повторное нажатие не плодило дубли. Больше одного совпадения по названию не
разрешается автоматически: возвращается ambiguous со списком кандидатов, иначе
можно молча привязаться к чужому одноимённому проекту.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client
from django.core.cache import cache
from django.utils import timezone

from .configuration_service import ConfigurationService
from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService
from .project_board_shared import build_account_cache_key, invalidate_project_runtime_caches
from .project_creation_defaults import ResolvedProjectFields, resolve_project_fields
from .tenant_scoping import scope_to_tenant
from .utils.decorators.sync_lock import SyncLockBusy, account_sync_lock

logger = logging.getLogger(__name__)

# ENTITY_TYPE_ID реквизита для компаний — то же значение 4, что и везде в
# проекте для crm.company/crm.requisite (company_search_service.py,
# project_board_service.py). Отдельная константа здесь просто даёт имя
# магическому числу в новых crm.requisite.* вызовах этого модуля.
REQUISITE_ENTITY_TYPE_ID = 4
# Шаблоны реквизитов меняются редко (inn-brief.md) — кэшируем список надолго,
# как MY_COMPANIES_CACHE_TTL в company_search_service.py (тоже "редко
# меняющийся" справочник). Отрицательный результат (шаблонов нет / сбой) не
# кэшируется вовсе — см. докстринг _get_default_requisite_preset_id.
REQUISITE_PRESET_CACHE_TTL = 60 * 60 * 6


@dataclass
class StepResult:
    status: str
    id: Optional[str] = None
    name: str = ""
    candidates: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None
    # Заполняется ТОЛЬКО когда ensure_company нашёл компанию по ИНН под ДРУГИМ
    # названием, чем ввёл сотрудник (см. докстринг ensure_company) — исходное
    # введённое имя, для явного предупреждения на фронте: "компания с таким
    # ИНН уже есть под названием «<name>»". Поле "name" в этом случае несёт
    # НАЙДЕННОЕ (настоящее) название, как и во всех остальных статусах — эта
    # пара полей нарочно не смешивается в один текст ошибки (inn-brief.md:
    # "поле в StepResult заведи явное, не прячь в тексте ошибки").
    entered_name: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        # list(...), а не self.candidates напрямую: create() подставляет один
        # и тот же экземпляр StepResult(status="skipped") сразу в четыре ключа
        # ответа (company/requisite/group/card) — без копии все четыре получили
        # бы ссылку на один список, и правка candidates одного шага тихо
        # портила бы остальные (ревью фикс-раунда задачи 5).
        return {
            "status": self.status,
            "id": self.id,
            "name": self.name,
            "candidates": list(self.candidates),
            "error": self.error,
            "entered_name": self.entered_name,
        }


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_rows(response: Any) -> Tuple[List[Dict[str, Any]], bool]:
    """Достаёт список записей из ответа Битрикса, различая ноль найденных от ошибки разбора.

    Возвращает кортеж (rows, parsed_ok):
    - rows: список распарсенных записей (может быть пусто)
    - parsed_ok: True если результат в ожидаемой форме (список, полностью состоящий из словарей
      или пустой), False если форма неожиданна или список содержит примесь не-словарей

    Битрикс отдаёт result то списком, то словарём с items, а при нештатных
    ситуациях — чем угодно. Нужно различать:
    - result=[] → ноль найденных (честный ответ), можем создавать (parsed_ok=True)
    - result={...} без items → подозрительно, ошибка разбора (parsed_ok=False)
    - result=[{...}, {...}] все словари → нормально (parsed_ok=True)
    - result=[{...}, "garbage"] смешанный список → примесь (parsed_ok=False), мусор может быть испорченным совпадением
    - result=["str"] список строк → ошибка разбора (parsed_ok=False)

    Это нужно для следующих шагов (группа, карточка), где та же дилемма.
    """
    if not isinstance(response, dict):
        return [], False

    result = response.get("result")
    if result is None:
        return [], False

    # Если result — словарь, пытаемся достать items или вложенный result
    if isinstance(result, dict):
        items = result.get("items")
        if items is None:
            items = result.get("result")
        # Если items всё равно не найден, это подозрительный ответ
        if items is None:
            return [], False
    else:
        items = result

    # Если items не список — ошибка разбора
    if not isinstance(items, list):
        return [], False

    # Если список пуст — это честный ответ «ничего не найдено»
    if len(items) == 0:
        return [], True

    # Фильтруем элементы, которые не словари
    valid_items = [item for item in items if isinstance(item, dict)]

    # Если были потери (примесь не-словарей в исходном списке) — это ошибка
    # Мусор может быть испорченным совпадением, не можем молча его выбросить
    if len(valid_items) < len(items):
        return [], False

    return valid_items, True


def _extract_created_id(response: Any) -> Optional[str]:
    """Извлекает идентификатор созданной записи из ответа метода *.add.

    Битрикс отвечает по-разному в зависимости от метода:
    - crm.company.add, sonet_group.create -> {"result": 77}
    - crm.item.add (смарт-процесс)        -> {"result": {"item": {"id": 501}}}
    - встречается и                          {"result": {"id": 501}}

    Возвращает None если ответ не содержит идентификатора в валидной форме.
    Вызывающий код превращает None в status="error".
    """
    if not isinstance(response, dict):
        return None

    result = response.get("result")
    if result is None:
        return None

    # Форма 1: скалярный ID (целое число или строка с цифрами)
    if isinstance(result, int):
        return str(result)
    if isinstance(result, str) and result.strip() and result.strip().isdigit():
        return result.strip()

    # Форма 2: вложенный объект с "id" (может быть {"item": {"id": 501}} или {"id": 501})
    if isinstance(result, dict):
        # Пытаемся извлечь "id" прямо из result
        if "id" in result:
            id_value = result["id"]
            if isinstance(id_value, int):
                return str(id_value)
            if isinstance(id_value, str) and id_value.strip() and id_value.strip().isdigit():
                return id_value.strip()

        # Пытаемся найти объект с "id" (например, {"item": {"id": 501}})
        for key, value in result.items():
            if isinstance(value, dict) and "id" in value:
                id_value = value["id"]
                if isinstance(id_value, int):
                    return str(id_value)
                if isinstance(id_value, str) and id_value.strip() and id_value.strip().isdigit():
                    return id_value.strip()

    return None


def _is_default_preset(preset: Dict[str, Any]) -> bool:
    """True, если элемент crm.requisite.preset.list помечен шаблоном "по
    умолчанию".

    Название и форма поля-маркера у этого метода нигде в проекте раньше не
    встречались (inn-brief.md: до этой задачи crm.requisite.add и
    crm.requisite.preset.list не вызывались вовсе, есть только .list на
    чтение). Проверяем сразу несколько правдоподобных имён поля и несколько
    кодировок "истины" — тот же приём, каким остальной код проекта переживает
    разные регистры полей Битрикса (RQ_INN/rqInn, ENTITY_ID/entityId и т.д.,
    см. company_search_service.py/project_board_service.py). Если ни один
    вариант не сработал — просто не дефолтный: вызывающий код
    (_get_default_requisite_preset_id) возьмёт первый элемент списка, как и
    предписывает inn-brief.md ("если шаблонов несколько — брать помеченный
    по умолчанию, иначе первый") — это осознанный отказ угадывать
    непроверенное имя поля, а не пропущенный случай.
    """
    for key in ("IS_DEFAULT", "isDefault", "DEFAULT", "default"):
        if key not in preset:
            continue
        value = preset[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str) and value.strip().upper() in {"Y", "YES", "TRUE", "1"}:
            return True
        return False
    return False


class ProjectCreationService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.client._bitrix_token.call_method(method, params)

    def _resolve_company_title(self, company_id: str) -> Optional[str]:
        """Достаёт TITLE компании по id — нужно, чтобы показать НАСТОЯЩЕЕ
        название найденной по ИНН компании (см. ensure_company), а не то,
        что ввёл человек: crm.requisite.list отдаёт ENTITY_ID, но не TITLE.

        Три исхода, различимые без отдельного флага "ok" — `None` уже не
        пересекается с пустой строкой:
        - `None` — ответ неразобираем или сбой сети (вызывающий код
          превращает это в status="error");
        - `""` — компании с таким id нет (осиротевший реквизит: компанию
          удалили, реквизит остался) — вызывающий код трактует это как
          "не найдена", а не как ошибку;
        - непустая строка — настоящее название компании.
        """
        try:
            response = self._call(
                "crm.company.list",
                {"filter": {"ID": self._to_bitrix_id(company_id)}, "select": ["ID", "TITLE"]},
            )
            rows, parsed_ok = _extract_rows(response)
        except Exception as exc:
            logger.warning("ensure_company: company lookup by id failed: %s", exc)
            return None
        if not parsed_ok:
            logger.warning("ensure_company: company lookup by id returned unexpected format")
            return None
        if not rows:
            return ""
        return _clean_str(rows[0].get("TITLE") or rows[0].get("title"))

    def _find_company_by_inn(self, inn: str, entered_company_name: str) -> Optional[StepResult]:
        """Точный поиск компании по ИНН через реквизит (RQ_INN, не %RQ_INN —
        подстрочный фильтр отдал бы чужую компанию).

        Возвращает `None`, если ни одного совпадения нет: это НЕ ошибка, а
        сигнал вызывающему коду (ensure_company) продолжить обычным поиском
        по названию — реквизита с таким ИНН пока никто не заводил. Любой
        другой исход (нашли ровно одну компанию, нашли несколько, сбой сети
        или неразбираемый ответ) — уже готовый StepResult, который
        ensure_company возвращает как есть, дальше не разбираясь.
        """
        try:
            response = self._call(
                "crm.requisite.list",
                {
                    "filter": {"ENTITY_TYPE_ID": REQUISITE_ENTITY_TYPE_ID, "RQ_INN": inn},
                    "select": ["ENTITY_ID", "RQ_INN"],
                },
            )
            rows, parsed_ok = _extract_rows(response)
        except Exception as exc:
            logger.warning("ensure_company: crm.requisite.list (by INN) failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти компанию по ИНН: {exc}")
        if not parsed_ok:
            logger.warning("ensure_company: crm.requisite.list (by INN) returned unexpected format")
            return StepResult(status="error", error="Битрикс вернул ответ в неожиданном формате при поиске по ИНН.")

        entity_ids: List[str] = []
        seen_ids = set()
        for row in rows:
            entity_id = _clean_str(row.get("ENTITY_ID") or row.get("entityId"))
            if entity_id and entity_id not in seen_ids:
                seen_ids.add(entity_id)
                entity_ids.append(entity_id)

        inn_matches: List[Dict[str, str]] = []
        for entity_id in entity_ids:
            title = self._resolve_company_title(entity_id)
            if title is None:
                return StepResult(status="error", error="Не удалось получить данные компании по ИНН.")
            if not title:
                # Осиротевший реквизит (компания удалена) — не совпадение,
                # пропускаем и идём дальше искать по названию.
                continue
            inn_matches.append({"id": entity_id, "name": title})

        if len(inn_matches) > 1:
            return StepResult(status="ambiguous", candidates=inn_matches)
        if len(inn_matches) == 1:
            match = inn_matches[0]
            entered_name = entered_company_name if entered_company_name != match["name"] else None
            return StepResult(
                status="found", id=match["id"], name=match["name"] or entered_company_name, entered_name=entered_name
            )
        return None

    def ensure_company(self, company_id: Optional[str], company_name: str, inn: Optional[str] = None) -> StepResult:
        """Шаг компании. Передан id — используем как есть, поиска не делаем,
        ИНН при этом не смотрим вовсе: для уже выбранной из поиска компании
        реквизиты не наша забота (решение заказчика 29.07.2026, inn-brief.md,
        раздел "Решение") — она либо уже имеет реквизит, либо нет.

        Иначе (создание НОВОЙ компании, inn обычно уже проверен на входе
        resolve_project_fields — см. её докстринг, но эта функция не
        полагается на это и просто использует inn как есть, пустая строка
        от невалидного ИНН здесь безопасна — ниже просто пропустит поиск по
        ИНН) — порядок ровно как в inn-brief.md:

        1. Точный поиск по ИНН (crm.requisite.list, RQ_INN) — ИНН настоящий
           идентификатор юрлица, значит имеет приоритет над текстом названия.
        2. Точный поиск по названию (=TITLE, как раньше).
        3. Создание (crm.company.add) — реквизит создаётся ОТДЕЛЬНЫМ шагом
           (ensure_requisite), не здесь.

        Расхождение имени: если по ИНН нашлась компания с ДРУГИМ названием,
        берём найденную (создание второй компании с тем же ИНН недопустимо —
        порча данных CRM клиента) и заполняем entered_name — то, что ввёл
        человек, — чтобы фронт мог явно предупредить, а не молча подменить
        название. StepResult.name при этом несёт НАСТОЯЩЕЕ (найденное)
        название, как и во всех остальных статусах.
        """
        company_id = _clean_str(company_id)
        company_name = _clean_str(company_name)
        inn = _clean_str(inn)

        if company_id:
            return StepResult(status="found", id=company_id, name=company_name)

        if not company_name:
            return StepResult(status="error", error="Не указана компания.")

        if inn:
            inn_result = self._find_company_by_inn(inn, company_name)
            if inn_result is not None:
                return inn_result
            # None -> реквизита с этим ИНН нет ни у кого — идём дальше, к
            # поиску по названию (см. докстринг _find_company_by_inn).

        # Шаг 2: поиск по точному названию
        try:
            response = self._call(
                "crm.company.list",
                {"filter": {"=TITLE": company_name}, "select": ["ID", "TITLE"]},
            )
            rows, parsed_ok = _extract_rows(response)
            if not parsed_ok:
                logger.warning("ensure_company: crm.company.list returned unexpected format")
                return StepResult(
                    status="error",
                    error="Битрикс вернул ответ в неожиданном формате.",
                )
        except Exception as exc:
            logger.warning("ensure_company: crm.company.list failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти компанию: {exc}")

        try:
            matches = [
                {"id": _clean_str(row.get("ID")), "name": _clean_str(row.get("TITLE"))}
                for row in rows
                if _clean_str(row.get("ID"))
            ]
        except Exception as exc:
            logger.warning("ensure_company: failed to parse company list response: %s", exc)
            return StepResult(status="error", error=f"Ошибка разбора ответа: {exc}")

        if len(matches) == 1:
            return StepResult(status="found", id=matches[0]["id"], name=matches[0]["name"])
        if len(matches) > 1:
            return StepResult(status="ambiguous", candidates=matches)

        # Шаг 3: создание компании, если не найдена ни по ИНН, ни по названию
        try:
            created = self._call("crm.company.add", {"fields": {"TITLE": company_name}})
            created_id = _extract_created_id(created)
        except Exception as exc:
            logger.warning("ensure_company: crm.company.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать компанию: {exc}")

        if not created_id:
            return StepResult(
                status="error",
                error="Битрикс не вернул валидный идентификатор компании.",
            )

        return StepResult(status="created", id=created_id, name=company_name)

    def _get_default_requisite_preset_id(self) -> Optional[str]:
        """Шаблон реквизитов для компаний (ENTITY_TYPE_ID=4). Несколько —
        берём помеченный по умолчанию, иначе первый (inn-brief.md). Список
        кэшируется — "меняется редко" (там же); отрицательный результат
        (шаблонов нет, сбой сети, неразбираемый ответ) НЕ кэшируется, чтобы
        временный сбой или ещё не настроенный на портале шаблон не запирали
        создание проектов на REQUISITE_PRESET_CACHE_TTL (6 часов) — тот же
        принцип, что и в company_search_service.py/project_board_service.py
        ("неудачный поиск не кэшируем").
        """
        cache_key = build_account_cache_key(self.account, "requisite-presets")
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            response = self._call(
                "crm.requisite.preset.list",
                {
                    "filter": {"ENTITY_TYPE_ID": REQUISITE_ENTITY_TYPE_ID},
                    "select": ["ID", "NAME", "ENTITY_TYPE_ID", "IS_DEFAULT"],
                },
            )
            rows, parsed_ok = _extract_rows(response)
        except Exception as exc:
            logger.warning("_get_default_requisite_preset_id: crm.requisite.preset.list failed: %s", exc)
            return None
        if not parsed_ok:
            logger.warning("_get_default_requisite_preset_id: crm.requisite.preset.list returned unexpected format")
            return None

        # Серверный filter ENTITY_TYPE_ID не обязан быть последней инстанцией
        # (см. докстринг _normalize_rows в company_search_service.py про
        # недоверие форме ответа Битрикса вообще) — перепроверяем на
        # клиенте, как и везде в проекте.
        presets = [
            row for row in rows
            if _clean_str(row.get("ENTITY_TYPE_ID")) == str(REQUISITE_ENTITY_TYPE_ID)
        ]
        if not presets:
            return None

        preset_id = ""
        for preset in presets:
            if _is_default_preset(preset):
                preset_id = _clean_str(preset.get("ID") or preset.get("id"))
                break
        if not preset_id:
            preset_id = _clean_str(presets[0].get("ID") or presets[0].get("id"))
        if not preset_id:
            return None

        cache.set(cache_key, preset_id, REQUISITE_PRESET_CACHE_TTL)
        return preset_id

    def ensure_requisite(self, company_id: str, company_name: str, inn: str) -> StepResult:
        """Шаг реквизита (ИНН) — вызывается ТОЛЬКО для новой компании: при
        company_id, пришедшем от клиента (существующая компания из поиска),
        create() передаёт сюда fields.inn == "" (см. докстринг
        resolve_project_fields) — этот шаг тут же возвращает "skipped", ИНН
        уже выбранной компании не наша забота (inn-brief.md, "Решение").

        Идемпотентен так же, как остальные шаги: сначала смотрит, нет ли уже
        у ЭТОЙ компании реквизита с ЭТИМ ИНН, и только тогда создаёт. Это
        закрывает повтор после частичного отказа "компания создана, реквизит
        нет" (см. create()/_create_under_lock): второй вызов найдёт компанию
        по точному названию (шаг 2 ensure_company, раз по ИНН реквизита ещё
        нет никому) и обязан дописать реквизит, а не развести руками. Другой
        реквизит той же компании (другой ИНН — например, старая ошибка
        данных) не блокирует создание: проверяем именно ЭТОТ ИНН у ЭТОЙ
        компании, а не факт "хоть что-то есть".

        Отсутствие шаблона реквизитов на портале — не повод трогать компанию:
        она остаётся, а этот шаг возвращает status="error" с понятной
        причиной. Придумывать PRESET_ID нельзя — угаданный шаблон может
        привязать реквизит к чужой форме (ИП вместо юрлица, другая страна) и
        испортить данные в CRM клиента сильнее, чем отсутствующий ИНН.
        """
        company_id = _clean_str(company_id)
        company_name = _clean_str(company_name)
        inn = _clean_str(inn)

        if not company_id or not inn:
            return StepResult(status="skipped")

        # Идемпотентность: у компании уже есть реквизит с этим ИНН?
        try:
            response = self._call(
                "crm.requisite.list",
                {
                    "filter": {
                        "ENTITY_TYPE_ID": REQUISITE_ENTITY_TYPE_ID,
                        "ENTITY_ID": self._to_bitrix_id(company_id),
                    },
                    "select": ["ID", "ENTITY_ID", "RQ_INN"],
                },
            )
            rows, parsed_ok = _extract_rows(response)
        except Exception as exc:
            logger.warning("ensure_requisite: crm.requisite.list failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось проверить реквизиты компании: {exc}")
        if not parsed_ok:
            logger.warning("ensure_requisite: crm.requisite.list returned unexpected format")
            return StepResult(status="error", error="Битрикс вернул ответ в неожиданном формате при проверке реквизита.")

        for row in rows:
            existing_inn = _clean_str(row.get("RQ_INN") or row.get("rqInn"))
            if existing_inn == inn:
                existing_id = _clean_str(row.get("ID") or row.get("id"))
                return StepResult(status="found", id=existing_id, name=inn)

        preset_id = self._get_default_requisite_preset_id()
        if not preset_id:
            return StepResult(
                status="error",
                error=(
                    "На портале не настроен шаблон реквизитов для компаний — "
                    "ИНН не сохранён. Обратитесь к администратору Битрикс24."
                ),
            )

        try:
            created = self._call(
                "crm.requisite.add",
                {
                    "fields": {
                        "ENTITY_TYPE_ID": REQUISITE_ENTITY_TYPE_ID,
                        "ENTITY_ID": self._to_bitrix_id(company_id),
                        "PRESET_ID": self._to_bitrix_id(preset_id),
                        # NAME обязателен у crm.requisite.add и не имеет
                        # отдельного поля в форме — используем название
                        # компании, как это по умолчанию делает сама форма
                        # реквизитов в интерфейсе Битрикса.
                        "NAME": company_name or inn,
                        "RQ_INN": inn,
                    }
                },
            )
            created_id = _extract_created_id(created)
        except Exception as exc:
            logger.warning("ensure_requisite: crm.requisite.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать реквизит: {exc}")

        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор реквизита.")

        return StepResult(status="created", id=created_id, name=inn)

    def ensure_group(self, group_name: str) -> StepResult:
        """Шаг 3: проект/группа в Задачах (после компании и её реквизита —
        см. докстринг create()).

        sonet_group.get фильтрует по подстроке, поэтому совпадением считаем
        только точное равенство имени — иначе «Портал Ромашка» подцепит
        «Портал Ромашка 2» и списания уедут в чужой проект.

        Группа создаётся под токеном текущего сотрудника, он же становится
        владельцем; отдельно владельца не назначаем и участников не добавляем.
        """
        group_name = _clean_str(group_name)
        if not group_name:
            return StepResult(status="error", error="Не указано название проекта.")

        try:
            response = self._call(
                "sonet_group.get",
                {"FILTER": {"NAME": group_name}, "SELECT": ["ID", "NAME"]},
            )
        except Exception as exc:
            logger.warning("ensure_group: sonet_group.get failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти проект: {exc}")

        # _extract_rows, а не response.get("result") напрямую: разбор ответа
        # обязан быть таким же защищённым, как сам вызов. Шаг оркестратора не
        # имеет права бросить исключение — иначе следующие шаги не выполнятся
        # и вызывающий код не соберёт частичный результат (заведено в Task 2).
        rows, parsed_ok = _extract_rows(response)
        if not parsed_ok:
            # Ответ непонятен. Создавать нельзя: если совпадение там было, в
            # Задачах навсегда останется дубль проекта — мы ничего не удаляем.
            return StepResult(status="error", error="Битрикс вернул ответ неожиданного вида при поиске проекта.")

        matches = [
            {"id": _clean_str(row.get("ID")), "name": _clean_str(row.get("NAME"))}
            for row in rows
            if _clean_str(row.get("ID")) and _clean_str(row.get("NAME")) == group_name
        ]

        if len(matches) == 1:
            return StepResult(status="found", id=matches[0]["id"], name=matches[0]["name"])
        if len(matches) > 1:
            return StepResult(status="ambiguous", candidates=matches)

        try:
            created = self._call(
                "sonet_group.create",
                {"NAME": group_name, "PROJECT": "Y", "VISIBLE": "Y", "OPENED": "N"},
            )
        except Exception as exc:
            logger.warning("ensure_group: sonet_group.create failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать проект: {exc}")

        # _extract_created_id (заведён в Task 2) переживает created=None и
        # result, оказавшийся словарём или списком: без него _clean_str тихо
        # положил бы в id строку вида "{'ID': 44}" со статусом "created".
        created_id = _clean_str(_extract_created_id(created))
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор проекта.")

        return StepResult(status="created", id=created_id, name=group_name)

    @staticmethod
    def _to_bitrix_id(value: Any) -> Any:
        """Битрикс ждёт числовые id числами; нечисловое отдаём как есть."""
        text = _clean_str(value)
        return int(text) if text.isdigit() else (text or None)

    def build_card_fields(
        self, fields: ResolvedProjectFields, group_id: str, mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Собирает поля crm.item.add по маппингу портала.

        Ключи те же, что у ProjectCardService._build_project_spa_update_fields —
        маппинг общий. Незамапленное и пустое не пишем: на разных порталах набор
        настроенных полей разный, а пустое значение затрёт то, что уже есть.
        """
        values = {
            "title": fields.project_name,
            "bitrix_group_id": self._to_bitrix_id(group_id),
            "stage_id": fields.stage,
            "company_id": self._to_bitrix_id(fields.company_id),
            "our_legal_entity_id": self._to_bitrix_id(fields.our_legal_entity_id),
            "curator_id": self._to_bitrix_id(fields.curator_user_id),
            "hourly_rate": fields.hourly_rate,
            "project_hours_budget": fields.project_hours_budget,
            "start_date": fields.project_start_date.isoformat() if fields.project_start_date else None,
            "finish_date": fields.project_end_date.isoformat() if fields.project_end_date else None,
            "is_support": "Y" if fields.is_support else "N",
        }

        built: Dict[str, Any] = {}
        for mapping_key, value in values.items():
            field_code = _clean_str((mapping or {}).get(mapping_key))
            if not field_code or value in (None, ""):
                continue
            built[field_code] = value
        return built

    def ensure_card(
        self,
        fields: ResolvedProjectFields,
        group_id: str,
        *,
        entity_type_id: int,
        mapping: Dict[str, Any],
    ) -> StepResult:
        """Шаг 4: карточка смарт-процесса, связанная с группой."""
        if not entity_type_id or not mapping:
            return StepResult(
                status="skipped",
                error="Смарт-процесс проектов не настроен — карточка не создана.",
            )

        group_field = _clean_str((mapping or {}).get("bitrix_group_id"))
        if not group_field:
            # mapping непуст, но без связи с группой найти существующую
            # карточку нечем: молчаливый переход к созданию плодил бы дубль
            # на каждое повторное нажатие (приложение ничего не удаляет).
            return StepResult(
                status="skipped",
                error="В маппинге не настроена связь карточки с группой (bitrix_group_id) — карточка не создана.",
            )

        try:
            response = self._call(
                "crm.item.list",
                {
                    "entityTypeId": entity_type_id,
                    "filter": {group_field: self._to_bitrix_id(group_id)},
                    "select": ["id"],
                },
            )
        except Exception as exc:
            logger.warning("ensure_card: crm.item.list failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти карточку: {exc}")

        existing, parsed_ok = _extract_rows(response)
        if not parsed_ok:
            return StepResult(status="error", error="Битрикс вернул ответ неожиданного вида при поиске карточки.")
        if existing:
            return StepResult(
                status="found",
                id=_clean_str(existing[0].get("id") or existing[0].get("ID")),
                name=fields.project_name,
            )

        try:
            created = self._call(
                "crm.item.add",
                {
                    "entityTypeId": entity_type_id,
                    "fields": self.build_card_fields(fields, group_id, mapping),
                },
            )
        except Exception as exc:
            logger.warning("ensure_card: crm.item.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать карточку: {exc}")

        # crm.item.add отдаёт созданную запись как result.item — id достаём
        # через тот же защищённый разбор, что и везде (_extract_created_id,
        # заведён в Task 2); _extract_rows здесь не годится — он не знает
        # ключа в единственном числе.
        created_id = _clean_str(_extract_created_id(created))
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор карточки.")

        return StepResult(status="created", id=created_id, name=fields.project_name)

    def write_through(
        self, fields: ResolvedProjectFields, group_id: str, item_id: Optional[str]
    ) -> None:
        """Пишет карточку в локальную таблицу сразу после создания в Битриксе,
        чтобы проект появился на доске немедленно, а не через фоновый синк:
        иначе сотрудник решит, что не сработало, и нажмёт повторно."""
        defaults = {
            "project_name": fields.project_name,
            "stage": fields.stage,
            "project_item_id": _clean_str(item_id) or None,
            "project_hours_budget": fields.project_hours_budget,
            "hourly_rate": fields.hourly_rate,
            "planned_budget_amount": fields.planned_budget_amount,
            "is_support": fields.is_support,
            "project_type": fields.project_type,
            "budget_mode": fields.budget_mode,
            "curator_user_id": fields.curator_user_id,
            "curator_name": fields.curator_name,
            "project_start_date": fields.project_start_date,
            "project_end_date": fields.project_end_date,
            "company_id": fields.company_id,
            "company_name": fields.company_name,
            "our_legal_entity_id": fields.our_legal_entity_id,
            "our_legal_entity_name": fields.our_legal_entity_name,
            "is_archived": False,
            "stage_source": "manual",
        }
        ProjectCard.objects.update_or_create(
            **scope_to_tenant(self.account, write=True),
            project_id=_clean_str(group_id),
            defaults=defaults,
        )

    def create(
        self,
        form: Dict[str, Any],
        *,
        current_user_id: str,
        current_user_name: str,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Оркестратор: компания -> её реквизит (ИНН) -> группа -> карточка,
        строго по порядку — карточка ссылается на первые две сущности (id
        компании, не реквизита). Сбой шага не откатывает уже созданное:
        возвращаем частичный результат, повторный вызов досоздаёт недостающее
        (каждый шаг идемпотентен сам по себе, включая реквизит — см. докстринг
        ensure_requisite). Шаг реквизита применим только при создании НОВОЙ
        компании (fields.inn пуст для уже выбранной из поиска — см. докстринг
        resolve_project_fields) и сам решает свою применимость, как и
        ensure_card решает применимость по конфигу смарт-процесса.

        Конкурентность (поднято ревью Task 2/4, см. progress.md):

        1. Гонка двух почти одновременных вызовов create(). Каждый шаг
           идемпотентен по принципу "сначала ищу, потом создаю", но два
           запроса могут пройти поиск параллельно и оба ничего не найти — на
           уровне шага это не лечится. Мутирующую часть (ensure_company ..
           write_through) оборачиваем в account_sync_lock с ОТДЕЛЬНЫМ
           scope="project_create", а не переиспользуем существующий
           scope="project": тот занят фоновой ProjectSyncService.sync()
           (sync_scheduler_service, _save_configuration_with_project_sync) —
           общий бюджет привязал бы кнопку к длительности чужой синхронизации
           портала (секунды-минуты на крупном портале) и наоборот, синк
           пропускал бы цикл из-за чужого нажатия кнопки. Подробности — в
           utils/decorators/sync_lock.py. Лок non-blocking
           (pg_try_advisory_lock) — при занятости не ждём и не бросаем
           исключение наружу, а честно возвращаем частичный результат с
           понятной ошибкой и предложением повторить.
        2. Дубль строки ProjectCard в скоупе портала. unique_together стоит
           на паре (bitrix24_account, project_id), а не (portal, project_id)
           — наследие ранней миграции. Значит write_through, который ищет и
           пишет строго СВОИМ аккаунтом (scope_to_tenant(.., write=True)), не
           видит строку, которую для того же project_id уже мог завести
           другой сотрудник ЭТОГО ЖЕ портала, — и создаёт вторую. Перед
           вызовом write_through проверяем СКОУП ЧТЕНИЯ (по порталу, без
           write=True) и, если строка там уже есть, не дублируем её.
        """
        today = today or timezone.localdate()
        config_service = ConfigurationService(self.client, self.account)
        config = config_service.get_configuration_sync()

        card_service = ProjectCardService(self.client, self.account)
        try:
            legal_entities = card_service.get_legal_entities(config)
        except Exception as exc:
            logger.warning("create: get_legal_entities failed: %s", exc)
            legal_entities = []
        try:
            stage_options = card_service.get_project_stage_options(config)
        except Exception as exc:
            logger.warning("create: get_project_stage_options failed: %s", exc)
            stage_options = []

        fields, missing = resolve_project_fields(
            form,
            config=config,
            current_user_id=current_user_id,
            current_user_name=current_user_name,
            today=today,
            legal_entities=legal_entities,
            stage_options=stage_options,
        )

        skipped = StepResult(status="skipped")
        if missing:
            return {
                "company": skipped.as_dict(),
                "requisite": skipped.as_dict(),
                "group": skipped.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": missing,
            }

        try:
            with account_sync_lock(self.account, scope="project_create"):
                return self._create_under_lock(fields, config, skipped)
        except SyncLockBusy:
            busy = StepResult(
                status="error",
                error="Кто-то уже создаёт проект на этом портале. Повторите через несколько секунд.",
            )
            return {
                "company": busy.as_dict(),
                "requisite": skipped.as_dict(),
                "group": skipped.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": [],
            }

    def _create_under_lock(
        self, fields: ResolvedProjectFields, config: Dict[str, Any], skipped: StepResult
    ) -> Dict[str, Any]:
        """Тело create() внутри account_sync_lock: компания -> её реквизит
        (ИНН) -> группа -> карточка, плюс write-through. Вынесено отдельным
        методом только ради читаемости create() — самостоятельного смысла
        вне лока не имеет."""
        company = self.ensure_company(fields.company_id, fields.company_name, fields.inn)
        if not company.id:
            return {
                "company": company.as_dict(),
                "requisite": skipped.as_dict(),
                "group": skipped.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": [],
            }
        fields.company_id = company.id
        fields.company_name = fields.company_name or company.name

        # fields.inn пуст ровно тогда, когда компания уже была выбрана из
        # поиска (company_id пришёл от клиента) — resolve_project_fields
        # гарантирует это (см. её докстринг про "не трогается"), поэтому
        # здесь достаточно просто позвать шаг: он сам вернёт "skipped" на
        # пустом ИНН (см. докстринг ensure_requisite), отдельная ветка
        # if/else тут не нужна — тот же приём, что и с ensure_card ниже
        # (шаг сам решает свою применимость по конфигу, а не вызывающий код).
        requisite = self.ensure_requisite(company.id, company.name, fields.inn)

        group = self.ensure_group(fields.project_name)
        if not group.id:
            return {
                "company": company.as_dict(),
                "requisite": requisite.as_dict(),
                "group": group.as_dict(),
                "card": skipped.as_dict(),
                "done": False,
                "missing_fields": [],
            }

        try:
            entity_type_id = int(config.get("project_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        mapping = config.get("project_fields_mapping") or {}

        card = self.ensure_card(
            fields, group.id, entity_type_id=entity_type_id, mapping=mapping
        )

        # write_through пишем при ЛЮБОМ статусе card, включая "error". Строка
        # в локальной таблице отражает ГРУППУ (доска ключуется по
        # project_id=group.id), а не карточку смарт-процесса, а группа к этому
        # моменту уже гарантированно существует в Битриксе (иначе был бы ранний
        # return выше). Если не показать её на доске из-за отдельного сбоя
        # карточки, сотрудник решит, что ничего не сработало, и нажмёт кнопку
        # снова — а повторный ensure_group для точного совпадения имени найдёт
        # ту же группу и ничего не сломает, а вот ensure_card при живой ошибке
        # (например, временная недоступность смарт-процесса) будет пытаться
        # досоздать карточку на КАЖДОЕ такое повторное нажатие без всякой
        # пользы, пока проект молча не отображается на доске.
        #
        # Дубль строки в скоупе портала (см. докстринг create() и progress.md,
        # ревью Task 4): unique_together у ProjectCard — пара
        # (bitrix24_account, project_id), не (portal, project_id). write_through
        # ищет и пишет строго своим аккаунтом и не увидит строку, которую для
        # этого же project_id мог уже завести другой сотрудник того же
        # портала, — и создаст вторую. Поэтому сначала смотрим в СКОУПЕ ЧТЕНИЯ
        # (по порталу, exclude по своему аккаунту исключает штатный повторный
        # вызов СВОИМ же аккаунтом — тот обязан обновлять свою строку как и
        # раньше) и, если строка уже есть, не пишем повторно.
        try:
            already_on_board = (
                ProjectCard.objects.filter(
                    **scope_to_tenant(self.account), project_id=_clean_str(group.id)
                )
                .exclude(bitrix24_account=self.account)
                .exists()
            )
            if already_on_board:
                logger.info(
                    "create: project %s already has a local row from another account "
                    "on this portal; skip write_through to avoid a duplicate.",
                    group.id,
                )
            else:
                self.write_through(fields, group.id, card.id)

            # К этой строке локальная запись для project_id=group.id
            # гарантированно существует — либо её только что записал
            # write_through выше, либо exists() только что подтвердил, что
            # её раньше записал другой аккаунт того же портала
            # (already_on_board=True). В ОБОИХ случаях сбрасываем кэш ЭТОГО
            # аккаунта (self.account): у кэша свой собственный
            # account-scoped ключ (build_account_cache_key), и после чужой
            # записи его некому сбросить, кроме этого же запроса — чужой
            # write_through чистил только СВОЙ (чужой) кэш-ключ. Без сброса
            # в ветке already_on_board кнопка отчитывалась бы успехом, а
            # доска ЭТОГО пользователя (если её кэш прогрелся до чужой
            # записи) оставалась пустой до истечения PROJECT_BOARD_CACHE_TTL/
            # HOMEPAGE_CACHE_TTL (2 минуты, project_board_shared.py) — тот же
            # симптом, что и основной баг, просто на более узком окне гонки
            # (ре-ревью, находка после первого раунда фикса; воспроизведено
            # тестами в CreateCacheInvalidationTest,
            # tests_project_creation_service.py). Сбрасываем БЕЗУСЛОВНО, не
            # различая found/created (write_through делает update_or_create
            # независимо от статусов шагов — см. отчёт в
            # task-9-cache-fix-report.md). Если сама попытка (exists() выше
            # или write_through) упадёт — except ниже — кэш не трогаем:
            # локальная строка в этом случае не гарантирована, показывать
            # нечего.
            invalidate_project_runtime_caches(self.account)
        except Exception as exc:
            logger.warning("create: write_through failed for group %s: %s", group.id, exc)

        return {
            "company": company.as_dict(),
            "requisite": requisite.as_dict(),
            "group": group.as_dict(),
            "card": card.as_dict(),
            # requisite.status != "error" — новый режим частичного отказа
            # "компания создана, реквизит нет" (inn-brief.md) обязан вести
            # себя как и остальные шаги: сорвать done, чтобы фронт предложил
            # повторить. skipped (существующая компания, ИНН не при делах)
            # done не трогает — так же, как "skipped" у card (смарт-процесс
            # не настроен) сегодня не трогает done.
            "done": card.status != "error" and requisite.status != "error",
            "missing_fields": [],
        }
