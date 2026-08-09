import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  assignMappedField,
  resolveInnFieldCode,
  hasMeaningfulValue,
  toNumberOrNull,
  makeNewEntryDraft,
  buildBaseEntryFields,
  resolveEntryInn,
  applyProjectContextFields,
  validateEntryBeforeSave
} from '../app/utils/timesheetEntry'

const CONFIG = {
  FIELDS: {
    HOURS: 'ufCrm87_HOURS',
    IS_CONSIDERED: 'ufCrm87_IS_CONSIDERED',
    DESCRIPTION: 'ufCrm87_DESCRIPTION',
    EMPLOYEE: 'ufCrm87_EMPLOYEE',
    DATE: 'ufCrm87_DATE',
    TASK_ID: 'ufCrm87_TASK_ID',
    TASK_NAME: 'ufCrm87_TASK_NAME',
    TASK_HIERARCHY: 'ufCrm87_HIER_IDS',
    TITLE_HIERARCHY: 'ufCrm87_HIER_TITLES',
    PROJECT_ID: 'ufCrm87_PROJECT_ID',
    PROJECT_TITLE: 'ufCrm87_PROJECT',
    PROJECT_ITEM_ID: 'ufCrm87_PROJECT_ITEM_ID',
    HOURLY_RATE_SNAPSHOT: 'ufCrm87_RATE',
    OUR_INN: 'ufCrm87_OUR_INN',
    CLIENT_INN: 'ufCrm87_CLIENT_INN'
  }
}

const HIERARCHY = {
  idPath: ['100', '200', '300'],
  titlePath: ['Проект', 'Эпик', 'Задача'],
  projectId: '55',
  projectTitle: 'Внедрение',
  ourInn: '7700000001',
  clientInn: '7700000002'
}

// --- мелкие помощники -------------------------------------------------------

test('assignMappedField не пишет незамапленное поле и undefined', () => {
  const target: Record<string, unknown> = {}
  assignMappedField(target, undefined, 'значение')
  assignMappedField(target, '', 'значение')
  assignMappedField(target, 'code', undefined)
  assert.deepEqual(target, {})
})

test('assignMappedField пишет пустую строку — ею затирают поле', () => {
  const target: Record<string, unknown> = {}
  assignMappedField(target, 'code', '')
  assert.deepEqual(target, { code: '' })
})

test('resolveInnFieldCode: SPA_FIELDS приоритетнее FIELDS', () => {
  const config = { FIELDS: { OUR_INN: 'from_fields' }, SPA_FIELDS: { OUR_INN: 'from_spa' } }
  assert.equal(resolveInnFieldCode(config, 'OUR_INN'), 'from_spa')
  assert.equal(resolveInnFieldCode({ FIELDS: { OUR_INN: 'from_fields' } }, 'OUR_INN'), 'from_fields')
  assert.equal(resolveInnFieldCode(null, 'OUR_INN'), '')
})

test('hasMeaningfulValue: пробельная строка не считается заполненной', () => {
  assert.equal(hasMeaningfulValue('   '), false)
  assert.equal(hasMeaningfulValue(''), false)
  assert.equal(hasMeaningfulValue(null), false)
  assert.equal(hasMeaningfulValue(undefined), false)
  assert.equal(hasMeaningfulValue(0), true, 'ноль — заполненное значение')
  assert.equal(hasMeaningfulValue('7'), true)
})

test('toNumberOrNull отсеивает нечисловое', () => {
  assert.equal(toNumberOrNull('2500'), 2500)
  assert.equal(toNumberOrNull(0), 0)
  assert.equal(toNumberOrNull('нет'), null)
  assert.equal(toNumberOrNull(null), 0, 'Number(null) === 0 — как в оригинале')
  assert.equal(toNumberOrNull(undefined), null)
})

// --- черновик и базовые поля ------------------------------------------------

test('makeNewEntryDraft: час по умолчанию, учитываем, дата — сегодня', () => {
  const draft = makeNewEntryDraft({ taskId: '300', employeeId: '10', today: new Date('2026-08-09T15:00:00Z') })
  assert.equal(draft.id, null)
  assert.equal(draft.taskId, '300')
  assert.equal(draft.employeeId, '10')
  assert.equal(draft.date, '2026-08-09')
  assert.equal(draft.hours, 1)
  assert.equal(draft.isConsidered, true)
})

test('buildBaseEntryFields раскладывает значения по замапленным полям', () => {
  const fields = buildBaseEntryFields(CONFIG, {
    hours: 2.5,
    isConsidered: true,
    description: 'Правки по макету',
    employeeId: '10',
    date: '2026-08-09'
  }, '300')

  assert.equal(fields.ufCrm87_HOURS, 2.5)
  assert.equal(fields.ufCrm87_IS_CONSIDERED, 'Y')
  assert.equal(fields.ufCrm87_DESCRIPTION, 'Правки по макету')
  assert.equal(fields.ufCrm87_EMPLOYEE, '10')
  assert.equal(fields.ufCrm87_DATE, '2026-08-09')
  assert.equal(fields.ufCrm87_TASK_ID, '300')
  assert.equal(fields.TITLE, 'Правки по макету')
})

test('buildBaseEntryFields: «не учитываем» пишется как N', () => {
  const fields = buildBaseEntryFields(CONFIG, {
    hours: 1, isConsidered: false, description: '', employeeId: '10', date: '2026-08-09'
  }, '300')
  assert.equal(fields.ufCrm87_IS_CONSIDERED, 'N')
})

test('buildBaseEntryFields обрезает TITLE до 255 символов', () => {
  const long = 'я'.repeat(400)
  const fields = buildBaseEntryFields(CONFIG, {
    hours: 1, isConsidered: true, description: long, employeeId: '10', date: '2026-08-09'
  }, '300')
  assert.equal(String(fields.TITLE).length, 255)
  assert.equal(fields.ufCrm87_DESCRIPTION, long, 'описание не обрезается')
})

// --- ИНН --------------------------------------------------------------------

test('resolveEntryInn: карточка проекта приоритетнее полей задачи', () => {
  const inn = resolveEntryInn({
    projectCard: { our_legal_entity_inn: '9900000001', company_inn: '9900000002' },
    hierarchy: HIERARCHY
  })
  assert.equal(inn.ourInn, '9900000001')
  assert.equal(inn.clientInn, '9900000002')
})

test('resolveEntryInn: без карточки берём ИНН из задачи', () => {
  const inn = resolveEntryInn({ projectCard: null, hierarchy: HIERARCHY })
  assert.equal(inn.ourInn, '7700000001')
  assert.equal(inn.clientInn, '7700000002')
})

test('resolveEntryInn: пустые значения в карточке не затирают ИНН задачи', () => {
  const inn = resolveEntryInn({
    projectCard: { our_legal_entity_inn: '   ', company_inn: null },
    hierarchy: HIERARCHY
  })
  assert.equal(inn.ourInn, '7700000001')
  assert.equal(inn.clientInn, '7700000002')
})

// --- проектный контекст -----------------------------------------------------

test('applyProjectContextFields пишет иерархию, проект, ИНН, ставку и элемент SPA', () => {
  const fields: Record<string, unknown> = {}
  applyProjectContextFields(fields, CONFIG, {
    hierarchy: HIERARCHY,
    projectCard: {
      project_item_id: '777',
      our_legal_entity_id: '12',
      our_legal_entity_inn: '9900000001',
      company_inn: '9900000002',
      hourly_rate: '2500'
    },
    resolvedTaskName: 'Задача'
  })

  assert.deepEqual(fields.ufCrm87_HIER_IDS, ['100', '200', '300'], 'иерархия обязана попасть в поля')
  assert.deepEqual(fields.ufCrm87_HIER_TITLES, ['Проект', 'Эпик', 'Задача'])
  assert.equal(fields.ufCrm87_PROJECT_ID, '55')
  assert.equal(fields.ufCrm87_PROJECT, 'Внедрение')
  assert.equal(fields.ufCrm87_TASK_NAME, 'Задача')
  assert.equal(fields.ufCrm87_OUR_INN, '9900000001')
  assert.equal(fields.ufCrm87_CLIENT_INN, '9900000002')
  assert.equal(fields.ufCrm87_PROJECT_ITEM_ID, '777')
  assert.equal(fields.ufCrm87_RATE, 2500, 'снимок ставки часа')
  assert.equal(fields.mycompanyId, 12, 'числовой id юрлица приводится к числу')
})

test('applyProjectContextFields: нечисловой id юрлица остаётся строкой', () => {
  const fields: Record<string, unknown> = {}
  applyProjectContextFields(fields, CONFIG, {
    hierarchy: HIERARCHY,
    projectCard: { our_legal_entity_id: 'CO-12' }
  })
  assert.equal(fields.mycompanyId, 'CO-12')
})

test('applyProjectContextFields: нулевая ставка не пишется снимком', () => {
  const fields: Record<string, unknown> = {}
  applyProjectContextFields(fields, CONFIG, {
    hierarchy: HIERARCHY,
    projectCard: { hourly_rate: 0 }
  })
  assert.equal(fields.ufCrm87_RATE, undefined, 'ставка 0 — не снимок, а отсутствие ставки')
})

test('applyProjectContextFields: без проектной группы проект и ставка не пишутся', () => {
  const fields: Record<string, unknown> = {}
  applyProjectContextFields(fields, CONFIG, {
    hierarchy: { ...HIERARCHY, projectId: null },
    projectCard: { project_item_id: '777', hourly_rate: '2500', our_legal_entity_id: '12' }
  })
  assert.equal(fields.ufCrm87_PROJECT_ID, undefined)
  assert.equal(fields.ufCrm87_PROJECT_ITEM_ID, undefined)
  assert.equal(fields.ufCrm87_RATE, undefined)
  assert.equal(fields.mycompanyId, undefined)
  assert.deepEqual(fields.ufCrm87_HIER_IDS, ['100', '200', '300'], 'иерархия пишется и без проекта')
})

test('applyProjectContextFields: без иерархии пишется только название задачи', () => {
  const fields: Record<string, unknown> = {}
  applyProjectContextFields(fields, CONFIG, { hierarchy: null, resolvedTaskName: 'Одинокая задача' })
  assert.deepEqual(fields, { ufCrm87_TASK_NAME: 'Одинокая задача' })
})

// --- валидация --------------------------------------------------------------

test('validateEntryBeforeSave: без проектной группы сохранение блокируется', () => {
  const result = validateEntryBeforeSave(CONFIG, {}, { ...HIERARCHY, projectId: null })
  assert.match(String(result.error), /не привязана к проектной группе/)
})

test('validateEntryBeforeSave: отсутствие project_item_id НЕ блокирует, а предупреждает', () => {
  const result = validateEntryBeforeSave(CONFIG, {}, HIERARCHY)
  assert.equal(result.error, null, 'штатное списание часов должно работать без связки с Project SPA')
  assert.match(String(result.warning), /project_item_id не найден/)
  assert.match(String(result.warning), /Внедрение/, 'в предупреждении виден проект')
})

test('validateEntryBeforeSave: с заполненным project_item_id предупреждения нет', () => {
  const result = validateEntryBeforeSave(CONFIG, { ufCrm87_PROJECT_ITEM_ID: '777' }, HIERARCHY)
  assert.equal(result.error, null)
  assert.equal(result.warning, null)
})

test('validateEntryBeforeSave: не задано поле элемента проекта — блокируем', () => {
  const config = { FIELDS: { ...CONFIG.FIELDS, PROJECT_ITEM_ID: '' } }
  const result = validateEntryBeforeSave(config, {}, HIERARCHY)
  assert.match(String(result.error), /ID элемента проекта SPA/)
})

test('validateEntryBeforeSave: требование снимка ставки проверяет значение', () => {
  const ok = validateEntryBeforeSave(
    CONFIG, { ufCrm87_PROJECT_ITEM_ID: '777', ufCrm87_RATE: 2500 }, HIERARCHY, { requireRateSnapshot: true }
  )
  assert.equal(ok.error, null)

  const zero = validateEntryBeforeSave(
    CONFIG, { ufCrm87_PROJECT_ITEM_ID: '777', ufCrm87_RATE: 0 }, HIERARCHY, { requireRateSnapshot: true }
  )
  assert.match(String(zero.error), /ставку часа/)
})

test('validateEntryBeforeSave: без конфигурации сохранять нельзя', () => {
  const result = validateEntryBeforeSave(null, {}, HIERARCHY)
  assert.match(String(result.error), /конфигурацию приложения/)
})
