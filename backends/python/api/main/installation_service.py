
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from django.utils import timezone

from config import config

from .models import Bitrix24Account
from .models import ApplicationInstallation
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
        Creates a Smart Process and saves its ID to configuration.
        Called from Settings page button.
        """
        logger.info("Creating Smart Process from settings...")
        try:
            config = self.config_service.get_configuration_sync()
            existing_sp = config.get('sp_entity_type_id', 0)

            if existing_sp and existing_sp != 0:
                raise InstallationError(f"Смарт-процесс уже существует (ID: {existing_sp}). Удалите его вручную перед созданием нового.")

            sp_id = self._create_smart_process_sync()

            new_config = {
                **config,
                'sp_entity_type_id': sp_id,
                'is_configured': False,
            }
            self.config_service.save_configuration_sync(new_config)

            logger.info(f"Smart Process created: {sp_id}")
            return new_config

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
            fields_mapping = self._create_default_fields_sync(sp_id)

            new_config = {
                **config,
                'sp_entity_type_id': sp_id,
                'fields_mapping': fields_mapping,
                'is_configured': True,
            }
            self.config_service.save_configuration_sync(new_config)

            logger.info(f"Fields created: {len(fields_mapping)} fields")
            return new_config

        except InstallationError:
            raise
        except Exception as e:
            logger.error(f"Fields creation failed: {e}")
            raise InstallationError(f"Ошибка создания полей: {e}")

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
            'project_id': ('B24APP_PROJECT_ID', 'ID Проекта', 'integer'),
            'data': ('B24APP_DATE', 'Дата отражения', 'date'),
            'id_zadach_ierarhiya': ('B24APP_TASK_HIER_IDS', 'Иерархия ID', 'string'),
            'title_zadach_ierarhiya': ('B24APP_TASK_HIER_TITLES', 'Иерархия Названий', 'string'),
            'task_name': ('B24APP_TASK_NAME', 'Название задачи', 'string'),
            'our_inn': ('B24APP_OUR_INN', 'Наш ИНН', 'string'),
            'client_inn': ('B24APP_CLIENT_INN', 'ИНН клиента', 'string'),
        }
        
        mapping = {}
        errors = []
        
        for key, (field_suffix, label, type_) in required_fields.items():
            # userfieldconfig.add creates UF fields
            # entityId format: CRM_{sp_id} for smart processes
            # fieldName: Bitrix appends UF_CRM_{sp_id}_ prefix automatically
            entity_id = f"CRM_{sp_id}"
            
            field_config = {
                'moduleId': 'crm',
                'field': {
                    'entityId': entity_id,
                    'fieldName': field_suffix,
                    'userTypeId': type_,
                    'editFormLabel': {'ru': label, 'en': label},
                    'listColumnLabel': {'ru': label, 'en': label},
                    'filterLabel': {'ru': label, 'en': label},
                }
            }
            
            try:
                logger.info(f"Creating field {key}: entityId={entity_id}, fieldName={field_suffix}, type={type_}")
                response = self.client._bitrix_token.call_method('userfieldconfig.add', field_config)
                logger.info(f"Response for {key}: {response}")
                
                # Check response structure
                res = response.get('result', {})
                field = res.get('field', {})
                created_name = field.get('fieldName')
                
                if created_name:
                    mapping[key] = created_name
                    logger.info(f"✅ Created field {key} -> {created_name}")
                else:
                    # Maybe the response structure is different
                    logger.warning(f"⚠️ Field creation for {key} returned unexpected response: {response}")
                    # Try to extract from other response formats
                    if isinstance(res, dict) and 'fieldName' in res:
                        mapping[key] = res['fieldName']
                    else:
                        errors.append(f"{key}: unexpected response format")
                    
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"❌ Error creating field {key}: {error_msg}")
                errors.append(f"{key}: {error_msg}")
                
                # Check if "already exists" error — try to find existing field
                if 'already' in error_msg.lower() or 'exist' in error_msg.lower() or 'уже' in error_msg.lower():
                    # Field likely exists, try to guess its name
                    # Bitrix creates fields as ufCrmXX_XXXXXXXXX format
                    logger.info(f"Field {key} may already exist, using suffix as fallback")
                    mapping[key] = field_suffix
                else:
                    mapping[key] = field_suffix  # fallback
        
        if errors:
            logger.warning(f"Field creation completed with {len(errors)} errors: {errors}")
        
        logger.info(f"Final mapping ({len(mapping)} fields): {mapping}")
        return mapping

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
             # self.client._bitrix_token.call_method('placement.bind', {
             #     'PLACEMENT': 'TASK_VIEW_TAB',
             #     'HANDLER': handler_url,
             #     'TITLE': 'Учет времени',
             #     'DESCRIPTION': 'Приложение для отражения часов'
             # })
             logger.info("Skipped binding TASK_VIEW_TAB (Disabled by user request)")
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
