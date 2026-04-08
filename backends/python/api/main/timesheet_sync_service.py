import logging
import time
from typing import Any, Dict, List

from b24pysdk import Client
from django.db import transaction

from .models import Bitrix24Account, TimesheetItem
from .report_services import DataProcessingService


logger = logging.getLogger(__name__)


class TimesheetSyncService:
    MAX_RETRIES = 5
    BASE_RETRY_DELAY = 2.0
    THROTTLE_DELAY = 0.5

    def __init__(self, client: Client, account: Bitrix24Account, config: Dict[str, Any]):
        self.client = client
        self.account = account
        self.config = config
        self.entity_type_id = config.get("sp_entity_type_id")
        self.processing_service = DataProcessingService(config.get("fields_mapping", {}))

    def _call_with_retry(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(self.MAX_RETRIES):
            try:
                return self.client._bitrix_token.call_method(method, params)
            except Exception as exc:
                error_str = str(exc).lower()
                is_rate_limit = (
                    "too many requests" in error_str
                    or "querylimitexceeded" in error_str
                    or "503" in error_str
                    or "429" in error_str
                    or "service temporarily unavailable" in error_str
                )
                if is_rate_limit and attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Rate limit hit (attempt %s/%s). Waiting %ss before retry. Error: %s",
                        attempt + 1,
                        self.MAX_RETRIES,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    continue
                raise

    def sync_all(self) -> int:
        logger.info("Starting sync for account %s", self.account.pk)

        if not self.entity_type_id:
            logger.error("No SP Entity Type ID configured cannot sync.")
            return 0

        start = 0
        limit = 50
        total_fetched = 0
        all_bitrix_ids = set()

        while True:
            try:
                logger.info("Fetching batch start=%s for SPA %s", start, self.entity_type_id)
                response = self._call_with_retry(
                    "crm.item.list",
                    {
                        "entityTypeId": self.entity_type_id,
                        "select": ["*", "UF_*"],
                        "order": {"id": "DESC"},
                        "start": start,
                        "limit": limit,
                    },
                )

                items = self._extract_items(response)
                if not items:
                    logger.info("No more items to fetch.")
                    break

                normalized_items = self.processing_service.normalize_items(items)
                for item in normalized_items:
                    try:
                        all_bitrix_ids.add(int(item["id_elem"]))
                    except (TypeError, ValueError, KeyError):
                        continue

                self._save_batch(normalized_items)

                count = len(items)
                total_fetched += count
                start += count
                logger.info("Processed %s items. Total: %s", count, total_fetched)

                if count < limit:
                    break

                time.sleep(self.THROTTLE_DELAY)
            except Exception as exc:
                logger.error("Sync error at start=%s: %s", start, exc)
                raise

        if all_bitrix_ids:
            deleted_count, _ = (
                TimesheetItem.objects.filter(bitrix24_account=self.account)
                .exclude(bitrix_id__in=all_bitrix_ids)
                .delete()
            )
            if deleted_count > 0:
                logger.info("Deleted %s orphaned records", deleted_count)

        logger.info("Sync complete. Total items: %s", total_fetched)
        return total_fetched

    @transaction.atomic
    def _save_batch(self, normalized_items: List[Dict[str, Any]]) -> None:
        for item in normalized_items:
            try:
                bitrix_id = int(item["id_elem"])
                date_reflection = item["data"]
                if not date_reflection:
                    logger.warning("Skipping item %s due to missing date", bitrix_id)
                    continue

                TimesheetItem.objects.update_or_create(
                    bitrix24_account=self.account,
                    bitrix_id=bitrix_id,
                    defaults={
                        "task_id": item["id_zadachi"],
                        "employee_id": item["sotrudnik_id"],
                        "hours": item["kolichestvo_chasov"],
                        "is_billable": item["uchitivaem"],
                        "non_billable_hours": item["ne_uchitivaemie_chasi"],
                        "description": item["opisanie"],
                        "project_title": item["project_name"],
                        "project_id": item["project_id"],
                        "task_hierarchy_ids": item["id_zadach_ierarhiya"],
                        "task_hierarchy_titles": item["title_zadach_ierarhiya"],
                        "date_reflection": date_reflection,
                        "source_created_at": item.get("source_created_at"),
                    },
                )
            except Exception as exc:
                logger.error("Error saving item %s: %s", item.get("id_elem"), exc)

    @staticmethod
    def _extract_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = response.get("result", [])
        if isinstance(result, dict):
            items = result.get("items")
            if items is None:
                items = result.get("result", [])
        else:
            items = result

        return items if isinstance(items, list) else []
