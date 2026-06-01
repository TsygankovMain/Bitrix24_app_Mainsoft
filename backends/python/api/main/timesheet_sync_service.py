import logging
import time
from typing import Any, Dict, List, Optional

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
    SCOPED_SAVE_CHUNK = 500
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

    def sync_all(self, date_from: Optional[str] = None, date_to: Optional[str] = None) -> int:
        """Синхронизация записей трудозатрат из Битрикс24.

        Если переданы обе даты и маппинг поля даты задан — выполняется быстрый
        scoped-синк только по периоду (два фильтра + батч-офсеты). При ошибке
        в scoped-пути автоматически выполняется полный синк (фолбэк).
        """
        logger.info("Starting sync for account %s (date_from=%s, date_to=%s)", self.account.pk, date_from, date_to)

        if not self.entity_type_id:
            logger.error("No SP Entity Type ID configured cannot sync.")
            return 0

        fdate = self.processing_service.mapping.get("data")
        scoped = bool(date_from and date_to and fdate and self.entity_type_id)

        if scoped:
            try:
                return self._sync_scoped(date_from, date_to, fdate)
            except Exception as exc:
                logger.warning(
                    "Scoped sync failed (date_from=%s, date_to=%s), falling back to full sync. Error: %s",
                    date_from,
                    date_to,
                    exc,
                )

        return self._sync_full()

    def _sync_full(self) -> int:
        """Полный keyset-синк (без изменений по сравнению с исходным sync_all)."""
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

    def _sync_scoped(self, date_from: str, date_to: str, fdate: str) -> int:
        """Быстрый синк только за период [date_from, date_to].

        Собирает ОБЪЕДИНЕНИЕ двух выборок по полю даты-отражения и по createdTime,
        дедуплицирует по id, сохраняет через _save_batch, удаляет из БД только
        записи внутри окна, которые не вернул Битрикс24.
        """
        logger.info(
            "Running scoped sync for account %s, period %s – %s (fdate=%s)",
            self.account.pk, date_from, date_to, fdate,
        )

        # Выборка A: по полю даты-отражения
        filter_a = {f">={fdate}": date_from, f"<={fdate}": date_to}
        items_a = self._fetch_all_pages_batched(filter_a)
        logger.info("Scoped fetch A (%s) returned %s items", fdate, len(items_a))

        # Выборка B: по createdTime
        filter_b = {">=createdTime": date_from, "<=createdTime": date_to}
        items_b = self._fetch_all_pages_batched(filter_b)
        logger.info("Scoped fetch B (createdTime) returned %s items", len(items_b))

        # Дедупликация по str(id)
        union: Dict[str, Dict[str, Any]] = {}
        for item in items_a:
            key = str(item.get("id", ""))
            if key:
                union[key] = item
        for item in items_b:
            key = str(item.get("id", ""))
            if key:
                union.setdefault(key, item)

        union_items = list(union.values())
        fetched_ids = set(union.keys())
        logger.info("Scoped union: %s unique items", len(union_items))

        # Нормализация и сохранение чанками
        normalized = self.processing_service.normalize_items(union_items)
        all_new_cards: List[Dict[str, Any]] = []
        chunk_size = self.SCOPED_SAVE_CHUNK
        for i in range(0, max(1, len(normalized)), chunk_size):
            chunk = normalized[i:i + chunk_size]
            if chunk:
                new_cards = self._save_batch(chunk)
                all_new_cards.extend(new_cards)

        # Scoped-сверка удалений: только внутри окна
        self._delete_scoped_orphans(date_from, date_to, fetched_ids)

        self._autofill_inn(all_new_cards)

        logger.info("Scoped sync complete. Total unique items: %s", len(union_items))
        return len(union_items)

    def _fetch_all_pages_batched(self, filter_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Получает ВСЕ страницы crm.item.list для заданного фильтра.

        Первая страница — одиночный _call_with_retry (start=0), затем если
        total > 50 — строит словарь офсетов и вызывает call_batches одним
        запросом. Разбор ответа батча — оборонительный.
        """
        base_params: Dict[str, Any] = {
            "entityTypeId": self.entity_type_id,
            "select": ["*", "UF_*"],
            "order": {"id": "ASC"},
            "filter": filter_dict,
            "start": 0,
        }

        # Первая страница
        first_response = self._call_with_retry("crm.item.list", base_params)
        first_items = self._extract_items(first_response)

        # total — на верхнем уровне ответа (см. views.py ~1985-1986)
        result_root = first_response.get("result", {})
        total = first_response.get("total", result_root.get("total", 0) if isinstance(result_root, dict) else 0)
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(first_items)

        all_items: List[Dict[str, Any]] = list(first_items)

        if total <= 50:
            return all_items

        # Батчевые офсеты для оставшихся страниц
        offsets = list(range(50, total, 50))
        methods = {
            f"p{off}": (
                "crm.item.list",
                {
                    "entityTypeId": self.entity_type_id,
                    "select": ["*", "UF_*"],
                    "order": {"id": "ASC"},
                    "filter": filter_dict,
                    "start": off,
                },
            )
            for off in offsets
        }

        logger.info(
            "Fetching %s batch-offset pages (total=%s) for filter %s",
            len(offsets), total, list(filter_dict.keys()),
        )

        batches_resp = self.client._bitrix_token.call_batches(methods, halt=False)

        # call_batches возвращает:
        #   batches_resp["result"]["result"][key] = содержимое response["result"]
        #   одиночного crm.item.list, т.е. {"items": [...], ...}
        try:
            sub_results = batches_resp.get("result", {}).get("result", {})
        except Exception:
            sub_results = {}

        if not isinstance(sub_results, dict):
            # Если вдруг list — конвертируем
            try:
                sub_results = {str(i): v for i, v in enumerate(sub_results)}
            except Exception:
                sub_results = {}

        for key, sub_result in sub_results.items():
            try:
                # sub_result — это то, что было в response["result"] одиночного вызова,
                # т.е. {"items": [...]} или просто список
                page_items = self._extract_items({"result": sub_result})
                all_items.extend(page_items)
            except Exception as exc:
                logger.warning("Could not parse batch sub-result for key=%s: %s", key, exc)
                continue

        return all_items

    def _delete_scoped_orphans(
        self, date_from: str, date_to: str, fetched_ids: set
    ) -> None:
        """Удаляет записи внутри окна [date_from, date_to], которых нет в fetched_ids.

        Записи за пределами окна НЕ трогает. ВАЖНО: если из Битрикс за период не
        получено ни одной записи (пустой fetched_ids) — удаление ПРОПУСКАЕТСЯ
        (защита от потери данных при сбое выборки/парсинга батча; реальная
        очистка пустого периода произойдёт при следующем полном синке).
        """
        if not fetched_ids:
            logger.info(
                "Scoped: fetched 0 items for window %s – %s; skip deletion (safety).",
                date_from, date_to,
            )
            return

        # bitrix_id в БД — целое; нормализуем id выборки в int (исключаем нечисловые)
        int_ids = set()
        for x in fetched_ids:
            try:
                int_ids.add(int(x))
            except (TypeError, ValueError):
                continue
        if not int_ids:
            logger.warning("Scoped: no valid integer ids in fetch; skip deletion (safety).")
            return

        try:
            deleted_count, _ = (
                TimesheetItem.objects.filter(
                    bitrix24_account=self.account,
                    date_reflection__date__gte=date_from,
                    date_reflection__date__lte=date_to,
                )
                .exclude(bitrix_id__in=int_ids)
                .delete()
            )
            if deleted_count > 0:
                logger.info(
                    "Scoped: deleted %s orphaned records in window %s – %s",
                    deleted_count, date_from, date_to,
                )
        except Exception as exc:
            logger.warning("Scoped orphan deletion failed: %s", exc)

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
