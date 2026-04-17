
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from django.utils import timezone

from config import config

from .models import Bitrix24Account
from .models import ApplicationInstallation
from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

TIMESHEET_FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    'id_zadachi': {'suffix': 'TASK_ID', 'label': 'ID Задачи', 'type': 'integer'},
    'sotrudnik': {'suffix': 'EMPLOYEE', 'label': 'Сотрудник', 'type': 'employee'},
    'kolichestvo_chasov': {'suffix': 'HOURS', 'label': 'Количество часов', 'type': 'double'},
    'uchitivaem': {'suffix': 'IS_BILLABLE', 'label': 'Учитываем?', 'type': 'boolean'},
    'ne_uchitivaemie_chasi': {'suffix': 'NON_BILLABLE', 'label': 'Неучитываемые часы', 'type': 'double'},
    'opisanie': {'suffix': 'DESCRIPTION', 'label': 'Описание', 'type': 'string'},
    'project_title': {'suffix': 'PROJECT', 'label': 'Проект', 'type': 'string'},
    'project_id': {'suffix': 'PROJECT_ID', 'label': 'ID Проекта', 'type': 'integer'},
    'project_item_id': {'suffix': 'PROJECT_ITEM_ID', 'label': 'ID элемента проекта SPA', 'type': 'integer'},
    'data': {'suffix': 'DATE', 'label': 'Дата отражения', 'type': 'date'},
    'id_zadach_ierarhiya': {'suffix': 'HIER_IDS', 'label': 'Иерархия ID', 'type': 'string', 'multiple': True},
    'title_zadach_ierarhiya': {'suffix': 'HIER_TITLES', 'label': 'Иерархия Названий', 'type': 'string', 'multiple': True},
    'task_name': {'suffix': 'TASK_NAME', 'label': 'Название задачи', 'type': 'string'},
    'our_inn': {'suffix': 'OUR_INN', 'label': 'Наш ИНН', 'type': 'string'},
    'client_inn': {'suffix': 'CLIENT_INN', 'label': 'ИНН клиента', 'type': 'string'},
}

PROJECT_FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    'bitrix_group_id': {'suffix': 'BITRIX_GROUP_ID', 'label': 'ID группы Bitrix', 'type': 'integer'},
    'stage_id': {'suffix': 'STAGE_ID', 'label': 'Стадия проекта', 'type': 'stage', 'system': True},
    'is_support': {'suffix': 'IS_SUPPORT', 'label': 'Support-флаг', 'type': 'boolean'},
    'project_hours_budget': {'suffix': 'PROJECT_HOURS_BUDGET', 'label': 'Бюджет часов', 'type': 'double'},
    'hourly_rate': {'suffix': 'HOURLY_RATE', 'label': 'Ставка часа', 'type': 'double'},
    'curator_id': {'suffix': 'CURATOR_ID', 'label': 'Куратор', 'type': 'employee'},
    'company_id': {'suffix': 'COMPANY_ID', 'label': 'Компания', 'type': 'crm_company'},
    'our_legal_entity_id': {'suffix': 'OUR_LEGAL_ENTITY_ID', 'label': 'Наше юрлицо', 'type': 'crm_company'},
    'start_date': {'suffix': 'START_DATE', 'label': 'Дата старта', 'type': 'date'},
    'finish_date': {'suffix': 'FINISH_DATE', 'label': 'Дата окончания', 'type': 'date'},
    'is_archived': {'suffix': 'IS_ARCHIVED', 'label': 'Архив', 'type': 'boolean'},
}

PROJECT_SYSTEM_MAPPINGS = {
    'title': 'TITLE',
    'stage_id': 'STAGE_ID',
}

PROJECT_FIELD_ALIASES = {
    'manual_stage': 'stage_id',
    'effective_stage': 'stage_id',
}

class InstallationError(Exception):
    pass

class InstallationService:
    """
    Service for installing the application components:
    1. Smart Process Type (SPA)
    2. User Fields for the SPA
    3. Placement (Task Tab)
    
    Respects manual configuration if present.
    """

    def __init__(self, bitrix24_client: Any, bitrix24_account: Bitrix24Account):
        self.client = bitrix24_client
        self.bitrix24_account = bitrix24_account
        self.config_service = ConfigurationService(bitrix24_client, bitrix24_account)
        self.rollback_stack = []

    def install_app_sync(self) -> Dict[str, Any]:
        """
        Orchestrates the installation process synchronously.
        Now only registers the app and installs placements.
        SP and fields creation is done via settings page buttons.
        """
        logger.info("Starting installation...")
        try:
            # 1. Load current configuration
            config = self.config_service.get_configuration_sync()

            # 2. Install Placements
            self._install_placements_sync()
            self.rollback_stack.append(('delete_placement', None))

            # 3. Connect support line without blocking installation.
            self.connect_support_line_sync()

            return config

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            self._rollback_sync()
            raise InstallationError(f"Installation failed: {e}")

    def create_smart_process_only(self) -> Dict[str, Any]:
        """
        Creates a Smart Process, creates default fields and saves ready mapping.
        """
        logger.info("Creating Smart Process with default fields from settings...")
        try:
            config = self.config_service.get_configuration_sync()
            existing_sp = config.get('sp_entity_type_id', 0)

            if existing_sp and existing_sp != 0:
                raise InstallationError(f"Смарт-процесс уже существует (ID: {existing_sp}). Удалите его вручную перед созданием нового.")

            sp_id = self._create_smart_process_sync()
            fields_mapping, warnings = self._create_fields_mapping_sync(sp_id, 'timesheet')

            new_config = {
                **config,
                'sp_entity_type_id': sp_id,
                'fields_mapping': fields_mapping,
                'is_configured': len(fields_mapping) == len(TIMESHEET_FIELD_DEFINITIONS),
            }
            self.config_service.save_configuration_sync(new_config)

            logger.info(f"Smart Process created: {sp_id}, mapped fields: {len(fields_mapping)}")
            return {
                'config': new_config,
                'created_fields_count': len(fields_mapping),
                'field_warnings': warnings,
            }

        except InstallationError:
            raise
        except Exception as e:
            logger.error(f"SP creation failed: {e}")
            raise InstallationError(f"Ошибка создания смарт-процесса: {e}")

    def create_fields_only(self, sp_id: int) -> Dict[str, Any]:
        """
        Creates all required fields in the specified Smart Process.
        Called from Settings page button.
        """
        logger.info(f"Creating fields for SP {sp_id} from settings...")
        try:
            if not sp_id or sp_id == 0:
                raise InstallationError("Сначала выберите или создайте смарт-процесс.")

            config = self.config_service.get_configuration_sync()
            fields_mapping, warnings = self._create_fields_mapping_sync(sp_id, 'timesheet')

            new_config = {
                **config,
                'sp_entity_type_id': sp_id,
                'fields_mapping': fields_mapping,
                'is_configured': len(fields_mapping) == len(TIMESHEET_FIELD_DEFINITIONS),
            }
            self.config_service.save_configuration_sync(new_config)

            logger.info(f"Fields created: {len(fields_mapping)} fields")
            return {
                'config': new_config,
                'created_fields_count': len(fields_mapping),
                'field_warnings': warnings,
            }

        except InstallationError:
            raise
        except Exception as e:
            logger.error(f"Fields creation failed: {e}")
            raise InstallationError(f"Ошибка создания полей: {e}")

    def create_single_field(self, sp_id: int, field_key: str, mapping_type: str = 'timesheet') -> Dict[str, Any]:
        if not sp_id or sp_id == 0:
            raise InstallationError("Не указан ID смарт-процесса.")

        config = self.config_service.get_configuration_sync()
        mapping_key = 'fields_mapping' if mapping_type == 'timesheet' else 'project_fields_mapping'
        entity_key = 'sp_entity_type_id' if mapping_type == 'timesheet' else 'project_sp_entity_type_id'
        existing_mapping = dict(config.get(mapping_key) or {})
        canonical_field_key = self._normalize_project_mapping_key(field_key) if mapping_type == 'project' else field_key

        created_mapping, warnings = self._create_fields_mapping_sync(sp_id, mapping_type, [canonical_field_key])
        if not created_mapping.get(canonical_field_key):
            raise InstallationError(f"Поле {canonical_field_key} не удалось создать или определить в Smart Process.")

        existing_mapping.update(created_mapping)
        new_config = {
            **config,
            entity_key: sp_id,
            mapping_key: existing_mapping,
        }
        self.config_service.save_configuration_sync(new_config)
        return {
            'config': new_config,
            'field_key': canonical_field_key,
            'field_id': created_mapping[canonical_field_key],
            'field_warnings': warnings,
        }

    def _create_smart_process_sync(self) -> int:
        """Creates a new Smart Process Type and returns its entityTypeId"""
        title = "Учет трудозатрат (App)"
        
        params = {
            'fields': {
                'title': title,
                'code': 'timesheet_app',
                'isBizProcEnabled': 'Y',
                'isAutomationEnabled': 'Y',
                'isClientEnabled': 'N', 
                'isUseInUserfieldEnabled': 'Y' 
                # Add other flags as preferred (dev_test had more)
            }
        }
        
        response = self.client._bitrix_token.call_method('crm.type.add', params)
        result = response.get('result', {})
        sp_id = result.get('type', {}).get('entityTypeId')
        
        if not sp_id:
            raise InstallationError("Failed to get entityTypeId from crm.type.add response")
            
        logger.info(f"Created Smart Process {title}, ID: {sp_id}")
        return int(sp_id)

    def _resolve_spa_ordinal_id(self, entity_type_id: int) -> int:
        smart_processes = self.config_service.get_smart_processes_sync()
        for smart_process in smart_processes:
            if int(smart_process.get('entityTypeId') or 0) == int(entity_type_id):
                return int(smart_process.get('id') or 0)
        raise InstallationError(f"Не удалось определить внутренний ID SPA для entityTypeId={entity_type_id}.")

    def _build_user_field_api_id(self, full_field_name: str) -> str:
        normalized_name = str(full_field_name or '')
        if '_' not in normalized_name:
            return normalized_name
        parts = normalized_name.split('_')
        if not parts:
            return normalized_name
        return ''.join(
            part.lower() if index == 0 else part[:1].upper() + part[1:].lower()
            for index, part in enumerate(parts)
        )

    def _get_mapping_definitions(self, mapping_type: str) -> Dict[str, Dict[str, Any]]:
        if mapping_type == 'timesheet':
            return TIMESHEET_FIELD_DEFINITIONS
        if mapping_type == 'project':
            return PROJECT_FIELD_DEFINITIONS
        raise InstallationError(f"Неизвестный тип маппинга: {mapping_type}")

    def _normalize_project_mapping_key(self, field_key: str) -> str:
        normalized_key = str(field_key or '').strip()
        if not normalized_key:
            return normalized_key
        return PROJECT_FIELD_ALIASES.get(normalized_key, normalized_key)

    def _normalize_project_mapping_keys(self, field_keys: List[str]) -> List[str]:
        normalized_keys: List[str] = []
        for field_key in field_keys:
            normalized_key = self._normalize_project_mapping_key(field_key)
            if normalized_key and normalized_key not in normalized_keys:
                normalized_keys.append(normalized_key)
        return normalized_keys

    def _create_fields_mapping_sync(
        self,
        entity_type_id: int,
        mapping_type: str,
        field_keys: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, str], List[str]]:
        definitions = self._get_mapping_definitions(mapping_type)
        target_keys = field_keys or list(definitions.keys())
        if mapping_type == 'project':
            target_keys = self._normalize_project_mapping_keys(target_keys)
        mapping: Dict[str, str] = {}
        warnings: List[str] = []
        ordinal_id = self._resolve_spa_ordinal_id(entity_type_id)
        entity_id = f"CRM_{ordinal_id}"

        if mapping_type == 'project':
            for key, system_field_id in PROJECT_SYSTEM_MAPPINGS.items():
                if key in target_keys:
                    mapping[key] = system_field_id

        for key in target_keys:
            if key in PROJECT_SYSTEM_MAPPINGS:
                continue

            field_definition = definitions.get(key)
            if not field_definition:
                raise InstallationError(f"Поле {key} не поддерживается для маппинга {mapping_type}.")

            full_field_name = f"UF_CRM_{ordinal_id}_{field_definition['suffix']}"
            field_api_id = self._build_user_field_api_id(full_field_name)
            field_config = {
                'moduleId': 'crm',
                'field': {
                    'entityId': entity_id,
                    'fieldName': full_field_name,
                    'userTypeId': field_definition['type'],
                    'editFormLabel': {'ru': field_definition['label'], 'en': field_definition['label']},
                    'listColumnLabel': {'ru': field_definition['label'], 'en': field_definition['label']},
                    'filterLabel': {'ru': field_definition['label'], 'en': field_definition['label']},
                }
            }
            if field_definition.get('multiple'):
                field_config['field']['multiple'] = 'Y'

            try:
                response = self.client._bitrix_token.call_method('userfieldconfig.add', field_config)
                raw_result = response.get('result', {})
                raw_field_name = (
                    raw_result.get('field', {}).get('fieldName')
                    or raw_result.get('fieldName')
                    or full_field_name
                )
                mapping[key] = self._build_user_field_api_id(raw_field_name)
                logger.info("Created %s field %s -> %s", mapping_type, key, mapping[key])
            except Exception as e:
                error_msg = str(e)
                if 'already' in error_msg.lower() or 'exist' in error_msg.lower() or 'уже' in error_msg.lower():
                    mapping[key] = field_api_id
                    warnings.append(f"{field_definition['label']}: поле уже существовало")
                    logger.info("Field %s already exists, using %s", key, field_api_id)
                    continue

                warnings.append(f"{field_definition['label']}: {error_msg}")
                logger.warning("Failed to create field %s (%s): %s", key, mapping_type, error_msg)

        available_fields = self.config_service.get_sp_fields_sync(entity_type_id)
        available_field_ids = {str(field.get('id') or '').lower() for field in available_fields}

        verified_mapping: Dict[str, str] = {}
        for key, field_id in mapping.items():
            if str(field_id).lower() in available_field_ids or field_id in PROJECT_SYSTEM_MAPPINGS.values():
                verified_mapping[key] = field_id
            else:
                warnings.append(f"{key}: поле не найдено в crm.item.fields после создания")

        logger.info("Final %s mapping (%s fields): %s", mapping_type, len(verified_mapping), verified_mapping)
        return verified_mapping, warnings

    def _install_placements_sync(self) -> None:
        """Installs the Task Tab placement"""
        base_url = config.app_base_url
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
            
        handler_url = f"{base_url}" # App handles routing on client side via placement checks

        # Ensure we unbind before bind to avoid duplicates?
        # placement.unbind is safe
        try:
             self.client._bitrix_token.call_method('placement.unbind', {
                 'PLACEMENT': 'TASK_VIEW_TAB',
                 'HANDLER': handler_url
             })
        except Exception:
             pass

        logger.info("Placement TASK_VIEW_TAB unbind attempt finished")

        # Install Project/Group Tab Placement
        try:
             self.client._bitrix_token.call_method('placement.unbind', {
                 'PLACEMENT': 'SONET_GROUP_DETAIL_TAB',
                 'HANDLER': handler_url
             })
        except Exception:
             pass

        logger.info("Placement SONET_GROUP_DETAIL_TAB unbind attempt finished")

        # 3. Bind Placements
        try:
             self.client._bitrix_token.call_method('placement.bind', {
                 'PLACEMENT': 'TASK_VIEW_TAB',
                 'HANDLER': handler_url,
                 'TITLE': 'Учет времени',
                 'DESCRIPTION': 'Приложение для отражения часов'
             })
             logger.info("Bound TASK_VIEW_TAB")
        except Exception as e:
             logger.error(f"Failed to bind TASK_VIEW_TAB: {e}")

        try:
             self.client._bitrix_token.call_method('placement.bind', {
                 'PLACEMENT': 'SONET_GROUP_DETAIL_TAB',
                 'HANDLER': handler_url,
                 'TITLE': 'Учет времени',
                 'DESCRIPTION': 'Приложение для отражения часов'
             })
             logger.info("Bound SONET_GROUP_DETAIL_TAB")
        except Exception as e:
             logger.error(f"Failed to bind SONET_GROUP_DETAIL_TAB: {e}")

    def _get_or_create_installation(self) -> ApplicationInstallation:
        installation, _ = ApplicationInstallation.objects.get_or_create(
            bitrix_24_account=self.bitrix24_account,
            defaults={
                "status": self.bitrix24_account.status,
                "portal_license_family": "",
                "application_token": self.bitrix24_account.application_token,
            },
        )
        return installation

    def get_support_line_status(self) -> Dict[str, Any]:
        installation = self._get_or_create_installation()
        return {
            "configured": bool(config.support_openline_code),
            "code": installation.support_line_code or (config.support_openline_code or ""),
            "status": installation.support_line_status or "not_connected",
            "dialog_id": installation.support_line_dialog_id or "",
            "connected_at": installation.support_line_connected_at.isoformat() if installation.support_line_connected_at else None,
            "error": installation.support_line_error or "",
        }

    def connect_support_line_sync(self, force: bool = False) -> Dict[str, Any]:
        installation = self._get_or_create_installation()
        support_line_code = (config.support_openline_code or "").strip()

        if not support_line_code:
            installation.support_line_code = ""
            installation.support_line_status = "disabled"
            installation.support_line_error = "SUPPORT_OPENLINE_CODE is not configured"
            installation.save(update_fields=["support_line_code", "support_line_status", "support_line_error", "update_at_utc"])
            return self.get_support_line_status()

        if installation.support_line_status == "connected" and installation.support_line_dialog_id and installation.support_line_code == support_line_code and not force:
            return self.get_support_line_status()

        try:
            response = self.client._bitrix_token.call_method("imopenlines.network.join", {
                "CODE": support_line_code,
            })
            dialog_id = str(response.get("result", "")).strip()
            if not dialog_id:
                raise InstallationError("Support line connection returned empty dialog id")

            installation.support_line_code = support_line_code
            installation.support_line_dialog_id = dialog_id
            installation.support_line_status = "connected"
            installation.support_line_error = ""
            installation.support_line_connected_at = timezone.now()
            installation.save(update_fields=[
                "support_line_code",
                "support_line_dialog_id",
                "support_line_status",
                "support_line_error",
                "support_line_connected_at",
                "update_at_utc",
            ])
        except Exception as error:
            installation.support_line_code = support_line_code
            installation.support_line_status = "error"
            installation.support_line_error = str(error)
            installation.save(update_fields=[
                "support_line_code",
                "support_line_status",
                "support_line_error",
                "update_at_utc",
            ])
            logger.warning("Support line connection failed for %s: %s", self.bitrix24_account.domain_url, error)

        return self.get_support_line_status()

    def _rollback_sync(self):
        """Rollbacks changes on failure"""
        logger.warning("Rolling back installation...")
        for action, data in reversed(self.rollback_stack):
            try:
                if action == 'delete_sp':
                    self.client._bitrix_token.call_method('crm.type.delete', {'id': data})
                
                elif action == 'delete_fields':
                    # Need to implement field deletion if critical
                    pass
                
                elif action == 'delete_placement':
                    self.client._bitrix_token.call_method('placement.unbind', {'PLACEMENT': 'TASK_VIEW_TAB'})
                
                elif action == 'delete_config':
                    self.client._bitrix_token.call_method('app.option.set', {'options': {'timestamp_config': ''}})

            except Exception as e:
                logger.error(f"Rollback failed for {action}: {e}")
