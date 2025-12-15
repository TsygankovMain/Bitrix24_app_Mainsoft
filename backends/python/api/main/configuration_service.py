
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class ConfigurationService:
    """
    Service for managing application configuration, including:
    - Loading/Saving settings from app.option
    - Retrieving available Smart Processes
    - Retrieving fields for a specific Smart Process
    """

    def __init__(self, client: Any, bitrix24_account=None):
        self.client = client
        self.bitrix24_account = bitrix24_account
        self._config_cache = None

    def get_configuration_sync(self) -> Dict[str, Any]:
        """
        Synchronously load configuration from app.option.
        """
        if self._config_cache:
            return self._config_cache

        try:
            # Use client token to call method
            response = self.client._bitrix_token.call_method('app.option.get', {})
            result = response.get('result', {})

            if 'timestamp_config' in result and result['timestamp_config']:
                try:
                    config = json.loads(result['timestamp_config'])
                    self._config_cache = config
                    # logger.info(f"Loaded config: {config}")
                    return config
                except json.JSONDecodeError:
                    logger.error("Failed to decode config JSON")
                    return self._get_default_configuration()
            else:
                logger.info("No config found, returning defaults")
                return self._get_default_configuration()

        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return self._get_default_configuration()

    def save_configuration_sync(self, config: Dict[str, Any]) -> None:
        """
        Synchronously save configuration to app.option.
        """
        json_config = json.dumps(config, ensure_ascii=False)
        self.client._bitrix_token.call_method('app.option.set', {
            'options': {'timestamp_config': json_config}
        })
        self._config_cache = config
        logger.info("Configuration saved successfully")

    def _get_default_configuration(self) -> Dict[str, Any]:
        """
        Default configuration if nothing is saved.
        """
        return {
            'sp_entity_type_id': 0, # 0 means not configured
            'fields_mapping': {},
            'is_configured': False
        }

    def get_smart_processes_sync(self) -> List[Dict[str, Any]]:
        """
        Get list of all Smart Processes (dynamic types).
        """
        response = self.client._bitrix_token.call_method('crm.type.list', {'filter': {}})
        types = response.get('result', {}).get('types', [])
        
        # Format for frontend
        result = []
        for t in types:
            result.append({
                'id': t['id'],
                'entityTypeId': t['entityTypeId'],
                'title': t['title'],
            })
        return result

    def get_sp_fields_sync(self, entity_type_id: int) -> List[Dict[str, Any]]:
        """
        Get fields for a specific Smart Process.
        """
        response = self.client._bitrix_token.call_method('crm.item.fields', {'entityTypeId': entity_type_id})
        result_data = response.get('result', {})
        # crm.item.fields usually returns { fields: { ... } }
        if 'fields' in result_data and isinstance(result_data['fields'], dict):
             fields = result_data['fields']
        else:
             fields = result_data
        
        logger.info(f"get_sp_fields_sync(SPA={entity_type_id}): Found {len(fields)} fields via crm.item.fields.")

        # Fallback: userfieldconfig.list (for custom fields)
        if not fields:
             try:
                 logger.info(f"Attempting userfieldconfig.list fallback for CRM_{entity_type_id}")
                 uf_res = self.client._bitrix_token.call_method('userfieldconfig.list', {
                     'moduleId': 'crm',
                     'filter': {'fieldName': f'UF_CRM_{entity_type_id}_%'} # Try to filter by prefix? Or just get all for object?
                 })
                 # userfieldconfig.list uses generic filter. 'fieldName' might work if we know prefix.
                 # But real way is usually just listing by moduleId, but we lack documentId filter in docs sometimes.
                 # Let's try crm.item.list with select=['*', 'UF_*'] limit 1 to see keys? No, empty if no items.
                 
                 # Better fallback: 'crm.userfield.list' (legacy) or just accept we need to rely on what available.
                 # Let's use `crm.userfield.list` with filter `ENTITY_ID: CRM_{type}`.
                 
                 uf_res = self.client._bitrix_token.call_method('crm.userfield.list', {
                     'filter': {'ENTITY_ID': f'CRM_{entity_type_id}'}
                 })
                 uf_items = uf_res.get('result', [])
                 logger.info(f"Fallback found {len(uf_items)} fields.")
                 
                 for uf in uf_items:
                     fields[uf['FIELD_NAME']] = {
                         'title': uf.get('EDIT_FORM_LABEL') or uf.get('FIELD_NAME'),
                         'type': uf.get('USER_TYPE_ID'),
                         'isRequired': uf.get('MANDATORY') == 'Y'
                     }
                 
                 # Add some default system fields manually if we are in fallback mode
                 system_fields = ['TITLE', 'ASSIGNED_BY_ID', 'STAGE_ID', 'ID']
                 for sys_f in system_fields:
                     if sys_f not in fields:
                        fields[sys_f] = {'title': sys_f, 'type': 'system'}

             except Exception as e:
                 logger.error(f"Fallback failed: {e}")

        result = []
        for key, field in fields.items():
            result.append({
                'id': key,
                'title': field.get('formLabel') or field.get('title') or key,
                'type': field.get('type'),
                'isRequired': field.get('isRequired', False),
                'isReadOnly': field.get('isReadOnly', False)
            })
            
        return result
