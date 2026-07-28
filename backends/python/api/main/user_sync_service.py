import logging
from typing import Any, Dict, List

from b24pysdk import Client
from django.db import transaction
from django.utils import timezone

from .employee_ids import extract_bitrix_user_id
from .models import Bitrix24Account, PortalUser
from .tenant_scoping import scope_to_tenant

logger = logging.getLogger(__name__)

_INACTIVE_ACTIVE_VALUES = {"N", "NO", "FALSE", "0"}


def _parse_active_flag(raw_value: Any) -> bool:
    """Разбирает ACTIVE из ответа Bitrix user.get в python bool.

    Инцидент 2026-07-28 (прод-регресс «User <id>» в дереве задачи): Bitrix
    REST отдаёт ACTIVE как JSON boolean (true/false), а не только строку
    "Y"/"N". Старое str(value).upper() == "Y" для True давало "TRUE" != "Y"
    -> ВСЕ пользователи считались уволенными (0 активных из 56 на проде).

    Принимает JSON boolean, "Y"/"N", "true"/"false", 1/0 (строки — в любом
    регистре). Отсутствие значения (None) или нераспознанный формат ->
    активен: безопасный дефолт, лучше по ошибке показать уволенного, чем
    спрятать активного из-за парсинга.
    """
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value is None:
        return True
    if isinstance(raw_value, (int, float)):
        return raw_value != 0
    return str(raw_value).strip().upper() not in _INACTIVE_ACTIVE_VALUES


class UserSyncService:
    """Полный постраничный синк справочника пользователей Bitrix24 -> PortalUser.

    В отличие от TimesheetSyncService, здесь НЕТ инкремента и НЕТ удаления
    "осиротевших" записей: пользователей на портале мало (десятки-сотни),
    полный обход дешёвый, а удаление запрещено Global Constraint ("ничего не
    удаляем из данных"). Пользователь, пропавший из ответа Bitrix, просто
    сохраняет последнее известное состояние до следующего успешного синка.
    """

    PAGE_SIZE = 50
    MAX_PAGES = 1000  # защита от зацикливания фонового джоба; 1000*50 = 50000 юзеров с запасом
    BULK_BATCH_SIZE = 200
    UPSERT_FIELDS = ["name", "last_name", "active", "updated_at"]

    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account

    def sync(self) -> Dict[str, int]:
        raw_users = self._fetch_all_users()
        return self._save_batch(raw_users)

    def _fetch_all_users(self) -> List[Dict[str, Any]]:
        """Все пользователи портала, БЕЗ фильтра ACTIVE (нужны и уволенные —
        см. Global Constraints). Пагинация: тот же курсор next/total/len<PAGE_SIZE,
        что в BitrixDataService.fetch_active_users."""
        result: List[Dict[str, Any]] = []
        seen_ids = set()
        start = 0
        pages = 0

        while pages < self.MAX_PAGES:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"sort": "ID", "order": "ASC", "start": start},
            )
            users = response.get("result", [])
            if not users:
                break

            for user in users:
                user_id = extract_bitrix_user_id(user.get("ID"))
                if not user_id or user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
                result.append(user)

            pages += 1
            next_value = response.get("next")
            if next_value not in (None, "", False):
                next_start = int(next_value)
                if next_start <= start:
                    break
                start = next_start
                continue

            total = response.get("total")
            if total is not None:
                next_start = start + len(users)
                if next_start >= int(total):
                    break
                start = next_start
                continue

            if len(users) < self.PAGE_SIZE:
                break
            start += len(users)

        return result

    @transaction.atomic
    def _save_batch(self, raw_users: List[Dict[str, Any]]) -> Dict[str, int]:
        prepared: List[tuple] = []
        for user in raw_users:
            bitrix_id = extract_bitrix_user_id(user.get("ID"))
            if not bitrix_id:
                continue
            prepared.append((
                bitrix_id,
                {
                    "name": user.get("NAME") or "",
                    "last_name": user.get("LAST_NAME") or "",
                    "active": _parse_active_flag(user.get("ACTIVE")),
                },
            ))

        if not prepared:
            return {"synced": 0, "created": 0, "updated": 0}

        now = timezone.now()
        bitrix_ids = [bid for bid, _ in prepared]
        existing = {
            row.bitrix_id: row
            for row in PortalUser.objects.filter(
                **scope_to_tenant(self.account),
                bitrix_id__in=bitrix_ids,
            )
        }

        to_create: List[PortalUser] = []
        to_update: List[PortalUser] = []

        for bitrix_id, defaults in prepared:
            existing_row = existing.get(bitrix_id)
            if existing_row is None:
                to_create.append(
                    PortalUser(
                        **scope_to_tenant(self.account, write=True),
                        bitrix_id=bitrix_id,
                        created_at=now,
                        updated_at=now,
                        **defaults,
                    )
                )
                continue

            has_changes = False
            for field_name, field_value in defaults.items():
                if getattr(existing_row, field_name) != field_value:
                    setattr(existing_row, field_name, field_value)
                    has_changes = True
            if has_changes:
                existing_row.updated_at = now
                to_update.append(existing_row)

        if to_create:
            PortalUser.objects.bulk_create(to_create, batch_size=self.BULK_BATCH_SIZE)
        if to_update:
            PortalUser.objects.bulk_update(to_update, self.UPSERT_FIELDS, batch_size=self.BULK_BATCH_SIZE)

        return {"synced": len(prepared), "created": len(to_create), "updated": len(to_update)}
