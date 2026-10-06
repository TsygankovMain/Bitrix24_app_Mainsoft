"""Настройка приложения «в одно нажатие».

Раньше администратор проходил экран «Сопоставление полей» шаг за шагом: создать
смарт-процесс часов, создать поля, то же для проектов, то же для доходов-расходов.
Этот сервис делает всё одним вызовом и оставляет портал в рабочем состоянии:

  * три смарт-процесса — часы, проекты, доходы-расходы;
  * все их поля и готовое сопоставление в конфигурации приложения;
  * стадии воронки проектов под доску проектов (только у процесса, созданного сейчас).

Правила, из-за которых сервис не сводится к трём вызовам create_smart_process_only:

  * **Чужое не трогаем.** Процесс, уже выбранный в настройках, и поля, сопоставленные
    руками, остаются как есть — досоздаётся только недостающее. Стадии существующего
    процесса не переименовываются: в них могут лежать проекты.
  * **Не плодим дубли.** Конфигурация хранится в app.option и пропадает при
    переустановке, а процессы на портале остаются. Процесс с нашим кодом
    (timesheet_app, project_app, finance_app) подхватывается, а не создаётся заново.
    Поэтому повторное нажатие безопасно, а оборванный на середине запуск
    дорабатывается следующим.
  * **Блоки независимы.** Отказ на одном (например, лимит смарт-процессов тарифа)
    не отменяет остальные: что получилось — сохраняется, отказ едет в отчёте.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from django.core.cache import cache

from .configuration_service import ConfigurationService
from .installation_service import (
    PROJECT_SYSTEM_MAPPINGS,
    SMART_PROCESS_DEFINITIONS,
    InstallationService,
)
from .project_board_shared import (
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
)

logger = logging.getLogger(__name__)

# Порядок важен только для отчёта и для того, чтобы главный блок (часы) создавался первым.
BLOCKS: Tuple[str, ...] = ("timesheet", "project", "finance")

BLOCK_TITLES: Dict[str, str] = {
    "timesheet": "Учёт времени",
    "project": "Проекты",
    "finance": "Доходы и расходы",
}

# Штатные стадии нового смарт-процесса (коды после двоеточия в STATUS_ID) → названия,
# по которым доска проектов узнаёт ручные стадии (project_board_shared).
DEFAULT_STAGE_RENAMES: Dict[str, str] = {
    "NEW": PROJECT_STAGE_NEW,
    "PREPARATION": PROJECT_STAGE_ESTIMATE,
    "CLIENT": PROJECT_STAGE_IN_WORK,
}

# Автоматические стадии: (код, название, цвет). Встают между «В работе» и успешной.
AUTO_STAGES: Tuple[Tuple[str, str, str], ...] = (
    ("UC_NOWRITE30", PROJECT_STAGE_NO_WRITEOFF_30, "#FFA900"),
    ("UC_NOWRITE90", PROJECT_STAGE_NO_WRITEOFF_90, "#FF5752"),
)

LOCK_TTL_SECONDS = 180


class OneClickSetupBusy(Exception):
    """Настройка этого портала уже идёт (двойной клик или второй администратор)."""


class OneClickSetupService:
    def __init__(self, bitrix24_client: Any, bitrix24_account: Any):
        self.client = bitrix24_client
        self.account = bitrix24_account
        self.installer = InstallationService(bitrix24_client, bitrix24_account)
        self.config_service: ConfigurationService = self.installer.config_service

    @property
    def lock_key(self) -> str:
        return f"one-click-setup:{getattr(self.account, 'member_id', '') or getattr(self.account, 'pk', '')}"

    # ------------------------------------------------------------------ запуск

    def run(self) -> Dict[str, Any]:
        if not cache.add(self.lock_key, "1", LOCK_TTL_SECONDS):
            raise OneClickSetupBusy("Настройка уже выполняется. Подождите минуту и обновите страницу.")
        try:
            return self._run()
        finally:
            cache.delete(self.lock_key)

    def _run(self) -> Dict[str, Any]:
        config = dict(self.config_service.get_configuration_sync() or {})
        portal_types = self.config_service.get_smart_processes_sync()
        blocks: List[Dict[str, Any]] = []

        for block in BLOCKS:
            report = self._setup_block(block, config, portal_types)
            blocks.append(report)

        timesheet_ready = next(b["ready"] for b in blocks if b["block"] == "timesheet")
        config["is_configured"] = bool(timesheet_ready)
        saved = self.config_service.save_configuration_sync(config)

        status = "done" if all(b["ready"] for b in blocks) else "partial"
        logger.info("One-click setup finished: %s (%s)", status,
                    ", ".join(f"{b['block']}={'ok' if b['ready'] else 'fail'}" for b in blocks))
        return {"status": status, "blocks": blocks, "config": saved}

    # ------------------------------------------------------------------- блок

    def _setup_block(self, block: str, config: Dict[str, Any], portal_types: List[Dict[str, Any]]) -> Dict[str, Any]:
        definition = SMART_PROCESS_DEFINITIONS[block]
        entity_key, mapping_key = definition["entity_key"], definition["mapping_key"]
        report: Dict[str, Any] = {
            "block": block,
            "title": BLOCK_TITLES[block],
            "entity_type_id": 0,
            "created": False,
            "created_fields": 0,
            "stages_prepared": False,
            "ready": False,
            "warnings": [],
        }
        try:
            sp_id, created = self._resolve_or_create_process(block, config.get(entity_key), portal_types)
            report["entity_type_id"], report["created"] = sp_id, created
            config[entity_key] = sp_id

            required = self._required_keys(block)
            mapping = {k: v for k, v in dict(config.get(mapping_key) or {}).items() if v}
            missing = [key for key in required if not mapping.get(key)]
            if missing:
                created_mapping, warnings = self.installer._create_fields_mapping_sync(sp_id, block, missing)
                mapping.update(created_mapping)
                report["created_fields"] = sum(1 for key in created_mapping if key not in PROJECT_SYSTEM_MAPPINGS)
                report["warnings"].extend(warnings)
            config[mapping_key] = mapping

            still_missing = [key for key in required if not mapping.get(key)]
            report["ready"] = not still_missing
            if still_missing:
                report["error"] = "Не удалось создать поля: " + ", ".join(still_missing)

            if block == "project" and created:
                report["stages_prepared"] = self._prepare_project_stages(sp_id, report["warnings"])
        except Exception as exc:  # отказ блока не должен ронять остальные
            logger.warning("One-click setup: block %s failed: %s", block, exc)
            report["ready"] = False
            report["error"] = str(exc)
        return report

    def _required_keys(self, block: str) -> List[str]:
        keys = list(self.installer._get_mapping_definitions(block).keys())
        if block == "project":
            keys += [key for key in PROJECT_SYSTEM_MAPPINGS if key not in keys]
        return keys

    def _resolve_or_create_process(
        self, block: str, configured_id: Any, portal_types: List[Dict[str, Any]]
    ) -> Tuple[int, bool]:
        known_ids = {int(t.get("entityTypeId") or 0) for t in portal_types}
        try:
            configured = int(configured_id or 0)
        except (TypeError, ValueError):
            configured = 0
        # Процесс из настроек берём, только если он ещё есть на портале: удалённый
        # вручную процесс оставил бы настройку указывать в пустоту.
        if configured and (configured in known_ids or not known_ids):
            return configured, False

        code = SMART_PROCESS_DEFINITIONS[block]["code"]
        for portal_type in portal_types:
            if code and str(portal_type.get("code") or "") == code:
                return int(portal_type["entityTypeId"]), False

        return self.installer._create_smart_process_sync(block), True

    # ----------------------------------------------------------------- стадии

    def _prepare_project_stages(self, entity_type_id: int, warnings: List[str]) -> bool:
        """Приводит стадии только что созданного процесса проектов к тем, что ждёт доска.

        Всё здесь — «по возможности»: доска работает и со штатными стадиями (автостадии
        она дорисовывает сама), поэтому отказ портала — предупреждение, а не ошибка.
        """
        call = self.client._bitrix_token.call_method
        try:
            category_id = self._default_category_id(entity_type_id)
            stage_entity = f"DYNAMIC_{entity_type_id}_STAGE_{category_id}"
            rows = call("crm.status.list", {"order": {"SORT": "ASC"}, "filter": {"ENTITY_ID": stage_entity}}).get("result") or []
        except Exception as exc:
            warnings.append(f"Стадии проектов: не удалось прочитать воронку ({exc})")
            return False

        ok = True
        by_code = {str(row.get("STATUS_ID") or "").split(":")[-1]: row for row in rows}
        names = {str(row.get("NAME") or "") for row in rows}

        for code, title in DEFAULT_STAGE_RENAMES.items():
            row = by_code.get(code)
            if not row or row.get("NAME") == title or title in names:
                continue
            try:
                call("crm.status.update", {"id": row.get("ID"), "fields": {"NAME": title}})
                names.add(title)
            except Exception as exc:
                ok = False
                warnings.append(f"Стадии проектов: «{title}» не переименована ({exc})")

        base_sort = self._sort_of(by_code.get("CLIENT")) or max([self._sort_of(r) for r in rows if not r.get("SEMANTICS")] or [30])
        next_sort = min([self._sort_of(r) for r in rows if self._sort_of(r) > base_sort] or [base_sort + 10])
        step = max(1, (next_sort - base_sort) // (len(AUTO_STAGES) + 1))
        for index, (code, title, color) in enumerate(AUTO_STAGES, start=1):
            if title in names:
                continue
            try:
                call("crm.status.add", {"fields": {
                    "ENTITY_ID": stage_entity,
                    # Префикс и CATEGORY_ID обязательны: стадию без воронки канбан
                    # покажет, но автоматизация портала её не увидит.
                    "STATUS_ID": f"DT{entity_type_id}_{category_id}:{code}",
                    "NAME": title,
                    "SORT": base_sort + step * index,
                    "COLOR": color,
                    "SEMANTICS": "",
                    "CATEGORY_ID": category_id,
                }})
            except Exception as exc:
                ok = False
                warnings.append(f"Стадии проектов: «{title}» не создана ({exc})")
        return ok

    def _default_category_id(self, entity_type_id: int) -> int:
        response = self.client._bitrix_token.call_method("crm.category.list", {"entityTypeId": entity_type_id})
        result = response.get("result") or {}
        categories = result.get("categories") if isinstance(result, dict) else result
        categories = categories or []
        if not categories:
            raise RuntimeError("у смарт-процесса нет воронок")
        default = next((c for c in categories if str(c.get("isDefault") or "").upper() in ("Y", "TRUE", "1")), categories[0])
        return int(default.get("id") or default.get("ID"))

    @staticmethod
    def _sort_of(row: Optional[Dict[str, Any]]) -> int:
        try:
            return int((row or {}).get("SORT") or 0)
        except (TypeError, ValueError):
            return 0
