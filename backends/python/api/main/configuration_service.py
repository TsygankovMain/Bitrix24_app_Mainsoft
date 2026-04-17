
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
                    config = self.normalize_configuration_sync(config)
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
        config = self.normalize_configuration_sync(config)
        json_config = json.dumps(config, ensure_ascii=False)
        self.client._bitrix_token.call_method('app.option.set', {
            'options': {'timestamp_config': json_config}
        })
        self._config_cache = config
        logger.info("Configuration saved successfully")

    def normalize_configuration_sync(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Normalize config so backend keeps backward compatibility with old project stage mappings.
        """
        normalized = self._merge_with_defaults(config)
        normalized_project_mapping = self._normalize_project_fields_mapping(
            normalized.get('project_fields_mapping')
        )
        root_stage_value = (
            normalized.get('stage_id')
            or normalized.get('stage')
            or normalized.get('project_stage')
            or normalized.get('effective_stage')
            or normalized.get('manual_stage')
        )
        root_stage_value = str(root_stage_value or '').strip()
        if root_stage_value:
            normalized_project_mapping['stage_id'] = root_stage_value
            normalized_project_mapping['stage'] = root_stage_value
            normalized_project_mapping['project_stage'] = root_stage_value
            normalized_project_mapping['manual_stage'] = root_stage_value
            normalized_project_mapping['effective_stage'] = root_stage_value

        normalized['project_fields_mapping'] = normalized_project_mapping
        return normalized

    def _merge_with_defaults(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        defaults = self._get_default_configuration()
        merged = dict(defaults)
        merged.update(config or {})

        directory_defaults = defaults.get('legal_entity_directory', {})
        merged_directory = dict(directory_defaults)
        merged_directory.update((config or {}).get('legal_entity_directory') or {})
        merged['legal_entity_directory'] = merged_directory

        return merged

    @staticmethod
    def _normalize_project_fields_mapping(mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(mapping, dict):
            return {}

        normalized = dict(mapping)
        stage_value = (
            normalized.get('stage_id')
            or normalized.get('stage')
            or normalized.get('project_stage')
            or normalized.get('effective_stage')
            or normalized.get('manual_stage')
        )
        stage_value = str(stage_value or '').strip()
        if stage_value:
            normalized['stage_id'] = stage_value
            normalized['stage'] = stage_value
            normalized['project_stage'] = stage_value
            normalized['manual_stage'] = stage_value
            normalized['effective_stage'] = stage_value
        return normalized

    def _get_default_configuration(self) -> Dict[str, Any]:
        """
        Default configuration if nothing is saved.
        """
        return {
            'sp_entity_type_id': 0, # 0 means not configured
            'fields_mapping': {},
            'project_sp_entity_type_id': 0,
            'project_fields_mapping': {},
            'is_configured': False,
            'hourly_rate': 0,
            'legal_entity_directory': {
                'iblock_type_id': 'lists',
                'iblock_id': 0,
                'iblock_code': '',
                'socnet_group_id': 0,
            },
        }

    def get_internal_lists_sync(self, iblock_type_id: str = 'lists', socnet_group_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Returns available Bitrix24 universal lists for configuring internal directories.
        Uses lists.get as recommended by Bitrix24 REST docs.
        """
        start = 0
        items: List[Dict[str, Any]] = []

        while True:
            params: Dict[str, Any] = {
                'IBLOCK_TYPE_ID': iblock_type_id,
                'IBLOCK_ORDER': {
                    'SORT': 'asc',
                    'NAME': 'asc',
                },
                'start': start,
            }
            if iblock_type_id == 'lists_socnet' and socnet_group_id:
                params['SOCNET_GROUP_ID'] = int(socnet_group_id)

            response = self.client._bitrix_token.call_method('lists.get', params)
            result = response.get('result', [])
            total = int(response.get('total') or len(result) or 0)

            if not isinstance(result, list) or not result:
                break

            for row in result:
                items.append({
                    'id': int(row.get('ID')) if str(row.get('ID') or '').isdigit() else row.get('ID'),
                    'name': row.get('NAME') or row.get('TITLE') or f"Список {row.get('ID')}",
                    'code': row.get('CODE') or '',
                    'iblock_type_id': iblock_type_id,
                })

            start += 50
            if start >= total:
                break

        return items

    def get_smart_processes_sync(self) -> List[Dict[str, Any]]:
        """
        Get list of all Smart Processes (dynamic types).
        """
        try:
            response = self.client._bitrix_token.call_method('crm.type.list', {'filter': {}})
        except Exception as exc:
            logger.error("get_smart_processes_sync: crm.type.list failed: %s", exc)
            return []

        raw_result = response.get('result', [])
        if isinstance(raw_result, dict):
            raw_types = raw_result.get('types') or raw_result.get('items') or []
        elif isinstance(raw_result, list):
            raw_types = raw_result
        else:
            raw_types = []

        result: List[Dict[str, Any]] = []
        for raw_type in raw_types:
            if not isinstance(raw_type, dict):
                continue

            entity_type_id = raw_type.get('entityTypeId') or raw_type.get('ENTITY_TYPE_ID')
            type_id = raw_type.get('id') or raw_type.get('ID') or entity_type_id
            title = raw_type.get('title') or raw_type.get('TITLE') or f"SPA {entity_type_id or type_id}"

            if not entity_type_id:
                continue

            result.append({
                'id': type_id,
                'entityTypeId': int(entity_type_id),
                'title': str(title),
            })

        logger.info("get_smart_processes_sync: loaded %s smart processes", len(result))
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

        system_field_fallbacks = {
            'TITLE': {'title': 'TITLE', 'type': 'string', 'isReadOnly': True},
            'ASSIGNED_BY_ID': {'title': 'ASSIGNED_BY_ID', 'type': 'employee', 'isReadOnly': True},
            'STAGE_ID': {'title': 'STAGE_ID', 'type': 'crm_status', 'isReadOnly': True},
            'ID': {'title': 'ID', 'type': 'integer', 'isReadOnly': True},
        }
        for sys_key, sys_meta in system_field_fallbacks.items():
            if sys_key not in fields:
                fields[sys_key] = dict(sys_meta)

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

    def get_project_spa_stages_sync(self, entity_type_id: int) -> Dict[str, Any]:
        """
        Return stage list for a configured Project SPA.
        """
        type_response = self.client._bitrix_token.call_method(
            'crm.type.getByEntityTypeId',
            {'entityTypeId': entity_type_id},
        )
        type_data = type_response.get('result', {}) or {}
        stage_entity_candidates = self._collect_stage_entity_ids(type_data, entity_type_id)

        last_error = None
        for stage_entity_id in stage_entity_candidates:
            try:
                stages_response = self.client._bitrix_token.call_method(
                    'crm.status.list',
                    {
                        'order': {'SORT': 'ASC'},
                        'filter': {'ENTITY_ID': stage_entity_id},
                    },
                )
                stages = stages_response.get('result', [])
                if not isinstance(stages, list):
                    stages = []
                return {
                    'entity_type_id': entity_type_id,
                    'type': type_data,
                    'stage_entity_id': stage_entity_id,
                    'stages': [
                        {
                            'id': row.get('STATUS_ID') or row.get('ID') or '',
                            'name': row.get('NAME') or row.get('NAME_INIT') or row.get('STATUS_ID') or row.get('ID') or '',
                            'sort': int(row.get('SORT') or 0),
                            'system': str(row.get('SYSTEM') or '').upper() == 'Y',
                            'semantics': row.get('SEMANTICS') or (row.get('EXTRA') or {}).get('SEMANTICS'),
                            'color': row.get('COLOR') or (row.get('EXTRA') or {}).get('COLOR'),
                        }
                        for row in stages
                    ],
                }
            except Exception as exc:
                last_error = exc
                logger.warning("Stage list load failed for %s: %s", stage_entity_id, exc)

        raise last_error or RuntimeError(f"Не удалось загрузить стадии Project SPA для entityTypeId={entity_type_id}")

    @staticmethod
    def _collect_stage_entity_ids(type_data: Dict[str, Any], entity_type_id: int) -> List[str]:
        candidates: List[str] = []

        def add_candidate(value: Any) -> None:
            candidate = str(value or '').strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested_value in value.items():
                    key_lower = str(key).lower()
                    if key_lower in {'statusentityid', 'stageentityid', 'status_entity_id', 'stage_entity_id'}:
                        add_candidate(nested_value)
                    elif key_lower in {'entityid', 'entity_id'}:
                        nested_candidate = str(nested_value or '').strip()
                        if nested_candidate.upper().startswith('DYNAMIC_'):
                            add_candidate(nested_candidate)
                    walk(nested_value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(type_data)
        add_candidate(f"DYNAMIC_{entity_type_id}_STAGE")
        type_id = type_data.get('id')
        if type_id not in (None, '', entity_type_id):
            add_candidate(f"DYNAMIC_{type_id}_STAGE")
        add_candidate(f"DYNAMIC_{entity_type_id}")
        if type_id not in (None, '', entity_type_id):
            add_candidate(f"DYNAMIC_{type_id}")

        return candidates
