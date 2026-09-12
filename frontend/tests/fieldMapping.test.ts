/**
 * Сопоставление полей: состояния готовности, автоподбор, план сохранения и
 * человеческие тексты ошибок.
 *
 * Главный инвариант этого файла — «человек не должен упереться в 400».
 * Сервер (save_configuration в backends/python/api/main/views.py) валидирует
 * проектный смарт-процесс целиком, как только в конфигурации есть
 * project_sp_entity_type_id > 0, и на неполном сопоставлении отклоняет
 * запрос, НЕ сохранив ничего. Поэтому planMappingSave обязан различать три
 * случая и ни в одном не отправлять заведомо отклоняемый запрос.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  PROJECT_MAPPING_ROWS,
  PROJECT_SPA_SERVER_REQUIRED_KEYS,
  PROJECT_STAGE_FIELD_KEY,
  TIMESHEET_MAPPING_ROWS,
  applySuggestions,
  buildFieldOptionGroups,
  buildMappingSteps,
  describeMappingKey,
  describeMappingSaveError,
  describeProjectSpaValidation,
  describeSuggestions,
  getLegacyStageValue,
  isFieldTypeCompatible,
  isMappedFieldMissing,
  mergeCreatedFieldMapping,
  normalizeMappingState,
  normalizeProjectMappingState,
  planMappingSave,
  resolveMappingBlockStatus,
  resolveMappingHealth,
  resolveMappingOverall,
  serializeProjectMappingState,
  suggestMappingMatches,
  type MappingRow,
} from '../app/utils/fieldMapping'
import type { ProjectSpaValidationPayload, SmartProcessFieldOption } from '../app/types/config'

function field(id: string, title: string, type: string): SmartProcessFieldOption {
  return { id, title, type }
}

/** Полное сопоставление проекта: каждому ключу — своё поле. */
function fullProjectMapping(): Record<string, string> {
  return PROJECT_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
    acc[row.key] = `UF_CRM_${row.key.toUpperCase()}`
    return acc
  }, {})
}

function projectFields(): SmartProcessFieldOption[] {
  return PROJECT_MAPPING_ROWS.map(row => field(
    `UF_CRM_${row.key.toUpperCase()}`,
    row.label,
    row.acceptedTypes?.[0] || 'string'
  ))
}

// region Состав полей

test('состав полей проекта совпадает с тем, что требует сервер', () => {
  const rowKeys = PROJECT_MAPPING_ROWS
    .map(row => (row.key === PROJECT_STAGE_FIELD_KEY ? 'stage_id' : row.key))
    .sort()

  assert.deepEqual(rowKeys, [...PROJECT_SPA_SERVER_REQUIRED_KEYS].sort())
})

test('у каждого поля написано, что сломается без него', () => {
  for (const row of [...TIMESHEET_MAPPING_ROWS, ...PROJECT_MAPPING_ROWS]) {
    assert.ok(row.breaks.length > 20, `поле ${row.key}: нет объяснения последствий`)
    assert.ok(row.desc.length > 5, `поле ${row.key}: нет описания содержимого`)
  }
})

test('все поля проекта обязательны — необязательных среди них нет', () => {
  assert.ok(PROJECT_MAPPING_ROWS.every(row => row.importance === 'critical'))
})

test('serverный ключ стадии переводится в название поля', () => {
  assert.equal(describeMappingKey('project', 'stage_id'), 'Стадия проекта')
  assert.equal(describeMappingKey('project', 'company_id'), 'Компания клиента')
  assert.equal(describeMappingKey('project', 'что_то_чужое'), 'что_то_чужое')
})

// endregion

// region Нормализация

test('пустые значения из сопоставления выбрасываются', () => {
  assert.deepEqual(
    normalizeMappingState({ a: 'UF_A', b: '', c: undefined as unknown as string }),
    { a: 'UF_A' }
  )
})

test('стадия читается из любого из пяти исторических ключей', () => {
  assert.equal(getLegacyStageValue({ project_fields_mapping: { stage_id: 'UF_S' } }), 'UF_S')
  assert.equal(getLegacyStageValue({ manual_stage: 'UF_M' }), 'UF_M')
  assert.equal(getLegacyStageValue({}), '')
})

test('экран видит одну стадию, а сервер получает все пять ключей', () => {
  const screenState = normalizeProjectMappingState({
    project_fields_mapping: { title: 'UF_T', effective_stage: 'UF_S' },
  })

  assert.deepEqual(screenState, { title: 'UF_T', stage: 'UF_S' })

  const forServer = serializeProjectMappingState(screenState)
  assert.equal(forServer.stage_id, 'UF_S')
  assert.equal(forServer.stage, 'UF_S')
  assert.equal(forServer.manual_stage, 'UF_S')
  assert.equal(forServer.effective_stage, 'UF_S')
  assert.equal(forServer.project_stage, 'UF_S')
})

test('созданное поле берётся из конфигурации сервера, а не из запасного id', () => {
  const next = mergeCreatedFieldMapping({}, { hourly_rate: 'UF_FROM_CONFIG' }, 'hourly_rate', 'UF_FALLBACK')
  assert.equal(next.hourly_rate, 'UF_FROM_CONFIG')
})

test('запасной id используется, когда конфигурация пришла без нового ключа', () => {
  const next = mergeCreatedFieldMapping({}, {}, 'hourly_rate', 777)
  assert.equal(next.hourly_rate, '777')
})

// endregion

// region Типы и варианты выбора

test('типы полей принимаются по тем же псевдонимам, что у сервера', () => {
  const dateRow = TIMESHEET_MAPPING_ROWS.find(row => row.key === 'data') as MappingRow
  assert.ok(isFieldTypeCompatible(dateRow, 'datetime'))
  assert.ok(!isFieldTypeCompatible(dateRow, 'string'))

  const stageRow = PROJECT_MAPPING_ROWS.find(row => row.key === PROJECT_STAGE_FIELD_KEY) as MappingRow
  assert.ok(isFieldTypeCompatible(stageRow, 'crm_status'))
  assert.ok(isFieldTypeCompatible(stageRow, 'status'))

  const companyRow = PROJECT_MAPPING_ROWS.find(row => row.key === 'company_id') as MappingRow
  assert.ok(isFieldTypeCompatible(companyRow, 'crm'))
  assert.ok(isFieldTypeCompatible(companyRow, 'string'))
})

test('поле неподходящего типа не исчезает, а уходит в отдельную группу', () => {
  const dateRow = TIMESHEET_MAPPING_ROWS.find(row => row.key === 'data') as MappingRow
  const groups = buildFieldOptionGroups(dateRow, [
    field('UF_DATE', 'Дата списания', 'date'),
    field('UF_TEXT', 'Заметка', 'string'),
  ])

  assert.deepEqual(groups.suitable.map(option => option.value), ['UF_DATE'])
  assert.deepEqual(groups.other.map(option => option.value), ['UF_TEXT'])
})

test('уже выбранное поле остаётся в списке, даже если тип не подходит', () => {
  const dateRow = TIMESHEET_MAPPING_ROWS.find(row => row.key === 'data') as MappingRow
  const groups = buildFieldOptionGroups(dateRow, [field('UF_TEXT', 'Заметка', 'string')], 'UF_TEXT')

  assert.deepEqual(groups.suitable.map(option => option.value), ['UF_TEXT'])
  assert.equal(groups.other.length, 0)
})

test('сопоставление на удалённое поле распознаётся как битое', () => {
  const fields = [field('UF_A', 'A', 'string')]
  assert.ok(isMappedFieldMissing('UF_GONE', fields))
  assert.ok(!isMappedFieldMissing('uf_a', fields), 'регистр кода поля не должен ломать сверку')
  assert.ok(!isMappedFieldMissing('', fields))
  assert.ok(!isMappedFieldMissing('UF_GONE', []), 'без загруженных полей судить нельзя')
})

// endregion

// region Состояния готовности

test('смарт-процесс не выбран — состояние «процесса нет» и совет выбрать', () => {
  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 0,
    spFields: [],
    mapping: {},
  })

  assert.equal(status.state, 'no-process')
  assert.match(status.headline, /не выбран/)
  assert.match(status.nextStep, /Выберите смарт-процесс/)
})

test('процесс выбран, а поля не загружены — это отдельное состояние', () => {
  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [],
    mapping: {},
  })

  assert.equal(status.state, 'no-fields')
  assert.match(status.nextStep, /Обновить список полей/)
})

test('поля есть, сопоставлений нет — состояние «пусто», совет про автоподбор', () => {
  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [field('UF_A', 'A', 'string')],
    mapping: {},
  })

  assert.equal(status.state, 'empty')
  assert.match(status.nextStep, /Подобрать автоматически/)
})

test('частичное сопоставление называет, сколько обязательных осталось', () => {
  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [field('UF_TASK', 'ID задачи', 'integer')],
    mapping: { id_zadachi: 'UF_TASK' },
  })

  assert.equal(status.state, 'partial')
  assert.equal(status.requiredMapped, 1)
  assert.ok(status.missingCritical.some(row => row.key === 'kolichestvo_chasov'))
  assert.match(status.headline, /Сопоставлено 1 из/)
})

test('одно недостающее поле называется по имени, а не числом', () => {
  const mapping = TIMESHEET_MAPPING_ROWS
    .filter(row => row.importance !== 'optional' && row.key !== 'client_inn')
    .reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {})

  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: TIMESHEET_MAPPING_ROWS.map(row => field(`UF_${row.key}`, row.label, 'string')),
    mapping,
  })

  assert.equal(status.state, 'partial')
  assert.match(status.nextStep, /«ИНН клиента»/)
})

test('необязательные поля не мешают состоянию «готово»', () => {
  const mapping = TIMESHEET_MAPPING_ROWS
    .filter(row => row.importance !== 'optional')
    .reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {})

  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: TIMESHEET_MAPPING_ROWS.map(row => field(`UF_${row.key}`, row.label, 'string')),
    mapping,
  })

  assert.equal(status.state, 'ready')
  assert.equal(status.missingOptional.length, 2)
  assert.match(status.headline, /необязательных не хватает: 2/)
})

test('битые сопоставления видны отдельно от недостающих', () => {
  const status = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [field('UF_TASK', 'ID задачи', 'integer')],
    mapping: { id_zadachi: 'UF_TASK', kolichestvo_chasov: 'UF_DELETED' },
  })

  assert.deepEqual(status.brokenRows.map(row => row.key), ['kolichestvo_chasov'])
})

test('полоса прогресса подсвечивает ровно один текущий шаг', () => {
  const timesheet = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [field('UF_TASK', 'ID задачи', 'integer')],
    mapping: { id_zadachi: 'UF_TASK' },
  })
  const project = resolveMappingBlockStatus({
    block: 'project',
    entityTypeId: 0,
    spFields: [],
    mapping: {},
  })

  const steps = buildMappingSteps({ timesheet, project, validation: null })

  assert.equal(steps.length, 5)
  assert.equal(steps.filter(step => step.state === 'current').length, 1)
  assert.equal(steps[0]?.state, 'done')
  assert.equal(steps[1]?.state, 'current')
  assert.equal(steps[2]?.state, 'todo')
})

test('шаг с битым сопоставлением помечается как проблемный, а не как пройденный', () => {
  const timesheet = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields: [field('UF_A', 'A', 'string')],
    mapping: { id_zadachi: 'UF_GONE' },
  })
  const project = resolveMappingBlockStatus({
    block: 'project',
    entityTypeId: 0,
    spFields: [],
    mapping: {},
  })

  const steps = buildMappingSteps({ timesheet, project, validation: null })
  assert.equal(steps[1]?.state, 'attention')
})

test('ничего не настроено — итог объясняет, чем это грозит', () => {
  const empty = { block: 'timesheet' as const, entityTypeId: 0, spFields: [], mapping: {} }
  const timesheet = resolveMappingBlockStatus(empty)
  const project = resolveMappingBlockStatus({ ...empty, block: 'project' })
  const steps = buildMappingSteps({ timesheet, project, validation: null })

  const overall = resolveMappingOverall(steps, { timesheet, project })

  assert.equal(overall.state, 'not-started')
  assert.match(overall.text, /пустыми/)
})

test('всё сопоставлено и проверка пройдена — итог «настройка завершена»', () => {
  const spFields = TIMESHEET_MAPPING_ROWS.map(row => field(`UF_${row.key}`, row.label, 'string'))
  const timesheet = resolveMappingBlockStatus({
    block: 'timesheet',
    entityTypeId: 1100,
    spFields,
    mapping: TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
      acc[row.key] = `UF_${row.key}`
      return acc
    }, {}),
  })
  const project = resolveMappingBlockStatus({
    block: 'project',
    entityTypeId: 1102,
    spFields: projectFields(),
    mapping: fullProjectMapping(),
  })

  const steps = buildMappingSteps({
    timesheet,
    project,
    validation: { is_valid: true, is_configured: true } as ProjectSpaValidationPayload,
  })

  assert.equal(resolveMappingOverall(steps, { timesheet, project }).state, 'ready')
})

// endregion

// region План сохранения: обход 400

function projectStatusWith(mapping: Record<string, string>, entityTypeId = 1102) {
  return resolveMappingBlockStatus({
    block: 'project',
    entityTypeId,
    spFields: projectFields(),
    mapping,
  })
}

test('проектный процесс не выбран — сохраняем целиком, без валидации на сервере', () => {
  const plan = planMappingSave({
    selectedProjectSpId: null,
    savedProjectSpId: 0,
    projectStatus: projectStatusWith({}, 0),
  })

  assert.equal(plan.kind, 'full')
  assert.equal(plan.kind === 'full' ? plan.projectSpIdToSend : -1, 0)
})

test('проектное сопоставление полное — сохраняем целиком', () => {
  const plan = planMappingSave({
    selectedProjectSpId: 1102,
    savedProjectSpId: 1102,
    projectStatus: projectStatusWith(fullProjectMapping()),
  })

  assert.equal(plan.kind, 'full')
  assert.equal(plan.kind === 'full' ? plan.projectSpIdToSend : -1, 1102)
})

test('процесс выбран в черновике и неполон — сохраняем только списания, без 400', () => {
  const partial = fullProjectMapping()
  delete partial.hourly_rate

  const plan = planMappingSave({
    selectedProjectSpId: 1102,
    savedProjectSpId: 0,
    projectStatus: projectStatusWith(partial),
  })

  assert.equal(plan.kind, 'timesheet-only')
  assert.equal(
    plan.kind === 'timesheet-only' ? plan.projectSpIdToSend : -1,
    0,
    'в запрос обязан уйти 0, иначе сервер запустит валидацию и откажет'
  )
  assert.match(plan.note, /не теряется|сохранятся сейчас/)
})

test('процесс уже подключён, а сопоставление сломалось — сохранение останавливается и объясняет', () => {
  const partial = fullProjectMapping()
  delete partial.curator_id

  const plan = planMappingSave({
    selectedProjectSpId: 1102,
    savedProjectSpId: 1102,
    projectStatus: projectStatusWith(partial),
  })

  assert.equal(plan.kind, 'blocked')
  if (plan.kind !== 'blocked') {
    return
  }

  assert.deepEqual(plan.blockers.map(item => item.key), ['curator_id'])
  assert.match(plan.blockers[0]?.reason || '', /уведомлени/i)
})

test('снятие уже сохранённого процесса предупреждает о последствиях', () => {
  const plan = planMappingSave({
    selectedProjectSpId: null,
    savedProjectSpId: 1102,
    projectStatus: projectStatusWith({}, 0),
  })

  assert.equal(plan.kind, 'full')
  assert.match(plan.note, /перестанут получать|отвяз/i)
})

// endregion

// region Автоподбор

test('автоподбор находит поле по точному названию', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => row.key === 'kolichestvo_chasov')
  const found = suggestMappingMatches(rows, [
    field('UF_CRM_1_HOURS', 'Количество часов', 'double'),
    field('UF_CRM_1_OTHER', 'Прочее', 'double'),
  ], {})

  assert.equal(found.length, 1)
  assert.equal(found[0]?.fieldId, 'UF_CRM_1_HOURS')
  assert.equal(found[0]?.source, 'label')
})

test('автоподбор находит поле по коду, когда название не совпало', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => row.key === 'task_name')
  const found = suggestMappingMatches(rows, [
    field('UF_CRM_1_TASK_NAME', 'Наименование работ', 'string'),
  ], {})

  assert.equal(found[0]?.source, 'code')
  assert.equal(found[0]?.fieldId, 'UF_CRM_1_TASK_NAME')
})

test('подбор по единственному подходящему типу помечается как требующий проверки', () => {
  const rows = PROJECT_MAPPING_ROWS.filter(row => row.key === PROJECT_STAGE_FIELD_KEY)
  const found = suggestMappingMatches(rows, [
    field('UF_CRM_1_SOMETHING', 'Этап работ', 'crm_status'),
  ], {})

  assert.equal(found[0]?.source, 'type')
  assert.match(found[0]?.reason || '', /проверьте/)
})

test('одно поле портала не предлагается двум разным ключам', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => ['project_title', 'task_name'].includes(row.key))
  const found = suggestMappingMatches(rows, [
    field('UF_CRM_1_NAME', 'Название задачи', 'string'),
  ], {})

  assert.equal(found.length, 1)
  assert.equal(found[0]?.key, 'task_name')
})

test('по строке и числу автоподбор не угадывает — только по характерным типам', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => ['our_inn', 'client_inn'].includes(row.key))
  const found = suggestMappingMatches(rows, [field('UF_CRM_1_SOMETHING', 'Прочее', 'string')], {})

  assert.equal(
    found.length,
    0,
    'единственное строковое поле нельзя выдавать за ИНН: строковых полей в процессе обычно много'
  )

  const dateRows = TIMESHEET_MAPPING_ROWS.filter(row => row.key === 'data')
  const byDate = suggestMappingMatches(dateRows, [field('UF_CRM_1_WHEN', 'Когда', 'date')], {})

  assert.equal(byDate.length, 1, 'а по единственной дате — можно, с пометкой «проверьте»')
  assert.equal(byDate[0]?.source, 'type')
})

test('уже занятое поле в подбор не попадает', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => row.key === 'kolichestvo_chasov')
  const found = suggestMappingMatches(
    rows,
    [field('UF_CRM_1_HOURS', 'Количество часов', 'double')],
    { ne_uchitivaemie_chasi: 'UF_CRM_1_HOURS' }
  )

  assert.equal(found.length, 0)
})

test('автоподбор не трогает уже заполненные строки', () => {
  const rows = TIMESHEET_MAPPING_ROWS.filter(row => row.key === 'kolichestvo_chasov')
  const found = suggestMappingMatches(
    rows,
    [field('UF_CRM_1_HOURS', 'Количество часов', 'double')],
    { kolichestvo_chasov: 'UF_MY_CHOICE' }
  )

  assert.equal(found.length, 0)
})

test('применение подбора не перезаписывает ручной выбор', () => {
  const next = applySuggestions(
    { kolichestvo_chasov: 'UF_MY_CHOICE' },
    [{
      key: 'kolichestvo_chasov',
      label: 'Количество часов',
      fieldId: 'UF_AUTO',
      fieldTitle: 'Часы',
      fieldType: 'double',
      source: 'label',
      reason: '',
    }]
  )

  assert.equal(next.kolichestvo_chasov, 'UF_MY_CHOICE')
})

test('применяются только отмеченные ключи', () => {
  const suggestions = [
    { key: 'a', label: 'A', fieldId: 'UF_A', fieldTitle: 'A', fieldType: 'string', source: 'label' as const, reason: '' },
    { key: 'b', label: 'B', fieldId: 'UF_B', fieldTitle: 'B', fieldType: 'string', source: 'label' as const, reason: '' },
  ]

  assert.deepEqual(applySuggestions({}, suggestions, ['b']), { b: 'UF_B' })
})

test('итог подбора говорит, что ничего не сохранено, и предупреждает о рискованных догадках', () => {
  const risky = describeSuggestions([{
    key: 'stage',
    label: 'Стадия',
    fieldId: 'UF_S',
    fieldTitle: 'Этап',
    fieldType: 'crm_status',
    source: 'type',
    reason: '',
  }], 1)

  assert.match(risky, /Ничего ещё не сохранено/)
  assert.match(risky, /по типу поля/)

  assert.match(describeSuggestions([], 3), /не нашёл/)
  assert.match(describeSuggestions([], 0), /все поля уже сопоставлены/)
})

// endregion

// region Человеческие тексты ошибок

function validationPayload(overrides: Partial<ProjectSpaValidationPayload>): ProjectSpaValidationPayload {
  return {
    is_configured: true,
    is_valid: false,
    entity_type_id: 1102,
    required_mapping_keys: [...PROJECT_SPA_SERVER_REQUIRED_KEYS],
    missing_mapping_keys: [],
    missing_fields_in_sp: [],
    type_mismatches: [],
    access_error: null,
    write_access_error: null,
    warnings: [],
    linkage_issues: {
      total_items: 0,
      missing_group_link_count: 0,
      duplicate_group_link_count: 0,
      duplicate_group_links: [],
      duplicate_project_item_link_count: 0,
      duplicate_project_item_links: [],
    },
    ...overrides,
  }
}

test('коды недостающих ключей превращаются в названия полей', () => {
  const report = describeProjectSpaValidation(validationPayload({
    missing_mapping_keys: ['stage_id', 'company_id'],
  }))

  assert.equal(report.ok, false)
  assert.deepEqual(report.problems.map(problem => problem.title), [
    'Поле «Стадия проекта» не сопоставлено',
    'Поле «Компания клиента» не сопоставлено',
  ])
  assert.ok(report.problems.every(problem => problem.fix.length > 10))
})

test('несовпадение типов объясняется словами, а не кодами типов', () => {
  const report = describeProjectSpaValidation(validationPayload({
    type_mismatches: [{
      key: 'company_id',
      mapped_field: 'UF_CRM_1_X',
      expected_type: 'crm_binding',
      actual_type: 'date',
    }],
  }))

  assert.match(report.problems[0]?.detail || '', /привязка к элементам CRM/)
  assert.ok(!(report.problems[0]?.detail || '').includes('crm_binding'))
})

test('отказ прав объясняется как нехватка доступа, а не как текст портала', () => {
  const report = describeProjectSpaValidation(validationPayload({
    write_access_error: 'ACCESS_DENIED',
  }))

  assert.match(report.problems[0]?.title || '', /не может изменять/)
  assert.match(report.problems[0]?.fix || '', /право на изменение/)
})

test('нестыковки связности карточек попадают в проблемы с объяснением', () => {
  const report = describeProjectSpaValidation(validationPayload({
    is_valid: true,
    linkage_issues: {
      total_items: 10,
      missing_group_link_count: 2,
      duplicate_group_link_count: 1,
      duplicate_group_links: [],
      duplicate_project_item_link_count: 0,
      duplicate_project_item_links: [],
    },
  }))

  assert.equal(report.ok, false, 'валидная конфигурация с битыми связями не «полностью в порядке»')
  assert.equal(report.problems.length, 2)
  assert.match(report.headline, /нестыковки/)
})

test('пройденная проверка говорит об этом одной фразой', () => {
  const report = describeProjectSpaValidation(validationPayload({ is_valid: true }))

  assert.equal(report.ok, true)
  assert.match(report.headline, /Проверка пройдена/)
})

test('непроверенное и ненастроенное состояния различаются', () => {
  assert.match(describeProjectSpaValidation(null).headline, /ещё не запускалась/)
  assert.match(
    describeProjectSpaValidation(validationPayload({ is_configured: false })).headline,
    /не выбран/
  )
})

test('400 с валидацией отдаёт разбор и говорит, что ничего не сохранено', () => {
  const report = describeMappingSaveError({
    status: 400,
    data: {
      error: 'Конфигурация Project SPA невалидна. Исправьте ошибки и повторите сохранение.',
      validation: validationPayload({ missing_mapping_keys: ['hourly_rate'] }),
    },
  })

  assert.ok(report.validation)
  assert.match(report.text, /НЕ сохранены/)
})

test('лимит запросов объясняет причину и срок, а не код 429', () => {
  const report = describeMappingSaveError({ status: 429 })

  assert.match(report.text, /минуту/)
  assert.ok(!report.text.includes('429'))
})

test('устаревшая вкладка и отсутствие прав получают свои объяснения', () => {
  assert.match(describeMappingSaveError({ status: 409 }).text, /Перезагрузите/)
  assert.match(describeMappingSaveError({ status: 403 }).title, /прав/)
  assert.match(describeMappingSaveError({ status: 502 }).title, /не ответили/)
})

test('неизвестная ошибка показывает текст сервера, а если его нет — совет', () => {
  assert.equal(
    describeMappingSaveError({ status: 400, data: { error: 'Некорректный формат тела запроса.' } }).text,
    'Некорректный формат тела запроса.'
  )
  assert.match(describeMappingSaveError({}).text, /Причина неизвестна/)
})

// endregion

// region Предупреждение по всему приложению

test('пустая конфигурация — критическое предупреждение о неработающем приложении', () => {
  const health = resolveMappingHealth({ sp_entity_type_id: 0, fields_mapping: {} })

  assert.equal(health.level, 'critical')
  assert.match(health.text, /не записываются/)
})

test('неизвестная конфигурация не поднимает ложную тревогу', () => {
  assert.equal(resolveMappingHealth(null).level, 'ok')
})

test('нет обязательного поля — критическое предупреждение с его названием', () => {
  const health = resolveMappingHealth({
    sp_entity_type_id: 1100,
    fields_mapping: { id_zadachi: 'UF_A' },
  })

  assert.equal(health.level, 'critical')
  assert.deepEqual(health.missingLabels, ['Количество часов'])
})

test('проекты не подключены — предупреждение, а не отказ', () => {
  const fields = TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
    acc[row.key] = `UF_${row.key}`
    return acc
  }, {})

  const health = resolveMappingHealth({ sp_entity_type_id: 1100, fields_mapping: fields })

  assert.equal(health.level, 'warning')
  assert.match(health.title, /Проекты не подключены/)
})

test('полная конфигурация обоих процессов не показывает предупреждения', () => {
  const fields = TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
    acc[row.key] = `UF_${row.key}`
    return acc
  }, {})

  const health = resolveMappingHealth({
    sp_entity_type_id: 1100,
    fields_mapping: fields,
    project_sp_entity_type_id: 1102,
    project_fields_mapping: fullProjectMapping(),
  })

  assert.equal(health.level, 'ok')
})

test('неполное сопоставление проектов даёт предупреждение с названиями полей', () => {
  const fields = TIMESHEET_MAPPING_ROWS.reduce<Record<string, string>>((acc, row) => {
    acc[row.key] = `UF_${row.key}`
    return acc
  }, {})
  const projectPartial = fullProjectMapping()
  delete projectPartial.hourly_rate

  const health = resolveMappingHealth({
    sp_entity_type_id: 1100,
    fields_mapping: fields,
    project_sp_entity_type_id: 1102,
    project_fields_mapping: projectPartial,
  })

  assert.equal(health.level, 'warning')
  assert.ok(health.missingLabels.includes('Ставка часа'))
})

// endregion
