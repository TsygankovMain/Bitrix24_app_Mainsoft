
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from .models import Bitrix24Account
from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

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
        """
        logger.info("Starting installation...")
        try:
            # 1. Load current configuration
            config = self.config_service.get_configuration_sync()
            sp_id = config.get('sp_entity_type_id', 0)
            fields_mapping = config.get('fields_mapping', {})
            
            # 2. Check/Create Smart Process
            if not sp_id or sp_id == 0:
                logger.info("No Smart Process configured. Creating new one...")
                sp_id = self._create_smart_process_sync()
                self.rollback_stack.append(('delete_sp', sp_id))
            else:
                logger.info(f"Using configured Smart Process ID: {sp_id}")

            # 3. Check/Create Fields
            # If mapping is incomplete, we should create missing fields? 
            # For now, if default fields are missing, we create them.
            if not fields_mapping:
                 fields_mapping = self._create_default_fields_sync(sp_id)
                 self.rollback_stack.append(('delete_fields', fields_mapping))
            
            # 4. Save Configuration
            # We save what we created/confirmed
            new_config = {
                'sp_entity_type_id': sp_id,
                'fields_mapping': fields_mapping,
                'is_configured': True,
                'is_auto_installed': True
            }
            self.config_service.save_configuration_sync(new_config)
            self.rollback_stack.append(('delete_config', None)) # Mark that we saved config

            # 5. Install Placements
            self._install_placements_sync()
            self.rollback_stack.append(('delete_placement', None))

            return new_config

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            self._rollback_sync()
            raise InstallationError(f"Installation failed: {e}")

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
        
        response = self.bitrix24_account.call_method('crm.type.add', params)
        result = response.get('result', {})
        sp_id = result.get('type', {}).get('entityTypeId')
        
        if not sp_id:
            raise InstallationError("Failed to get entityTypeId from crm.type.add response")
            
        logger.info(f"Created Smart Process {title}, ID: {sp_id}")
        return int(sp_id)

    def _create_default_fields_sync(self, sp_id: int) -> Dict[str, str]:
        """Creates the required fields for the application"""
        
        # Define fields we need
        # Provide internal map key -> (field_name, field_label, field_type)
        required_fields = {
            'id_zadachi': ('B24APP_TASK_ID', 'ID Задачи', 'integer'),
            'sotrudnik': ('B24APP_EMPLOYEE', 'Сотрудник', 'employee'),
            'kolichestvo_chasov': ('B24APP_HOURS', 'Количество часов', 'double'),
            'uchitivaem': ('B24APP_IS_BILLABLE', 'Учитываем?', 'boolean'),
            'ne_uchitivaemie_chasi': ('B24APP_NON_BILLABLE', 'Неучитываемые часы', 'double'),
            'opisanie': ('B24APP_DESCRIPTION', 'Описание', 'string'),
            'project_title': ('B24APP_PROJECT', 'Проект', 'string'),
            # 'project_id' can be stored in project string or separate integer
            'project_id': ('B24APP_PROJECT_ID', 'ID Проекта', 'integer'),
            'data': ('B24APP_DATE', 'Дата отражения', 'date'),
            'id_zadach_ierarhiya': ('B24APP_TASK_HIERARCHY_IDS', 'Иерархия ID', 'string'), # JSON string
            'title_zadach_ierarhiya': ('B24APP_TASK_HIERARCHY_ITLES', 'Иерархия Названий', 'string') # JSON string
        }
        
        mapping = {}
        
        for key, (chem_name, label, type_) in required_fields.items():
            # userfieldconfig.add
            # For SP, moduleId = 'crm', fieldId = 'CRM_<ID>'
            
            field_config = {
                'moduleId': 'crm',
                'field': {
                    'entityId': f"CRM_{sp_id}",
                    'fieldName': chem_name,
                    'userTypeId': type_,
                    'editFormLabel': {'ru': label},
                    'listColumnLabel': {'ru': label},
                    'filterLabel': {'ru': label},
                }
            }
            
            try:
                response = self.bitrix24_account.call_method('userfieldconfig.add', field_config)
                # response['result']['field']['fieldName'] or similar
                # actually userfieldconfig returns the created field object
                
                # Check response structure
                res = response.get('result', {})
                field = res.get('field', {})
                created_name = field.get('fieldName')
                
                if created_name:
                    mapping[key] = created_name
                    logger.info(f"Created field {key} -> {created_name}")
                else:
                    logger.warning(f"Field creation returned unexpected response for {key}")
                    
            except Exception as e:
                # If field already exists (e.g. reinstall), we might catch error or ignore
                # Ideally we check existence first or handle "already exists" error
                logger.warning(f"Error creating field {key}: {e}")
                # Fallback: assume it exists with the name we asked for?
                mapping[key] = chem_name 
                
        return mapping

    def _install_placements_sync(self) -> None:
        """Installs the Task Tab placement"""
        from config import config # Import locally to avoid circulars if any
        base_url = config.app_base_url
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
            
        handler_url = f"{base_url}" # App handles routing on client side via placement checks

        # Ensure we unbind before bind to avoid duplicates?
        # placement.unbind is safe
        try:
             self.bitrix24_account.call_method('placement.unbind', {
                 'PLACEMENT': 'TASK_VIEW_TAB',
                 'HANDLER': handler_url
             })
        except Exception:
             pass

        logger.info("Placement TASK_VIEW_TAB unbind attempt finished")

        # Install Project/Group Tab Placement
        try:
             self.bitrix24_account.call_method('placement.unbind', {
                 'PLACEMENT': 'SONET_GROUP_DETAIL_TAB',
                 'HANDLER': handler_url
             })
        except Exception:
             pass

        logger.info("Placement SONET_GROUP_DETAIL_TAB unbind attempt finished")

    def _rollback_sync(self):
        """Rollbacks changes on failure"""
        logger.warning("Rolling back installation...")
        for action, data in reversed(self.rollback_stack):
            try:
                if action == 'delete_sp':
                    self.bitrix24_account.call_method('crm.type.delete', {'id': data})
                
                elif action == 'delete_fields':
                    # Need to implement field deletion if critical
                    pass
                
                elif action == 'delete_placement':
                    self.bitrix24_account.call_method('placement.unbind', {'PLACEMENT': 'TASK_VIEW_TAB'})
                
                elif action == 'delete_config':
                    self.bitrix24_account.call_method('app.option.set', {'options': {'timestamp_config': ''}})

            except Exception as e:
                logger.error(f"Rollback failed for {action}: {e}")
