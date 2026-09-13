/**
 * Шаг «Доходы-расходы» экрана сопоставления полей.
 *
 * До 12.09.2026 шага не было вовсе, а экраны БДДС вели на экран
 * сопоставления кнопкой «Открыть «Настройка полей»» — человек попадал туда,
 * где настроить процесс было негде. Тесты фиксируют:
 *
 * - состав полей совпадает с тем, что заводит установка и читает сервис
 *   операций (сверка с python-файлами, а не с копией в тесте);
 * - автоподбор узнаёт поля установки ТОЧНО по коду;
 * - шаг необязательный: не поднимает баннер, не становится «сейчас здесь»,
 *   не портит «настройка завершена»;
 * - сохранение шлёт конфигурацию целиком с финансовыми ключами;
 * - ссылки с экранов БДДС ведут прямо на шаг.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  FINANCE_APP_SMART_PROCESS_TITLE,
  FINANCE_CONFIG_SAVE_SCOPE,
  FINANCE_MAPPING_ROWS,
  FINANCE_SERVER_REQUIRED_KEYS,
  MAPPING_SETTINGS_PATH,
  PROJECT_MAPPING_ROWS,
  TIMESHEET_MAPPING_ROWS,
  applyFinanceMappingToConfig,
  applySuggestions,
  buildMappingStepLink,
  buildMappingSteps,
  describeMappingKey,
  findFinanceAppSmartProcess,
  getMappingRows,
  isFinanceMappingChanged,
  matchesInstallCode,
  planFinanceMappingSave,
  resolveFinanceMappingNotice,
  resolveMappingBlockStatus,
  resolveMappingHealth,
  resolveMappingOverall,
  resolveMappingStepTarget,
  suggestMappingMatches,
} from '../app/utils/fieldMapping'
import { BDDS_OPERATIONS_SETTINGS_LABEL, BDDS_OPERATIONS_SETTINGS_PATH } from '../app/utils/bddsOperations'
import { describeBddsError } from '../app/utils/bddsErrors'
import type { AppConfigurationPayload, ProjectSpaValidationPayload, SmartProcessFieldOption } from '../app/types/config'

const BACKEND = new URL('../../backends/python/api/main/', import.meta.url)

function readBackend(file: string): string {
  return readFileSync(new URL(file, BACKEND), 'utf-8')
}

function field(id: string, title: string, type: string): SmartProcessFieldOption {
  return { id, title, type }
}

/**
 * Поля процесса 1104 «Доходы-расходы (App)» так, как их отдаёт crm.item.fields:
 * пользовательские поля установки плюс системные поля элемента с теми же
 * названиями («Сумма», «Валюта», «Источник», «Ответственный») — ловушка для
 * подбора по названию.
 */
function financeAppFields(ordinal = 17): SmartProcessFieldOption[] {
  return [
    field('id', 'ID', 'integer'),
    field('title', 'Название', 'string'),
    field('opportunity', 'Сумма', 'double'),
    field('currencyId', 'Валюта', 'crm_currency'),
    field('sourceId', 'Источник', 'crm_status'),
    field('assignedById', 'Ответственный', 'user'),
    field('createdTime', 'Дата создания', 'datetime'),
    field(`ufCrm${ordinal}ProjectItemId`, 'ID карточки проекта', 'integer'),
    field(`ufCrm${ordinal}OperationType`, 'Тип операции', 'string'),
    field(`ufCrm${ordinal}Amount`, 'Сумма', 'double'),
    field(`ufCrm${ordinal}Currency`, 'Валюта', 'string'),
    field(`ufCrm${ordinal}OperationDate`, 'Дата операции', 'date'),
    field(`ufCrm${ordinal}Source`, 'Источник', 'string'),
    field(`ufCrm${ordinal}DealId`, 'ID сделки', 'integer'),
    field(`ufCrm${ordinal}Comment`, 'Комментарий', 'string'),
    field(`ufCrm${ordinal}ResponsibleUserId`, 'Ответственный', 'employee'),
  ]
}

function fullFinanceMapping(ordinal = 17): Record<string, string> {
  const camel = (code: string) => code.toLowerCase().split('_').map(part => part[0]!.toUpperCase() + part.slice(1)).join('')
  return FINANCE_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
    acc[row.key] = `ufCrm${ordinal}${camel(row.installCode!)}`
    return acc
  }, {})
}

function readyTimesheetAndProject() {
  const timesheet = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: TIMESHEET_MAPPING_ROWS.map(row => field(`UF_${row.key}`, row.label, row.acceptedTypes?.[0] || 'string')),
    mapping: TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {}),
  })
  const project = resolveMappingBlockStatus({
    block: 'project',
    entityTypeId: 1102,
    spFields: PROJECT_MAPPING_ROWS.map(row => field(`UF_${row.key}`, row.label, row.acceptedTypes?.[0] || 'string')),
    mapping: PROJECT_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {}),
  })
  return { timesheet, project }
}

// region Состав полей сверяется с бэкендом

test('состав и суффиксы полей совпадают с FINANCE_FIELD_DEFINITIONS установки', () => {
  const source = readBackend('installation_service.py')
  const block = source.match(/FINANCE_FIELD_DEFINITIONS[^{]*\{([\s\S]*?)\n\}/)
  assert.ok(block, 'в installation_service.py не нашлось FINANCE_FIELD_DEFINITIONS')

  const fromBackend = [...block[1]!.matchAll(/'([a-z_]+)':\s*\{'suffix':\s*'([A-Z_]+)'/g)]
    .map(match => [match[1], match[2]])
  const fromScreen = FINANCE_MAPPING_ROWS.map(row => [row.key, row.installCode])

  assert.equal(fromBackend.length, 9)
  assert.deepEqual(
    [...fromScreen].sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    [...fromBackend].sort((a, b) => String(a[0]).localeCompare(String(b[0])))
  )
})

test('обязательные ключи — копия required_keys сервиса операций и помечены critical', () => {
  const source = readBackend('finance_operation_service.py')
  const match = source.match(/required_keys\s*=\s*\(([^)]*)\)/)
  assert.ok(match, 'в finance_operation_service.py не нашлось required_keys')

  const fromBackend = [...match[1]!.matchAll(/"([a-z_]+)"/g)].map(item => item[1])
  assert.deepEqual([...FINANCE_SERVER_REQUIRED_KEYS], fromBackend)

  const critical = FINANCE_MAPPING_ROWS.filter(row => row.importance === 'critical').map(row => row.key)
  assert.deepEqual([...critical].sort(), [...fromBackend].sort())
})

test('у каждого поля написано, что сломается без него', () => {
  for (const row of FINANCE_MAPPING_ROWS) {
    assert.ok(row.breaks.length > 20, `у «${row.label}» нет последствий`)
    assert.ok(row.creatable, `«${row.label}» должно создаваться кнопкой: create_single_field умеет finance`)
  }
  assert.equal(getMappingRows('finance'), FINANCE_MAPPING_ROWS)
  assert.equal(describeMappingKey('finance', 'operation_date'), 'Дата операции')
})

test('готовый процесс установки называется так же, как в SMART_PROCESS_DEFINITIONS', () => {
  const source = readBackend('installation_service.py')
  assert.ok(source.includes(`'title': '${FINANCE_APP_SMART_PROCESS_TITLE}'`))
  assert.ok(source.includes(`'code': 'finance_app'`))
})

// endregion

// region Автоподбор по коду установки

test('код поля узнаётся целиком в обеих формах и без номера, но не по вхождению', () => {
  assert.equal(matchesInstallCode('ufCrm17Amount', 'AMOUNT'), true)
  assert.equal(matchesInstallCode('UF_CRM_17_AMOUNT', 'AMOUNT'), true)
  assert.equal(matchesInstallCode('UF_CRM_AMOUNT', 'AMOUNT'), true)
  assert.equal(matchesInstallCode('ufCrm17ProjectItemId', 'PROJECT_ITEM_ID'), true)

  assert.equal(matchesInstallCode('ufCrm17AmountVat', 'AMOUNT'), false)
  assert.equal(matchesInstallCode('ufCrm17TotalAmount', 'AMOUNT'), false)
  assert.equal(matchesInstallCode('opportunity', 'AMOUNT'), false)
  assert.equal(matchesInstallCode('ufCrm17ResponsibleUserId', 'ID'), false)
  assert.equal(matchesInstallCode('ufCrm17Amount', undefined), false)
})

test('на процессе установки все девять полей подбираются точно по коду, мимо системных тёзок', () => {
  const found = suggestMappingMatches(FINANCE_MAPPING_ROWS, financeAppFields(17), {})

  assert.equal(found.length, 9)
  assert.ok(found.every(item => item.source === 'install'), 'все совпадения должны быть по коду установки')

  const byKey = Object.fromEntries(found.map(item => [item.key, item.fieldId]))
  assert.deepEqual(byKey, fullFinanceMapping(17))
  assert.match(found[0]!.reason, /точно/)
})

test('подбор ничего не применяет сам: сопоставление меняется только после «Применить»', () => {
  const mapping: Record<string, string> = {}
  const found = suggestMappingMatches(FINANCE_MAPPING_ROWS, financeAppFields(17), mapping)

  assert.deepEqual(mapping, {})
  assert.deepEqual(applySuggestions(mapping, found), fullFinanceMapping(17))
})

test('без полей установки подбор идёт по названию и не берёт системное поле чужого типа', () => {
  const fields = [
    field('sourceId', 'Источник', 'crm_status'),
    field('currencyId', 'Валюта', 'crm_currency'),
    field('ufCrm3Src', 'Источник', 'string'),
    field('ufCrm3Sum', 'Сумма операции', 'double'),
  ]

  const found = suggestMappingMatches(FINANCE_MAPPING_ROWS, fields, {})
  const byKey = Object.fromEntries(found.map(item => [item.key, item]))

  assert.equal(byKey.source?.fieldId, 'ufCrm3Src')
  assert.equal(byKey.source?.source, 'label')
  assert.equal(byKey.amount?.fieldId, 'ufCrm3Sum')
  assert.equal(byKey.currency, undefined, 'currencyId не строка — предлагать его под «Валюту» нельзя')
})

test('уже сопоставленное поле подбор не трогает и не отдаёт другому ключу', () => {
  const found = suggestMappingMatches(FINANCE_MAPPING_ROWS, financeAppFields(17), {
    amount: 'ufCrm17Amount',
  })

  assert.equal(found.some(item => item.key === 'amount'), false)
  assert.equal(found.some(item => item.fieldId === 'ufCrm17Amount'), false)
})

test('готовый процесс находится по коду, а без кода — по названию', () => {
  const processes = [
    { entityTypeId: 1100, title: 'Учет трудозатрат (App)', code: 'timesheet_app' },
    { entityTypeId: 1104, title: 'Переименовали на портале', code: 'finance_app' },
  ]
  assert.equal(findFinanceAppSmartProcess(processes)?.entityTypeId, 1104)
  assert.equal(findFinanceAppSmartProcess([{ entityTypeId: 1104, title: 'Доходы-расходы (App)' }])?.entityTypeId, 1104)
  assert.equal(findFinanceAppSmartProcess([{ entityTypeId: 7, title: 'Сделки' }]), null)
})

// endregion

// region Шаг необязательный

test('ненастроенные «Доходы-расходы» не поднимают баннер «сопоставление не заполнено»', () => {
  const config: AppConfigurationPayload = {
    sp_entity_type_id: 1100,
    fields_mapping: TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {}),
    project_sp_entity_type_id: 1102,
    project_fields_mapping: PROJECT_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {}),
    finance_sp_entity_type_id: 0,
    finance_fields_mapping: {},
  }

  assert.equal(resolveMappingHealth(config).level, 'ok')
  assert.equal(resolveMappingHealth({ ...config, finance_sp_entity_type_id: 1104, finance_fields_mapping: { amount: 'x' } }).level, 'ok')
})

test('шаг «Доходы-расходы» в полосе — «по желанию», не «сейчас здесь» и не в счёте шагов', () => {
  const { timesheet, project } = readyTimesheetAndProject()
  const finance = resolveMappingBlockStatus({ block: 'finance', entityTypeId: 0, spFields: [], mapping: {} })
  const validation = { is_valid: true, is_configured: true } as ProjectSpaValidationPayload

  const steps = buildMappingSteps({ timesheet, project, validation, finance })
  const financeStep = steps.find(step => step.id === 'finance')

  assert.equal(steps.length, 6)
  assert.equal(financeStep?.state, 'optional')
  assert.equal(financeStep?.optional, true)
  assert.equal(financeStep?.anchor, 'block-finance-process')
  assert.equal(steps.filter(step => step.state === 'current').length, 0)

  const overall = resolveMappingOverall(steps, { timesheet, project })
  assert.equal(overall.state, 'ready')
  assert.equal(overall.totalSteps, 5)
  assert.equal(overall.doneSteps, 5)
})

test('пока обязательное не настроено, «сейчас здесь» остаётся на обязательном шаге', () => {
  const empty = { entityTypeId: 0, spFields: [], mapping: {} }
  const steps = buildMappingSteps({
    timesheet: resolveMappingBlockStatus({ ...empty, block: 'timesheet' }),
    project: resolveMappingBlockStatus({ ...empty, block: 'project' }),
    finance: resolveMappingBlockStatus({ ...empty, block: 'finance' }),
    financeNeeded: true,
  })

  assert.equal(steps[0]?.state, 'current')
  assert.equal(steps.find(step => step.id === 'finance')?.state, 'optional')
})

test('начатая, но неполная настройка при подключённом БДДС — «есть проблема», без подписки — «по желанию»', () => {
  const { timesheet, project } = readyTimesheetAndProject()
  const finance = resolveMappingBlockStatus({
    block: 'finance',
    entityTypeId: 1104,
    spFields: financeAppFields(17),
    mapping: { amount: 'ufCrm17Amount' },
  })

  const withBdds = buildMappingSteps({ timesheet, project, finance, financeNeeded: true })
  const withoutBdds = buildMappingSteps({ timesheet, project, finance, financeNeeded: false })

  assert.equal(finance.state, 'partial')
  assert.equal(withBdds.find(step => step.id === 'finance')?.state, 'attention')
  assert.equal(withoutBdds.find(step => step.id === 'finance')?.state, 'optional')
})

test('полное сопоставление — шаг «готово»; без переданного статуса шага нет вовсе', () => {
  const { timesheet, project } = readyTimesheetAndProject()
  const finance = resolveMappingBlockStatus({
    block: 'finance',
    entityTypeId: 1104,
    spFields: financeAppFields(17),
    mapping: fullFinanceMapping(17),
  })

  assert.equal(finance.state, 'ready')
  assert.equal(buildMappingSteps({ timesheet, project, finance }).find(step => step.id === 'finance')?.state, 'done')
  assert.equal(buildMappingSteps({ timesheet, project }).length, 5)
})

test('подсказка пустого шага говорит, какой процесс выбрать и что он только для БДДС', () => {
  const status = resolveMappingBlockStatus({ block: 'finance', entityTypeId: 0, spFields: [], mapping: {} })
  assert.match(status.headline, /«Доходы-расходы» не выбран/)
  assert.match(status.nextStep, /Доходы-расходы \(App\)/)
  assert.match(status.nextStep, /только для операций БДДС/)
})

test('напоминание про «Доходы-расходы» — только при подключённом БДДС и с ссылкой на шаг', () => {
  const base: AppConfigurationPayload = { finance_sp_entity_type_id: 0, finance_fields_mapping: {} }

  assert.equal(resolveFinanceMappingNotice(base, false), null)
  assert.equal(resolveFinanceMappingNotice(null, true), null)

  const notConnected = resolveFinanceMappingNotice(base, true)
  assert.equal(notConnected?.to, '/settings/mapping?step=finance')
  assert.match(notConnected!.title, /не подключены/)

  const partial = resolveFinanceMappingNotice({
    finance_sp_entity_type_id: 1104,
    finance_fields_mapping: { amount: 'ufCrm17Amount' },
  }, true)
  assert.deepEqual(partial?.missingLabels, ['ID карточки проекта', 'Тип операции', 'Дата операции', 'Источник'])

  const ready = resolveFinanceMappingNotice({
    finance_sp_entity_type_id: 1104,
    finance_fields_mapping: fullFinanceMapping(17),
  }, true)
  assert.equal(ready, null)
})

// endregion

// region Сохранение

test('сохранение шлёт конфигурацию целиком: финансовые ключи подменены, остальное не тронуто', () => {
  const saved: AppConfigurationPayload = {
    sp_entity_type_id: 1100,
    fields_mapping: { id_zadachi: 'ufCrm5TaskId' },
    project_sp_entity_type_id: 1102,
    project_fields_mapping: { title: 'TITLE', stage_id: 'STAGE_ID' },
    hourly_rate: 1500,
    billing_accountants: ['7'],
    finance_sp_entity_type_id: 0,
    finance_fields_mapping: {},
  }

  const next = applyFinanceMappingToConfig(saved, {
    entityTypeId: 1104,
    mapping: { amount: 'ufCrm17Amount', comment: '' },
  })

  assert.equal(next.finance_sp_entity_type_id, 1104)
  assert.deepEqual(next.finance_fields_mapping, { amount: 'ufCrm17Amount' }, 'пустые значения не отправляются')
  for (const key of ['sp_entity_type_id', 'fields_mapping', 'project_sp_entity_type_id', 'project_fields_mapping', 'hourly_rate', 'billing_accountants']) {
    assert.deepEqual(next[key], saved[key], `ключ ${key} не должен меняться`)
  }
  assert.equal(saved.finance_sp_entity_type_id, 0, 'исходная конфигурация не мутирует')

  assert.equal(applyFinanceMappingToConfig(saved, { entityTypeId: null, mapping: {} }).finance_sp_entity_type_id, 0)
  assert.equal(FINANCE_CONFIG_SAVE_SCOPE, 'finance')
})

test('признак scope=finance понимает сервер', () => {
  const views = readBackend('views.py')
  assert.ok(views.includes(`CONFIG_SAVE_SCOPE_FINANCE = "${FINANCE_CONFIG_SAVE_SCOPE}"`))
})

test('план сохранения: пусто, отвязка, черновик и готово различаются', () => {
  const empty = resolveMappingBlockStatus({ block: 'finance', entityTypeId: 0, spFields: [], mapping: {} })

  const skip = planFinanceMappingSave({ selectedFinanceSpId: 0, savedFinanceSpId: 0, financeStatus: empty, mapping: {} })
  assert.equal(skip.kind, 'skip')
  assert.match(skip.note, /необязательный/)

  const unlink = planFinanceMappingSave({ selectedFinanceSpId: null, savedFinanceSpId: 1104, financeStatus: empty, mapping: {} })
  assert.equal(unlink.kind, 'unlink')
  assert.equal(unlink.financeSpIdToSend, 0)

  const partialMapping = { amount: 'ufCrm17Amount' }
  const draft = planFinanceMappingSave({
    selectedFinanceSpId: 1104,
    savedFinanceSpId: 0,
    financeStatus: resolveMappingBlockStatus({ block: 'finance', entityTypeId: 1104, spFields: financeAppFields(), mapping: partialMapping }),
    mapping: partialMapping,
  })
  assert.equal(draft.kind, 'draft')
  assert.equal(draft.financeSpIdToSend, 1104, 'черновик сохраняется — сервер конфигурацию операций не проверяет')
  assert.deepEqual(draft.missing.map(item => item.key), ['project_item_id', 'operation_type', 'operation_date', 'source'])

  const full = fullFinanceMapping()
  const ready = planFinanceMappingSave({
    selectedFinanceSpId: 1104,
    savedFinanceSpId: 1090,
    financeStatus: resolveMappingBlockStatus({ block: 'finance', entityTypeId: 1104, spFields: financeAppFields(), mapping: full }),
    mapping: full,
  })
  assert.equal(ready.kind, 'ready')
  assert.match(ready.note, /ID 1090/, 'смена процесса предупреждает, что прежние операции пропадут из приложения')
})

test('несохранённые изменения шага видны, одинаковое сопоставление изменением не считается', () => {
  const saved: AppConfigurationPayload = { finance_sp_entity_type_id: '1104', finance_fields_mapping: { amount: 'ufCrm17Amount' } }

  assert.equal(isFinanceMappingChanged(saved, { entityTypeId: 1104, mapping: { amount: 'ufCrm17Amount', comment: '' } }), false)
  assert.equal(isFinanceMappingChanged(saved, { entityTypeId: 1104, mapping: {} }), true)
  assert.equal(isFinanceMappingChanged(saved, { entityTypeId: 1106, mapping: { amount: 'ufCrm17Amount' } }), true)
  assert.equal(isFinanceMappingChanged({}, { entityTypeId: null, mapping: {} }), false)
})

// endregion

// region Ссылки на шаг

test('ссылка на шаг — параметр адреса экрана сопоставления, и экран её понимает', () => {
  assert.equal(buildMappingStepLink('finance'), `${MAPPING_SETTINGS_PATH}?step=finance`)

  assert.deepEqual(resolveMappingStepTarget('finance'), {
    block: 'finance',
    anchor: 'block-finance-process',
    focusId: 'finance-process',
  })
  assert.equal(resolveMappingStepTarget(['project'])?.anchor, 'block-project-process')
  assert.equal(resolveMappingStepTarget('constructor'), null)
  assert.equal(resolveMappingStepTarget('__proto__'), null)
  assert.equal(resolveMappingStepTarget(undefined), null)
})

test('кнопка из отказа «не настроен» на экранах БДДС ведёт прямо на шаг «Доходы-расходы»', () => {
  assert.equal(BDDS_OPERATIONS_SETTINGS_PATH, '/settings/mapping?step=finance')
  assert.match(BDDS_OPERATIONS_SETTINGS_LABEL, /Доходы-расходы/)
  assert.doesNotMatch(BDDS_OPERATIONS_SETTINGS_LABEL, /Настройка полей/)
})

test('подсказка к отказу БДДС называет существующий экран и шаг', () => {
  const payload = { error: 'Finance SPA is not configured', code: 'finance_spa_not_configured' }
  const view = describeBddsError({ response: { status: 409, _data: payload }, status: 409, data: payload })
  assert.equal(view.isSmartProcessMissing, true)
  assert.match(view.hint, /Сопоставление полей/)
  assert.match(view.hint, /Доходы-расходы/)
  assert.doesNotMatch(view.hint, /Настройка полей/)
})

// endregion
