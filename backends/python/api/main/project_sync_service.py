import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client
from django.db.models import Q
from django.utils import timezone

from .bitrix_data_access import BitrixDataService
from .configuration_service import ConfigurationService
from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .project_board_service import ProjectCardService
from .project_board_shared import (
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NEW,
    build_local_project_groups,
    ensure_project_card_schema,
    get_project_card_queryset,
    invalidate_project_runtime_caches,
)
from .stage_automation_service import ProjectStageAutomationService


logger = logging.getLogger(__name__)


class ProjectSyncService:
    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account
        self.card_service = ProjectCardService(client, account)

    def sync(self, incremental_since_minutes: Optional[int] = None) -> Dict[str, Any]:
        warning: Optional[str] = None
        sync_mode = "groups"
        skipped_missing_group_link = 0
        skipped_conflict_linking = 0
        schema_ready = ensure_project_card_schema()
        by_project_item_id, by_project_id, by_project_title = self.card_service.collect_writeoff_maps()
        stage_lookup = self.card_service.get_project_stage_lookup()
        created = 0
        updated = 0
        synced_total = 0
        incremental_from: Optional[datetime] = None
        incremental_minutes = 0
        try:
            incremental_minutes = int(incremental_since_minutes or 0)
        except (TypeError, ValueError):
            incremental_minutes = 0
        if incremental_minutes > 0:
            incremental_from = timezone.now() - timedelta(minutes=incremental_minutes)

        project_sp_entity_type_id, project_fields_mapping = self._load_project_sp_config()

        if project_sp_entity_type_id:
            try:
                project_items = self.fetch_project_sp_items(project_sp_entity_type_id, updated_since=incremental_from)
                sync_mode = "project_spa_incremental" if incremental_from else "project_spa"
                synced_total = len(project_items)
                if schema_ready:
                    created, updated, skipped_missing_group_link, skipped_conflict_linking = self._sync_from_project_sp_items(
                        project_items,
                        project_fields_mapping,
                        by_project_item_id,
                        by_project_id,
                        by_project_title,
                        stage_lookup,
                    )
                else:
                    warning = (
                        "Локальная таблица проектов недоступна, поэтому данные Project SPA пока не сохраняются в проекцию. "
                        "После завершения миграции синхронизация начнет работать в полном режиме."
                    )
                if skipped_missing_group_link > 0:
                    warning = (
                        f"Часть проектов из SPA не синхронизирована: {skipped_missing_group_link} "
                        "элементов без связи с Bitrix group/project."
                    )
                if skipped_conflict_linking > 0:
                    conflict_warning = (
                        f"Пропущены конфликтные связи group_id <-> project_item_id: {skipped_conflict_linking}. "
                        "Исправьте дубликаты в Project SPA."
                    )
                    warning = f"{warning} {conflict_warning}".strip() if warning else conflict_warning
            except Exception as exc:
                logger.warning("Project SPA sync failed, falling back to group sync: %s", exc)
                warning = (
                    "Не удалось получить проекты из Smart Process ПРОЕКТ. "
                    "Применен fallback по группам Bitrix24."
                )

        if not sync_mode.startswith("project_spa"):
            try:
                groups = self.fetch_project_groups()
            except Exception as exc:
                logger.warning("Project sync Bitrix fetch failed, falling back to local timesheets: %s", exc)
                groups = build_local_project_groups(self.account)
                local_warning = (
                    "Не удалось получить список проектов напрямую из Битрикс24. "
                    "Использован локальный список по уже загруженным списаниям."
                )
                warning = f"{warning} {local_warning}".strip() if warning else local_warning

            sync_mode = "groups"
            synced_total = len(groups)
            if schema_ready:
                created, updated = self._sync_from_groups(groups, by_project_id, by_project_title)
            else:
                local_warning = (
                    "Локальная таблица проектов недоступна, поэтому sync выполнен без сохранения карточек. "
                    "После миграции данные начнут записываться в локальную проекцию."
                )
                warning = f"{warning} {local_warning}".strip() if warning else local_warning

        if schema_ready:
            self.card_service.refresh_writeoff_stats()
        daily_check = ProjectStageAutomationService(self.account).run_daily_check()

        result = {
            "status": "success",
            "sync_mode": sync_mode,
            "synced": synced_total,
            "created": created,
            "updated": updated,
            "skipped_missing_group_link": skipped_missing_group_link,
            "skipped_conflict_linking": skipped_conflict_linking,
            **daily_check,
        }
        if incremental_from:
            result["incremental_from"] = incremental_from.isoformat()
        if warning:
            result["warning"] = warning

        invalidate_project_runtime_caches(self.account)
        return result

    def _sync_from_groups(
        self,
        groups: List[Dict[str, Any]],
        by_project_id: Dict[str, datetime],
        by_project_title: Dict[str, datetime],
    ) -> Tuple[int, int]:
        owner_ids = {
            str(group.get("OWNER_ID") or group.get("ownerId") or "").strip()
            for group in groups
            if group.get("OWNER_ID") or group.get("ownerId")
        }
        user_map = BitrixDataService(self.client, {}, self.account).fetch_users(list(owner_ids))

        if not ensure_project_card_schema():
            return 0, 0

        existing_cards = {card.project_id: card for card in get_project_card_queryset(self.account)}
        created = 0
        updated = 0

        for group in groups:
            normalized = self.normalize_project_group(group, user_map, by_project_id, by_project_title)
            project_id = normalized["project_id"]
            if not project_id:
                continue

            existing = existing_cards.get(project_id)
            if existing is None:
                ProjectCard.objects.create(
                    bitrix24_account=self.account,
                    project_id=project_id,
                    project_name=normalized["project_name"],
                    stage=normalized["initial_stage"],
                    manual_stage=normalized["initial_stage"],
                    is_archived=normalized["is_archived"],
                    archived_at=timezone.now() if normalized["is_archived"] else None,
                    curator_user_id=normalized["curator_user_id"],
                    curator_name=normalized["curator_name"],
                    project_start_date=normalized["project_start_date"],
                    project_end_date=normalized["project_end_date"],
                    last_writeoff_at=normalized["last_writeoff_at"],
                    last_writeoff_days=normalized["last_writeoff_days"],
                    stage_source="manual",
                )
                created += 1
                continue

            changed_fields: List[str] = []
            if normalized["project_name"] and existing.project_name != normalized["project_name"]:
                existing.project_name = normalized["project_name"]
                changed_fields.append("project_name")
            if not existing.curator_user_id and normalized["curator_user_id"]:
                existing.curator_user_id = normalized["curator_user_id"]
                changed_fields.append("curator_user_id")
            if not existing.curator_name and normalized["curator_name"]:
                existing.curator_name = normalized["curator_name"]
                changed_fields.append("curator_name")
            if not existing.project_start_date and normalized["project_start_date"]:
                existing.project_start_date = normalized["project_start_date"]
                changed_fields.append("project_start_date")
            if not existing.project_end_date and normalized["project_end_date"]:
                existing.project_end_date = normalized["project_end_date"]
                changed_fields.append("project_end_date")
            if not existing.manual_stage:
                existing.manual_stage = normalized["initial_stage"]
                changed_fields.append("manual_stage")
            if not existing.stage:
                existing.stage = existing.manual_stage or normalized["initial_stage"]
                changed_fields.append("stage")
            if normalized["is_archived"] and not existing.is_archived:
                existing.is_archived = True
                existing.archived_at = existing.archived_at or timezone.now()
                changed_fields.extend(["is_archived", "archived_at"])

            if changed_fields:
                changed_fields.append("updated_at")
                existing.save(update_fields=changed_fields)
                updated += 1

        return created, updated

    def _sync_from_project_sp_items(
        self,
        project_items: List[Dict[str, Any]],
        mapping: Dict[str, str],
        by_project_item_id: Dict[str, datetime],
        by_project_id: Dict[str, datetime],
        by_project_title: Dict[str, datetime],
        stage_lookup: Dict[str, Dict[str, Any]],
    ) -> Tuple[int, int, int, int]:
        if not ensure_project_card_schema():
            return 0, 0, 0, 0

        normalized_items = [
            self.normalize_project_item(project_item, mapping, by_project_item_id, by_project_id, by_project_title, stage_lookup)
            for project_item in project_items
        ]

        curator_ids = [item["curator_user_id"] for item in normalized_items if item.get("curator_user_id")]
        user_map = BitrixDataService(self.client, {}, self.account).fetch_users(curator_ids)

        existing_cards = list(get_project_card_queryset(self.account))
        existing_by_group = {card.project_id: card for card in existing_cards if card.project_id}
        existing_by_item = {card.project_item_id: card for card in existing_cards if card.project_item_id}

        created = 0
        updated = 0
        skipped_missing_group_link = 0
        skipped_conflict_linking = 0
        group_to_items: Dict[str, set] = {}
        item_to_groups: Dict[str, set] = {}
        for normalized in normalized_items:
            bitrix_group_id = normalized.get("project_id")
            project_item_id = normalized.get("project_item_id")
            if not bitrix_group_id or not project_item_id:
                continue
            group_to_items.setdefault(bitrix_group_id, set()).add(project_item_id)
            item_to_groups.setdefault(project_item_id, set()).add(bitrix_group_id)
        conflicting_groups = {group_id for group_id, item_ids in group_to_items.items() if len(item_ids) > 1}
        conflicting_items = {item_id for item_id, group_ids in item_to_groups.items() if len(group_ids) > 1}
        for item_id in conflicting_items:
            conflicting_groups.update(item_to_groups.get(item_id, set()))

        for normalized in normalized_items:
            project_item_id = normalized.get("project_item_id")
            bitrix_group_id = normalized.get("project_id")
            if not bitrix_group_id:
                skipped_missing_group_link += 1
                continue
            if bitrix_group_id in conflicting_groups or (project_item_id and project_item_id in conflicting_items):
                skipped_conflict_linking += 1
                continue

            existing: Optional[ProjectCard] = None
            if project_item_id:
                existing = existing_by_item.get(project_item_id)
            if existing is None:
                existing = existing_by_group.get(bitrix_group_id)

            if normalized.get("curator_user_id") and not normalized.get("curator_name"):
                normalized["curator_name"] = user_map.get(normalized["curator_user_id"])

            if existing is None:
                card = ProjectCard.objects.create(
                    bitrix24_account=self.account,
                    project_item_id=project_item_id,
                    project_id=bitrix_group_id,
                    project_name=normalized["project_name"],
                    stage=normalized["stage"],
                    manual_stage=normalized["manual_stage"],
                    is_archived=normalized["is_archived"],
                    archived_at=timezone.now() if normalized["is_archived"] else None,
                    project_hours_budget=normalized.get("project_hours_budget"),
                    hourly_rate=normalized.get("hourly_rate") or 0.0,
                    is_support=normalized.get("is_support", False),
                    project_type=normalized.get("project_type"),
                    budget_mode=normalized.get("budget_mode"),
                    planned_budget_amount=normalized.get("planned_budget_amount"),
                    curator_user_id=normalized.get("curator_user_id"),
                    curator_name=normalized.get("curator_name"),
                    company_id=normalized.get("company_id"),
                    company_name=normalized.get("company_name"),
                    our_legal_entity_id=normalized.get("our_legal_entity_id"),
                    our_legal_entity_name=normalized.get("our_legal_entity_name"),
                    project_start_date=normalized.get("project_start_date"),
                    project_end_date=normalized.get("project_end_date"),
                    last_writeoff_at=normalized.get("last_writeoff_at"),
                    last_writeoff_days=normalized.get("last_writeoff_days", 0),
                    stage_source=normalized.get("stage_source", "manual"),
                )
                created += 1
                if card.project_id:
                    existing_by_group[card.project_id] = card
                if card.project_item_id:
                    existing_by_item[card.project_item_id] = card
                continue

            changed_fields: List[str] = []
            self._set_if_changed(existing, "project_item_id", project_item_id, changed_fields)
            self._set_if_changed(existing, "project_id", bitrix_group_id, changed_fields)
            self._set_if_changed(existing, "project_name", normalized["project_name"], changed_fields)
            self._set_if_changed(existing, "stage", normalized["stage"], changed_fields)
            self._set_if_changed(existing, "manual_stage", normalized["manual_stage"], changed_fields)
            self._set_if_changed(existing, "is_archived", normalized["is_archived"], changed_fields)
            self._set_if_changed(existing, "project_hours_budget", normalized.get("project_hours_budget"), changed_fields)
            self._set_if_changed(existing, "hourly_rate", normalized.get("hourly_rate") or 0.0, changed_fields)
            self._set_if_changed(existing, "is_support", normalized.get("is_support", False), changed_fields)
            self._set_if_changed(existing, "project_type", normalized.get("project_type"), changed_fields)
            self._set_if_changed(existing, "budget_mode", normalized.get("budget_mode"), changed_fields)
            self._set_if_changed(existing, "planned_budget_amount", normalized.get("planned_budget_amount"), changed_fields)
            self._set_if_changed(existing, "curator_user_id", normalized.get("curator_user_id"), changed_fields)
            self._set_if_changed(existing, "curator_name", normalized.get("curator_name"), changed_fields)
            self._set_if_changed(existing, "company_id", normalized.get("company_id"), changed_fields)
            self._set_if_changed(existing, "company_name", normalized.get("company_name"), changed_fields)
            self._set_if_changed(existing, "our_legal_entity_id", normalized.get("our_legal_entity_id"), changed_fields)
            self._set_if_changed(existing, "our_legal_entity_name", normalized.get("our_legal_entity_name"), changed_fields)
            self._set_if_changed(existing, "project_start_date", normalized.get("project_start_date"), changed_fields)
            self._set_if_changed(existing, "project_end_date", normalized.get("project_end_date"), changed_fields)
            self._set_if_changed(existing, "last_writeoff_at", normalized.get("last_writeoff_at"), changed_fields)
            self._set_if_changed(existing, "last_writeoff_days", normalized.get("last_writeoff_days", 0), changed_fields)
            self._set_if_changed(existing, "stage_source", normalized.get("stage_source", "manual"), changed_fields)

            archived_at = (existing.archived_at or timezone.now()) if normalized["is_archived"] else None
            self._set_if_changed(existing, "archived_at", archived_at, changed_fields)

            if changed_fields:
                changed_fields.append("updated_at")
                existing.save(update_fields=changed_fields)
                updated += 1
                if existing.project_id:
                    existing_by_group[existing.project_id] = existing
                if existing.project_item_id:
                    existing_by_item[existing.project_item_id] = existing

        return created, updated, skipped_missing_group_link, skipped_conflict_linking

    def fetch_project_sp_items(self, entity_type_id: int, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        start = 0
        items: List[Dict[str, Any]] = []
        filter_enabled = updated_since is not None
        filter_payload = {">updatedTime": updated_since.isoformat()} if updated_since else None

        while True:
            request_payload: Dict[str, Any] = {
                "entityTypeId": int(entity_type_id),
                "select": ["id", "title", "createdTime", "updatedTime", "*", "UF_*"],
                "start": start,
            }
            if filter_enabled and filter_payload:
                request_payload["filter"] = filter_payload

            try:
                response = self.client._bitrix_token.call_method("crm.item.list", request_payload)
            except Exception as exc:
                if filter_enabled:
                    logger.warning("Incremental Project SPA filter failed, retrying full list: %s", exc)
                    filter_enabled = False
                    start = 0
                    items = []
                    continue
                raise
            batch, next_value = self.extract_items_from_response(response)
            if not batch:
                break
            items.extend(batch)
            if next_value is None or int(next_value) <= start:
                break
            start = int(next_value)

        return items

    def _load_project_sp_config(self) -> Tuple[int, Dict[str, str]]:
        config = ConfigurationService(self.client, self.account).get_configuration_sync()
        try:
            entity_type_id = int(config.get("project_sp_entity_type_id") or 0)
        except (TypeError, ValueError):
            entity_type_id = 0
        mapping = config.get("project_fields_mapping") or {}
        if not isinstance(mapping, dict):
            mapping = {}
        return entity_type_id, mapping

    def normalize_project_item(
        self,
        item: Dict[str, Any],
        mapping: Dict[str, str],
        by_project_item_id: Dict[str, datetime],
        by_project_id: Dict[str, datetime],
        by_project_title: Dict[str, datetime],
        stage_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        project_item_id = self._clean_str(item.get("id") or item.get("ID"))
        group_value = self._get_mapped_value(item, mapping, "bitrix_group_id", "UF_CRM_BITRIX_GROUP_ID", "ufCrmBitrixGroupId")
        project_id = self._extract_scalar(group_value)

        title_value = self._get_mapped_value(item, mapping, "title", "TITLE", "title")
        project_name = self._extract_scalar(title_value) or f"Проект {project_id or project_item_id or 'без имени'}"

        curator_value = self._get_mapped_value(item, mapping, "curator_id", "UF_CRM_CURATOR_ID", "ufCrmCuratorId")
        curator_user_id = self._extract_scalar(curator_value)
        company_value = self._get_mapped_value(item, mapping, "company_id", "UF_CRM_COMPANY_ID", "ufCrmCompanyId")
        company_id = self._extract_scalar(company_value)
        legal_value = self._get_mapped_value(item, mapping, "our_legal_entity_id", "UF_CRM_OUR_LEGAL_ENTITY_ID", "ufCrmOurLegalEntityId")
        legal_entity_id = self._extract_scalar(legal_value)

        company_name = self._extract_scalar(self._get_mapped_value(item, mapping, "company_name", "UF_CRM_COMPANY_NAME", "ufCrmCompanyName"))
        legal_entity_name = self._extract_scalar(
            self._get_mapped_value(item, mapping, "our_legal_entity_name", "UF_CRM_OUR_LEGAL_ENTITY_NAME", "ufCrmOurLegalEntityName")
        )
        manual_stage = self._extract_scalar(self._get_mapped_value(item, mapping, "manual_stage", "UF_CRM_STAGE_MANUAL", "ufCrmStageManual"))
        effective_stage = self._extract_scalar(
            self._get_mapped_value(
                item,
                mapping,
                "stage_id",
                "stage",
                "effective_stage",
                "UF_CRM_STAGE_ID",
                "UF_CRM_EFFECTIVE_STAGE",
                "ufCrmEffectiveStage",
                "stageId",
                "STAGE_ID",
            )
        )
        is_archived = ProjectCardService._to_bool(
            self._get_mapped_value(item, mapping, "is_archived", "UF_CRM_IS_ARCHIVED", "ufCrmIsArchived"),
            default=False,
        )
        is_support = ProjectCardService._to_bool(
            self._get_mapped_value(item, mapping, "is_support", "UF_CRM_IS_SUPPORT", "ufCrmIsSupport"),
            default=False,
        )
        budget = ProjectCardService._to_optional_float(
            self._get_mapped_value(item, mapping, "project_hours_budget", "UF_CRM_PROJECT_HOURS_BUDGET", "ufCrmProjectHoursBudget")
        )
        project_type = self._extract_scalar(
            self._get_mapped_value(item, mapping, "project_type", "UF_CRM_PROJECT_TYPE", "ufCrmProjectType")
        )
        budget_mode = self._extract_scalar(
            self._get_mapped_value(item, mapping, "budget_mode", "UF_CRM_BUDGET_MODE", "ufCrmBudgetMode")
        )
        planned_budget_amount = ProjectCardService._to_optional_float(
            self._get_mapped_value(
                item,
                mapping,
                "planned_budget_amount",
                "UF_CRM_PLANNED_BUDGET_AMOUNT",
                "ufCrmPlannedBudgetAmount",
            )
        )
        hourly_rate = ProjectCardService._to_float(
            self._get_mapped_value(item, mapping, "hourly_rate", "UF_CRM_HOURLY_RATE", "ufCrmHourlyRate"),
            default=0.0,
        )
        start_date = ProjectCardService._parse_date(
            self._get_mapped_value(item, mapping, "start_date", "UF_CRM_START_DATE", "ufCrmStartDate", "projectDateStart", "PROJECT_DATE_START")
        )
        finish_date = ProjectCardService._parse_date(
            self._get_mapped_value(item, mapping, "finish_date", "UF_CRM_FINISH_DATE", "ufCrmFinishDate", "projectDateFinish", "PROJECT_DATE_FINISH")
        )

        last_writeoff_at = by_project_item_id.get(project_item_id) if project_item_id else None
        if project_id:
            last_writeoff_at = last_writeoff_at or by_project_id.get(project_id)
        if last_writeoff_at is None and project_name:
            last_writeoff_at = by_project_title.get(project_name)
        last_writeoff_days = (timezone.localdate() - last_writeoff_at.date()).days if last_writeoff_at else 0

        normalized_manual_stage = self.card_service.resolve_project_stage_title(manual_stage, stage_lookup) if manual_stage else None
        normalized_effective_stage = self.card_service.resolve_project_stage_title(effective_stage, stage_lookup) if effective_stage else None
        if normalized_manual_stage is None:
            normalized_manual_stage = normalized_effective_stage or (PROJECT_STAGE_IN_WORK if last_writeoff_at else PROJECT_STAGE_NEW)
        if normalized_effective_stage is None:
            normalized_effective_stage = normalized_manual_stage
        stage_source = "auto" if normalized_effective_stage != normalized_manual_stage else "manual"

        company_id, company_name = self.card_service._resolve_company_reference(company_id, company_name)
        legal_entity_id, legal_entity_name = self.card_service._resolve_legal_entity_reference(legal_entity_id, legal_entity_name)
        if not project_type:
            project_type = "support" if is_support else "delivery"
        if not budget_mode:
            budget_mode = "support" if is_support else "hours_and_amount"

        return {
            "project_item_id": project_item_id,
            "project_id": project_id,
            "project_name": project_name,
            "stage": normalized_effective_stage,
            "manual_stage": normalized_manual_stage,
            "stage_source": stage_source,
            "is_archived": is_archived,
            "is_support": is_support,
            "project_hours_budget": budget,
            "project_type": project_type,
            "budget_mode": budget_mode,
            "planned_budget_amount": planned_budget_amount,
            "hourly_rate": hourly_rate,
            "curator_user_id": curator_user_id,
            "curator_name": None,
            "company_id": company_id,
            "company_name": company_name,
            "our_legal_entity_id": legal_entity_id,
            "our_legal_entity_name": legal_entity_name,
            "project_start_date": start_date,
            "project_end_date": finish_date,
            "last_writeoff_at": last_writeoff_at,
            "last_writeoff_days": last_writeoff_days,
        }

    def backfill_timesheet_project_items(self, batch_size: int = 1000) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            return {"status": "skipped", "updated": 0, "unresolved": 0, "scanned": 0}

        project_cards = (
            get_project_card_queryset(self.account)
            .exclude(project_item_id__isnull=True)
            .exclude(project_item_id="")
            .values("project_id", "project_name", "project_item_id")
        )
        by_project_id = {
            self._clean_str(card.get("project_id")): self._clean_str(card.get("project_item_id"))
            for card in project_cards
            if self._clean_str(card.get("project_id")) and self._clean_str(card.get("project_item_id"))
        }
        by_project_name = {
            self._clean_str(card.get("project_name")): self._clean_str(card.get("project_item_id"))
            for card in project_cards
            if self._clean_str(card.get("project_name")) and self._clean_str(card.get("project_item_id"))
        }

        queryset = TimesheetItem.objects.filter(bitrix24_account=self.account).filter(
            Q(project_item_id__isnull=True) | Q(project_item_id="")
        )
        scanned = 0
        updated = 0
        unresolved = 0
        pending: List[TimesheetItem] = []

        for item in queryset.iterator(chunk_size=batch_size):
            scanned += 1
            project_item_id = (
                by_project_id.get(self._clean_str(item.project_id))
                or by_project_name.get(self._clean_str(item.project_title))
            )
            if not project_item_id:
                unresolved += 1
                continue
            item.project_item_id = project_item_id
            pending.append(item)
            if len(pending) >= batch_size:
                TimesheetItem.objects.bulk_update(pending, ["project_item_id"])
                updated += len(pending)
                pending = []

        if pending:
            TimesheetItem.objects.bulk_update(pending, ["project_item_id"])
            updated += len(pending)

        return {
            "status": "success",
            "scanned": scanned,
            "updated": updated,
            "unresolved": unresolved,
        }

    def fetch_project_groups(self) -> List[Dict[str, Any]]:
        errors: List[str] = []
        for fetcher in (self._fetch_project_groups_via_sonet_group, self._fetch_project_groups_via_socialnetwork):
            try:
                groups = fetcher()
                if groups:
                    return groups
            except Exception as exc:
                error_text = str(exc)
                errors.append(error_text)
                logger.warning("Project sync fetcher %s failed: %s", fetcher.__name__, error_text)

        if errors:
            raise RuntimeError(f"Не удалось загрузить проекты из Битрикс24: {' | '.join(errors)}")
        return []

    def _fetch_project_groups_via_sonet_group(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page = 1
        page_size = 50

        while True:
            response = self.client._bitrix_token.call_method(
                "sonet_group.get",
                {
                    # В Битрикс24 "группа" и "проект" — по сути одно и то же для бюджетного модуля.
                    # Синхронизируем все SonetGroup, а не только PROJECT=Y, иначе карточка
                    # для обычных рабочих групп не создаётся и /project-board/card отдаёт 404.
                    "SELECT": [
                        "ID",
                        "NAME",
                        "PROJECT",
                        "CLOSED",
                        "OWNER_ID",
                        "PROJECT_DATE_START",
                        "PROJECT_DATE_FINISH",
                    ],
                    "NAV_PARAMS": {"nPageSize": page_size, "iNumPage": page},
                },
            )
            batch, _ = self.extract_items_from_response(response)
            if not batch:
                break

            for item in batch:
                items.append(item)

            if len(batch) < page_size:
                break
            page += 1

        return items

    def _fetch_project_groups_via_socialnetwork(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        start = 0

        while True:
            response = self.client._bitrix_token.call_method(
                "socialnetwork.api.workgroup.list",
                {
                    # См. комментарий в _fetch_project_groups_via_sonet_group:
                    # тянем все группы, не только PROJECT=Y.
                    "select": [
                        "ID",
                        "NAME",
                        "PROJECT",
                        "CLOSED",
                        "OWNER_ID",
                        "PROJECT_DATE_START",
                        "PROJECT_DATE_FINISH",
                    ],
                    "start": start,
                },
            )
            batch, next_value = self.extract_items_from_response(response)
            if not batch:
                break

            for item in batch:
                items.append(item)

            if next_value is None or int(next_value) <= start:
                break
            start = int(next_value)

        return items

    def normalize_project_group(
        self,
        group: Dict[str, Any],
        user_map: Dict[str, str],
        by_project_id: Dict[str, datetime],
        by_project_title: Dict[str, datetime],
    ) -> Dict[str, Any]:
        project_id = self._clean_str(self._get_first(group, "ID", "id"))
        project_name = self._get_first(group, "NAME", "name") or f"Проект {project_id}"
        curator_user_id = self._clean_str(self._get_first(group, "OWNER_ID", "ownerId"))
        last_writeoff_at = (by_project_id.get(project_id) if project_id else None) or by_project_title.get(project_name)
        last_writeoff_days = (timezone.localdate() - last_writeoff_at.date()).days if last_writeoff_at else 0
        initial_stage = PROJECT_STAGE_IN_WORK if last_writeoff_at else PROJECT_STAGE_NEW

        return {
            "project_id": project_id,
            "project_name": project_name,
            "curator_user_id": curator_user_id,
            "curator_name": user_map.get(curator_user_id) if curator_user_id else None,
            "project_start_date": ProjectCardService._parse_date(self._get_first(group, "PROJECT_DATE_START", "projectDateStart")),
            "project_end_date": ProjectCardService._parse_date(self._get_first(group, "PROJECT_DATE_FINISH", "projectDateFinish")),
            "is_archived": ProjectCardService._to_bool(self._get_first(group, "CLOSED", "closed"), default=False),
            "last_writeoff_at": last_writeoff_at,
            "last_writeoff_days": last_writeoff_days,
            "initial_stage": initial_stage,
        }

    @staticmethod
    def extract_items_from_response(response: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        result = response.get("result", [])
        next_value = response.get("next")

        if isinstance(result, dict):
            items = result.get("items")
            if items is None:
                items = result.get("result", [])
            if next_value is None:
                next_value = result.get("next")
        else:
            items = result

        if not isinstance(items, list):
            items = []
        if next_value in ("", False):
            next_value = None

        return items, int(next_value) if next_value is not None else None

    @staticmethod
    def _get_first(source: Dict[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str:
                return value_str
        return None

    @staticmethod
    def _is_project(item: Dict[str, Any]) -> bool:
        project_flag = item.get("PROJECT")
        if project_flag is None:
            return True
        return ProjectCardService._to_bool(project_flag, default=False)

    @staticmethod
    def _set_if_changed(card: ProjectCard, field_name: str, next_value: Any, changed_fields: List[str]) -> None:
        if getattr(card, field_name) != next_value:
            setattr(card, field_name, next_value)
            changed_fields.append(field_name)

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @staticmethod
    def _extract_scalar(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, list):
            if not value:
                return None
            return ProjectSyncService._extract_scalar(value[0])
        if isinstance(value, dict):
            for key in ("id", "ID", "value", "VALUE"):
                if key in value:
                    return ProjectSyncService._extract_scalar(value.get(key))
            return None
        return ProjectSyncService._clean_str(value)

    @staticmethod
    def _get_mapped_value(item: Dict[str, Any], mapping: Dict[str, str], mapping_key: str, *fallback_fields: str) -> Any:
        configured_field = mapping.get(mapping_key)
        candidates = [configured_field, *fallback_fields]
        for field_name in candidates:
            if not field_name:
                continue
            if field_name in item:
                value = item.get(field_name)
                if value not in (None, ""):
                    return value
        return None
