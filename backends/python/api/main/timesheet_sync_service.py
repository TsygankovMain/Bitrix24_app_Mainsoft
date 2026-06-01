import logging
import time
from typing import Any, Dict, List

from b24pysdk import Client
from django.db import transaction
from django.utils import timezone

from .models import Bitrix24Account, TimesheetItem
from .report_services import DataProcessingService


logger = logging.getLogger(__name__)


class TimesheetSyncService:
    MAX_RETRIES = 5
    BASE_RETRY_DELAY = 2.0
    THROTTLE_DELAY = 0.5
    BULK_BATCH_SIZE = 200
    UPSERT_FIELDS = [
        "task_id",
        "employee_id",
        "hours",
        "is_billable",
        "non_billable_hours",
        "description",
        "project_title",
        "project_id",
        "project_item_id",
        "hourly_rate_snapshot",
        "task_hierarchy_ids",
        "task_hierarchy_titles",
        "date_reflection",
        "source_created_at",
        "updated_at",
    ]

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

        # Быстрая выборка больших объёмов (apidocs Bitrix, performance/huge-data):
        #  - start=-1 отключает медленный подсчёт total на каждой странице;
        #  - keyset-пагинация: order id ASC + filter {">id": last_id} вместо offset,
        #    что убирает и медленный offset-скан на больших наборах.
        # Полный обход сохраняется -> сверка осиротевших записей ниже продолжает работать,
        # данные остаются всегда свежими (полный синк), но в разы быстрее.
        last_id = 0
        page_size = 50
        total_fetched = 0
        all_bitrix_ids = set()
        all_new_cards: List[Dict[str, Any]] = []

        while True:
            try:
                logger.info("Fetching batch id>%s for SPA %s", last_id, self.entity_type_id)
                response = self._call_with_retry(
                    "crm.item.list",
                    {
                        "entityTypeId": self.entity_type_id,
                        "select": ["*", "UF_*"],
                        "order": {"id": "ASC"},
                        "filter": {">id": last_id},
                        "start": -1,
                    },
                )

                items = self._extract_items(response)
                if not items:
                    logger.info("No more items to fetch.")
                    break

                # Сдвигаем курсор на максимальный id пачки (keyset-пагинация)
                batch_max_id = last_id
                for raw in items:
                    try:
                        rid = int(raw.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if rid > batch_max_id:
                        batch_max_id = rid

                normalized_items = self.processing_service.normalize_items(items)
                for item in normalized_items:
                    try:
                        all_bitrix_ids.add(int(item["id_elem"]))
                    except (TypeError, ValueError, KeyError):
                        continue

                new_cards = self._save_batch(normalized_items)
                all_new_cards.extend(new_cards)

                count = len(items)
                total_fetched += count
                logger.info("Processed %s items. Total: %s", count, total_fetched)

                # Защита от зацикливания, если курсор не продвинулся
                if batch_max_id <= last_id:
                    logger.warning(
                        "Cursor did not advance (last_id=%s, batch=%s items); stopping.",
                        last_id,
                        count,
                    )
                    break
                last_id = batch_max_id

                if count < page_size:
                    break

                time.sleep(self.THROTTLE_DELAY)
            except Exception as exc:
                logger.error("Sync error at id>%s: %s", last_id, exc)
                raise

        if all_bitrix_ids:
            deleted_count, _ = (
                TimesheetItem.objects.filter(bitrix24_account=self.account)
                .exclude(bitrix_id__in=all_bitrix_ids)
                .delete()
            )
            if deleted_count > 0:
                logger.info("Deleted %s orphaned records", deleted_count)

        self._autofill_inn(all_new_cards)

        logger.info("Sync complete. Total items: %s", total_fetched)
        return total_fetched

    def _autofill_inn(self, new_cards: List[Dict[str, Any]]) -> None:
        """Авто-простановка ИНН в новые карточки списания. Изолировано: ошибки не валят синк."""
        if not new_cards:
            return
        try:
            from .inn_backfill_service import InnBackfillService
            service = InnBackfillService(self.client, self.account, self.config)
            summary = service.autofill(new_cards)
            logger.info("INN autofill after sync: %s", summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("INN autofill failed (sync not affected): %s", exc)

    @transaction.atomic
    def _save_batch(self, normalized_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prepared_items: List[tuple[int, Dict[str, Any]]] = []
        bitrix_ids: List[int] = []

        for item in normalized_items:
            try:
                bitrix_id = int(item["id_elem"])
                date_reflection = item["data"]
                if not date_reflection:
                    logger.warning("Skipping item %s due to missing date", bitrix_id)
                    continue

                prepared_items.append(
                    (
                        bitrix_id,
                        {
                            "task_id": item["id_zadachi"],
                            "employee_id": item["sotrudnik_id"],
                            "hours": item["kolichestvo_chasov"],
                            "is_billable": item["uchitivaem"],
                            "non_billable_hours": item["ne_uchitivaemie_chasi"],
                            "description": item["opisanie"],
                            "project_title": item["project_name"],
                            "project_id": item["project_id"],
                            "project_item_id": item.get("project_item_id"),
                            "hourly_rate_snapshot": item.get("hourly_rate_snapshot"),
                            "task_hierarchy_ids": item["id_zadach_ierarhiya"],
                            "task_hierarchy_titles": item["title_zadach_ierarhiya"],
                            "date_reflection": date_reflection,
                            "source_created_at": item.get("source_created_at"),
                        },
                    )
                )
                bitrix_ids.append(bitrix_id)
            except Exception as exc:
                logger.error("Error saving item %s: %s", item.get("id_elem"), exc)

        if not prepared_items:
            return []

        now = timezone.now()
        existing_items = {
            item.bitrix_id: item
            for item in TimesheetItem.objects.filter(
                bitrix24_account=self.account,
                bitrix_id__in=bitrix_ids,
            )
        }
        to_create: List[TimesheetItem] = []
        to_update: List[TimesheetItem] = []

        for bitrix_id, defaults in prepared_items:
            existing_item = existing_items.get(bitrix_id)
            if existing_item is None:
                to_create.append(
                    TimesheetItem(
                        bitrix24_account=self.account,
                        bitrix_id=bitrix_id,
                        created_at=now,
                        updated_at=now,
                        **defaults,
                    )
                )
                continue

            has_changes = False
            for field_name, field_value in defaults.items():
                if getattr(existing_item, field_name) != field_value:
                    setattr(existing_item, field_name, field_value)
                    has_changes = True

            if has_changes:
                existing_item.updated_at = now
                to_update.append(existing_item)

        if to_create:
            TimesheetItem.objects.bulk_create(to_create, batch_size=self.BULK_BATCH_SIZE)
        if to_update:
            TimesheetItem.objects.bulk_update(
                to_update,
                self.UPSERT_FIELDS,
                batch_size=self.BULK_BATCH_SIZE,
            )

        # Новые карточки — для авто-простановки ИНН после синка
        return [
            {
                "bitrix_id": obj.bitrix_id,
                "project_id": obj.project_id,
                "project_item_id": obj.project_item_id,
            }
            for obj in to_create
        ]

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
