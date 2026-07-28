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
from typing import Any, Dict, List, Optional

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


def _extract_rows(response: Any) -> List[Dict[str, Any]]:
    """Достаёт список записей из ответа Битрикса, не доверяя его форме.

    Битрикс отдаёт result то списком, то словарём с items, а при нештатных
    ситуациях — чем угодно. Разбор ответа обязан быть таким же защищённым,
    как сам вызов: шаг оркестратора не имеет права бросить исключение, иначе
    следующие шаги не выполнятся и вызывающий код не соберёт частичный
    результат.
    """
    if not isinstance(response, dict):
        return []

    result = response.get("result")
    if result is None:
        return []

    # Если result — словарь, пытаемся достать items или вложенный result
    if isinstance(result, dict):
        items = result.get("items")
        if items is None:
            items = result.get("result")
    else:
        items = result

    # Если items не список — пустой результат
    if not isinstance(items, list):
        return []

    # Фильтруем элементы, которые не словари
    return [item for item in items if isinstance(item, dict)]


def _extract_scalar_id(response: Any) -> Optional[str]:
    """Извлекает скалярный идентификатор из ответа Битрикса на crm.company.add.

    Возвращает None если ответ не содержит валидного идентификатора (не
    целое число и не строку с цифрами).
    """
    if not isinstance(response, dict):
        return None

    result = response.get("result")
    if result is None:
        return None

    # Если result — целое число или строка с цифрами, это валидный ID
    if isinstance(result, int):
        return str(result)
    if isinstance(result, str) and result.strip() and result.strip().isdigit():
        return result.strip()

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
            rows = _extract_rows(response)
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
            created_id = _extract_scalar_id(created)
        except Exception as exc:
            logger.warning("ensure_company: crm.company.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать компанию: {exc}")

        if not created_id:
            return StepResult(
                status="error",
                error="Битрикс не вернул валидный идентификатор компании.",
            )

        return StepResult(status="created", id=created_id, name=company_name)
