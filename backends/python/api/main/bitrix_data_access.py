import json
import logging
from typing import Any, Dict, List, Optional

from b24pysdk import Client
from django.core.cache import cache

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

        numeric_to_original: Dict[str, str] = {}
        for uid in user_ids:
            if not uid:
                continue
            uid_str = str(uid).strip()
            if uid_str.startswith("["):
                try:
                    parsed = json.loads(uid_str)
                    if isinstance(parsed, list) and parsed:
                        numeric_to_original[str(parsed[0])] = uid_str
                        continue
                except Exception:
                    pass
                continue

            if uid_str and uid_str.lstrip("-").isdigit():
                numeric_to_original[uid_str] = uid_str

        if not numeric_to_original:
            return {}

        try:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"FILTER": {"ID": list(numeric_to_original.keys())}},
            )
            users = response.get("result", [])
            user_map: Dict[str, str] = {}
            for user in users:
                numeric_id = str(user.get("ID", ""))
                name = f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".strip()
                if not name:
                    name = user.get("EMAIL") or f"User {numeric_id}"
                user_map[numeric_id] = name
                original = numeric_to_original.get(numeric_id)
                if original and original != numeric_id:
                    user_map[original] = name
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
            response = self.client._bitrix_token.call_method(
                "user.get",
                {
                    "FILTER": {"ACTIVE": "Y"},
                    "sort": "LAST_NAME",
                    "order": "ASC",
                },
            )
            users = response.get("result", [])
            result: List[Dict[str, str]] = []

            for user in users:
                user_id = str(user.get("ID", "")).strip()
                if not user_id:
                    continue

                user_type = str(user.get("USER_TYPE", "")).strip().lower()
                if user_type and user_type != "employee":
                    continue

                name = f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".strip()
                if not name:
                    name = user.get("EMAIL") or f"User {user_id}"

                result.append({"id": user_id, "name": name})

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
