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
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client

from .models import Bitrix24Account

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    id: Optional[str] = None
    name: str = ""
    candidates: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "id": self.id,
            "name": self.name,
            "candidates": self.candidates,
            "error": self.error,
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


class ProjectCreationService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.client._bitrix_token.call_method(method, params)

    def ensure_company(self, company_id: Optional[str], company_name: str) -> StepResult:
        """Шаг 1: компания. Передан id — используем как есть, поиска не делаем."""
        company_id = _clean_str(company_id)
        company_name = _clean_str(company_name)

        if company_id:
            return StepResult(status="found", id=company_id, name=company_name)

        if not company_name:
            return StepResult(status="error", error="Не указана компания.")

        # Шаг 1: поиск по названию
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

        # Шаг 2: создание компании, если не найдена
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

    def ensure_group(self, group_name: str) -> StepResult:
        """Шаг 2: проект/группа в Задачах.

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
