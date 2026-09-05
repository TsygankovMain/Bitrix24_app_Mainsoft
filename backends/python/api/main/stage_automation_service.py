from typing import Any, Dict, Optional


from .models import Bitrix24Account, ProjectCard
from .project_board_service import ProjectCardService
from .project_board_shared import (
    PROJECT_AUTO_STAGES,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    ensure_project_card_schema,
    get_project_card_queryset,
    invalidate_project_runtime_caches,
)


class ProjectStageAutomationService:
    def __init__(self, account: Bitrix24Account):
        self.account = account

    def run_daily_check(self) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            return {
                "status": "ok",
                "checked": 0,
                "moved_to_30_days": 0,
                "moved_to_90_days": 0,
                "returned_to_work": 0,
            }

        ProjectCardService(None, self.account).refresh_writeoff_stats()
        cards = get_project_card_queryset(self.account).filter(is_archived=False)

        checked = 0
        moved_to_30_days = 0
        moved_to_90_days = 0
        returned_to_work = 0

        for card in cards:
            checked += 1
            target_stage = self._resolve_auto_stage(card)

            if target_stage == PROJECT_STAGE_NO_WRITEOFF_30 and card.stage != target_stage:
                card.stage = target_stage
                card.stage_source = "auto"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                moved_to_30_days += 1
                continue

            if target_stage == PROJECT_STAGE_NO_WRITEOFF_90 and card.stage != target_stage:
                card.stage = target_stage
                card.stage_source = "auto"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                moved_to_90_days += 1
                continue

            if target_stage is None and card.stage in PROJECT_AUTO_STAGES:
                fallback_stage = card.manual_stage or (PROJECT_STAGE_IN_WORK if card.last_writeoff_at else PROJECT_STAGE_NEW)
                card.stage = fallback_stage
                card.stage_source = "manual"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                returned_to_work += 1

        invalidate_project_runtime_caches(self.account)
        return {
            "status": "ok",
            "checked": checked,
            "moved_to_30_days": moved_to_30_days,
            "moved_to_90_days": moved_to_90_days,
            "returned_to_work": returned_to_work,
        }

    @staticmethod
    def _resolve_auto_stage(card: ProjectCard) -> Optional[str]:
        if not card.last_writeoff_at:
            return None
        if card.last_writeoff_days >= 90:
            return PROJECT_STAGE_NO_WRITEOFF_90
        if card.last_writeoff_days >= 30:
            return PROJECT_STAGE_NO_WRITEOFF_30
        return None
