import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from b24pysdk import Client
from django.utils import timezone

from .bitrix_data_access import BitrixDataService
from .models import Bitrix24Account, ProjectCard
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

    def sync(self) -> Dict[str, Any]:
        warning: Optional[str] = None

        try:
            groups = self.fetch_project_groups()
        except Exception as exc:
            logger.warning("Project sync Bitrix fetch failed, falling back to local timesheets: %s", exc)
            groups = build_local_project_groups(self.account)
            warning = (
                "Не удалось получить список проектов напрямую из Битрикс24. "
                "Использован локальный список по уже загруженным списаниям."
            )

        by_project_id, by_project_title = self.card_service.collect_writeoff_maps()
        owner_ids = {
            str(group.get("OWNER_ID") or group.get("ownerId") or "").strip()
            for group in groups
            if group.get("OWNER_ID") or group.get("ownerId")
        }
        user_map = BitrixDataService(self.client, {}, self.account).fetch_users(list(owner_ids))

        if not ensure_project_card_schema():
            daily_check = ProjectStageAutomationService(self.account).run_daily_check()
            invalidate_project_runtime_caches(self.account)
            result = {
                "status": "success",
                "synced": len(groups),
                "created": 0,
                "updated": 0,
                **daily_check,
                "warning": (
                    "Локальная таблица проектов недоступна, поэтому board собран без сохранения карточек. "
                    "После завершения миграции синхронизация начнет сохранять метаданные."
                ),
            }
            if warning:
                result["warning"] = f"{result['warning']} {warning}"
            return result

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

        self.card_service.refresh_writeoff_stats()
        daily_check = ProjectStageAutomationService(self.account).run_daily_check()

        result = {
            "status": "success",
            "synced": len(groups),
            "created": created,
            "updated": updated,
            **daily_check,
        }
        if warning:
            result["warning"] = warning

        invalidate_project_runtime_caches(self.account)
        return result

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
                    "FILTER": {"PROJECT": "Y"},
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
                if self._is_project(item):
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
                    "filter": {"PROJECT": "Y"},
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
                if self._is_project(item):
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
        project_id = self._get_first(group, "ID", "id")
        project_name = self._get_first(group, "NAME", "name") or f"Проект {project_id}"
        curator_user_id = self._get_first(group, "OWNER_ID", "ownerId")
        last_writeoff_at = by_project_id.get(project_id) or by_project_title.get(project_name)
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
