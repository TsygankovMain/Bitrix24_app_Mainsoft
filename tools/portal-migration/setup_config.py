"""Настраивает установленное приложение на портале: маппинг смарт-процессов и полей.

Смарт-процессы на nfr-mainsoft уже созданы приложением ранее (1100 «Учет
трудозатрат (App)», 1102 «Проекты (App)», 1104 «Доходы-расходы (App)»),
поэтому ничего не создаём — сопоставляем существующие поля с ключами,
которые ждёт код, и сохраняем конфигурацию в app.option портала.

Соответствие строится по суффиксу: определение поля объявляет suffix TASK_ID,
в смарт-процессе оно живёт как ufCrm44TaskId. Сравниваем нормализованные имена,
а не порядок — порядок полей в ответе Битрикса не гарантирован.

    docker exec timesheet-demo-app-1 python /app/setup_config.py
"""
import os
import re
import sys

import django

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from main.models import Bitrix24Account  # noqa: E402
from main.configuration_service import ConfigurationService  # noqa: E402
from main.installation_service import (  # noqa: E402
    TIMESHEET_FIELD_DEFINITIONS,
    PROJECT_FIELD_DEFINITIONS,
    FINANCE_FIELD_DEFINITIONS,
)

TIMESHEET_ET = 1100
PROJECT_ET = 1102
FINANCE_ET = 1104


def to_suffix(field_name: str, type_id: int) -> str:
    """ufCrm44TaskId -> TASK_ID (для типа 44)."""
    tail = re.sub(rf'^ufCrm_?{type_id}_?', '', field_name)
    tail = re.sub(r'(?<!^)(?=[A-Z])', '_', tail)
    return tail.upper().strip('_')


def build_mapping(fields: dict, definitions: dict, type_id: int) -> tuple:
    by_suffix = {to_suffix(name, type_id): name for name in fields
                 if name.lower().startswith('ufcrm')}
    mapping, missing = {}, []
    for key, definition in definitions.items():
        if definition.get('system'):
            continue
        found = by_suffix.get(definition['suffix'])
        if found:
            mapping[key] = found
        else:
            missing.append((key, definition['suffix']))
    return mapping, missing


def fields_of(client, entity_type_id: int) -> dict:
    response = client._bitrix_token.call_method('crm.item.fields',
                                                {'entityTypeId': entity_type_id})
    return response.get('result', {}).get('fields', {})


def main() -> int:
    account = Bitrix24Account.objects.order_by('-created_at_utc').first()
    if not account:
        print('портал не найден: приложение не установлено')
        return 1
    print('портал:', account.domain_url)

    client = account.client
    config_service = ConfigurationService(client, account)

    plan = (
        ('списания', TIMESHEET_ET, TIMESHEET_FIELD_DEFINITIONS, 'sp_entity_type_id', 'fields_mapping', 44),
        ('проекты', PROJECT_ET, PROJECT_FIELD_DEFINITIONS, 'project_sp_entity_type_id', 'project_fields_mapping', 46),
        ('финансы', FINANCE_ET, FINANCE_FIELD_DEFINITIONS, 'finance_sp_entity_type_id', 'finance_fields_mapping', 48),
    )

    config = dict(config_service.get_configuration_sync())
    total_missing = []
    for label, entity_type_id, definitions, id_key, map_key, type_id in plan:
        fields = fields_of(client, entity_type_id)
        if not fields:
            print(f'{label}: смарт-процесс {entity_type_id} не отвечает, пропускаю')
            continue
        mapping, missing = build_mapping(fields, definitions, type_id)
        config[id_key] = entity_type_id
        config[map_key] = mapping
        print(f'{label}: СП {entity_type_id}, сопоставлено полей {len(mapping)}'
              + (f', не найдено {len(missing)}' if missing else ''))
        for key, suffix in missing:
            print(f'    нет поля под ключ {key} (ожидался суффикс {suffix})')
            total_missing.append((label, key, suffix))

    config['is_configured'] = True
    config_service.save_configuration_sync(config)

    saved = ConfigurationService(client, account).get_configuration_sync()
    print('\nсохранено в портале:')
    print('  списания  :', saved.get('sp_entity_type_id'), '| полей', len(saved.get('fields_mapping') or {}))
    print('  проекты   :', saved.get('project_sp_entity_type_id'), '| полей', len(saved.get('project_fields_mapping') or {}))
    print('  финансы   :', saved.get('finance_sp_entity_type_id'), '| полей', len(saved.get('finance_fields_mapping') or {}))
    print('  настроено :', saved.get('is_configured'))
    return 0 if not total_missing else 2


if __name__ == '__main__':
    raise SystemExit(main())
