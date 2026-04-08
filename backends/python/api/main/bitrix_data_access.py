import json
import logging
from typing import Any, Dict, List, Optional

from b24pysdk import Client
from django.core.cache import cache

from .employee_ids import extract_bitrix_user_id, normalize_employee_id
from .models import Bitrix24Account
from .project_board_shared import (
    BITRIX_REFERENCE_CACHE_TTL,
    FILTER_EMPLOYEES_CACHE_SUFFIX,
    build_account_cache_key,
)


logger = logging.getLogger(__name__)


class BitrixDataService:
    """Service for fetching data from Bitrix24."""

    def __init__(self, client: Client, config: Dict[str, Any], account: Optional[Bitrix24Account] = None):
        self.client = client
        self.config = config
        self.account = account
        self.entity_type_id = config.get("sp_entity_type_id", 0)

    def check_connection(self) -> None:
        try:
            response = self.client._bitrix_token.call_method("crm.type.list", {})
            types = response.get("result", {}).get("types", [])
            logger.info("Found %s Smart Processes", len(types))
            for item in types:
                logger.info("SPA: %s (ID: %s)", item.get("title"), item.get("entityTypeId"))

            target = next((item for item in types if str(item.get("entityTypeId")) == str(self.entity_type_id)), None)
            if target:
                logger.info("Target SPA %s FOUND.", self.entity_type_id)
            else:
                logger.error("Target SPA %s NOT FOUND in crm.type.list!", self.entity_type_id)
        except Exception as exc:
            logger.error("Failed to list SPAs: %s", exc)

    def fetch_users(self, user_ids: List[str]) -> Dict[str, str]:
        if not user_ids:
            return {}

        numeric_to_aliases: Dict[str, set[str]] = {}
        for uid in user_ids:
            raw_id = str(uid).strip() if uid not in (None, "") else ""
            normalized_id = normalize_employee_id(uid)
            numeric_id = extract_bitrix_user_id(uid)
            if not numeric_id:
                continue

            aliases = numeric_to_aliases.setdefault(numeric_id, set())
            aliases.add(numeric_id)
            if normalized_id:
                aliases.add(normalized_id)
            if raw_id:
                aliases.add(raw_id)

        if not numeric_to_aliases:
            return {}

        try:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"FILTER": {"ID": list(numeric_to_aliases.keys())}},
            )
            users = response.get("result", [])
            user_map: Dict[str, str] = {}
            for user in users:
                numeric_id = extract_bitrix_user_id(user.get("ID"))
                if not numeric_id:
                    continue

                name = self._build_user_name(user, numeric_id)
                for alias in numeric_to_aliases.get(numeric_id, {numeric_id}):
                    user_map[alias] = name
            return user_map
        except Exception as exc:
            logger.error("Error fetching users: %s", exc)
            return {}

    def fetch_active_users(self) -> List[Dict[str, str]]:
        if self.account:
            cache_key = build_account_cache_key(self.account, FILTER_EMPLOYEES_CACHE_SUFFIX)
            cached = cache.get(cache_key)
            if cached:
                return cached
            if cached == []:
                cache.delete(cache_key)

        try:
            result: List[Dict[str, str]] = []
            seen_ids = set()
            start = 0

            while True:
                response = self.client._bitrix_token.call_method(
                    "user.get",
                    {
                        "FILTER": {"ACTIVE": "Y"},
                        "sort": "LAST_NAME",
                        "order": "ASC",
                        "start": start,
                    },
                )
                users = response.get("result", [])

                for user in users:
                    user_id = normalize_employee_id(user.get("ID"))
                    if not user_id:
                        continue
                    if user_id in seen_ids:
                        continue
                    seen_ids.add(user_id)

                    result.append({"id": user_id, "name": self._build_user_name(user, user_id)})

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

                if len(users) < 50:
                    break

                start += len(users)

            result = sorted(result, key=lambda item: item["name"])
            if self.account:
                cache_key = build_account_cache_key(self.account, FILTER_EMPLOYEES_CACHE_SUFFIX)
                if result:
                    cache.set(cache_key, result, BITRIX_REFERENCE_CACHE_TTL)
                else:
                    cache.delete(cache_key)
            return result
        except Exception as exc:
            logger.error("Error fetching active users: %s", exc)
            return []

    def fetch_all_items(self, extra_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.check_connection()

        if not self.entity_type_id:
            logger.error("No SP Entity Type ID configured")
            return []

        base_filter = {"entityTypeId": self.entity_type_id}
        if extra_filter:
            base_filter.update(extra_filter)

        logger.info("Executing single request fetch (SELECT *, UF_*) for SPA %s", self.entity_type_id)
        try:
            response = self.client._bitrix_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": self.entity_type_id,
                    "filter": base_filter,
                    "select": ["*", "UF_*"],
                    "order": {"id": "DESC"},
                    "start": 0,
                    "limit": 50,
                },
            )
            all_items = response.get("result", {}).get("items", [])
        except Exception as exc:
            logger.error("Error fetching items: %s", exc)
            all_items = []

        logger.info("Total items fetched from Bitrix24: %s", len(all_items))
        if all_items:
            logger.info("First item FULL DUMP:")
            logger.info(json.dumps(all_items[0], indent=2, default=str))
        return all_items

    @staticmethod
    def _build_user_name(user: Dict[str, Any], user_id: str) -> str:
        name = f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".strip()
        if name:
            return name
        return user.get("EMAIL") or user_id
