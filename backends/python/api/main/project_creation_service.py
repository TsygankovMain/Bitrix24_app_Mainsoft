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

        try:
            response = self._call(
                "crm.company.list",
                {"filter": {"=TITLE": company_name}, "select": ["ID", "TITLE"]},
            )
        except Exception as exc:
            logger.warning("ensure_company: crm.company.list failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось найти компанию: {exc}")

        matches = [
            {"id": _clean_str(row.get("ID")), "name": _clean_str(row.get("TITLE"))}
            for row in (response.get("result") or [])
            if _clean_str(row.get("ID"))
        ]

        if len(matches) == 1:
            return StepResult(status="found", id=matches[0]["id"], name=matches[0]["name"])
        if len(matches) > 1:
            return StepResult(status="ambiguous", candidates=matches)

        try:
            created = self._call("crm.company.add", {"fields": {"TITLE": company_name}})
        except Exception as exc:
            logger.warning("ensure_company: crm.company.add failed: %s", exc)
            return StepResult(status="error", error=f"Не удалось создать компанию: {exc}")

        created_id = _clean_str(created.get("result"))
        if not created_id:
            return StepResult(status="error", error="Битрикс не вернул идентификатор компании.")

        return StepResult(status="created", id=created_id, name=company_name)
