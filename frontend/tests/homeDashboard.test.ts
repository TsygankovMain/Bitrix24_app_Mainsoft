import test from 'node:test'
import assert from 'node:assert/strict'

import type { PeriodCheckResult } from '../app/types/period'
import type { ProjectBoardCardRecord } from '../app/types/project-board'
import {
  buildHomeMetrics,
  buildProjectRows,
  countPeriodBlockers,
  countPeriodFindings,
  filterProjectRows,
  formatHours,
  formatMonthTitle,
  formatMonthValue,
  parseMonthValue,
  sortProjectRows,
} from '../app/utils/homeDashboard'

function makeCheck(overrides: Partial<PeriodCheckResult> = {}): PeriodCheckResult {
  return {
    period: { year: 2026, month: 9, title: 'Сентябрь 2026' },
    can_close: true,
    blockers: [],
    warnings: [],
    stats: { hours: 1234.56, entries: 410, projects: 17, employees: 23 },
    ...overrides,
  }
}

function makeCard(overrides: Partial<ProjectBoardCardRecord> = {}): ProjectBoardCardRecord {
  return {
    project_id: '101',
    project_name: 'Портал ОРТК',
    company_name: 'ОРТК',
    curator_name: 'Егор',
    stage: 'В работе',
    is_archived: false,
    last_writeoff_days: 3,
    actual_hours: 42,
    hourly_rate: 2500,
    project_hours_budget: 120,
    our_legal_entity_name: 'Мейнсофт',
    ...overrides,
  } as ProjectBoardCardRecord
}

// --- Месяц ---

test('parseMonthValue: разбирает значение поля «месяц»', () => {
  assert.deepEqual(parseMonthValue('2026-09'), { year: 2026, month: 9 })
  assert.deepEqual(parseMonthValue(' 2026-01 '), { year: 2026, month: 1 })
})

test('parseMonthValue: пустое и кривое значение — null, а не падение', () => {
  assert.equal(parseMonthValue(''), null)
  assert.equal(parseMonthValue(null), null)
  assert.equal(parseMonthValue('2026-13'), null)
  assert.equal(parseMonthValue('сентябрь'), null)
})

test('formatMonthValue: дата превращается в значение поля с ведущим нулём', () => {
  assert.equal(formatMonthValue(new Date(2026, 0, 15)), '2026-01')
  assert.equal(formatMonthValue(new Date(2026, 11, 1)), '2026-12')
})

test('formatMonthTitle: подпись по-русски, для пустого значения — понятная заглушка', () => {
  assert.equal(formatMonthTitle('2026-09'), 'сентябрь 2026')
  assert.equal(formatMonthTitle(''), 'Месяц не выбран')
})

// --- Показатели ---

test('formatHours: округляет до десятых', () => {
  assert.equal(formatHours(10.04), '10')
  assert.equal(formatHours(10.06), '10,1')
  assert.equal(formatHours(null), '0')
})

test('buildHomeMetrics: четыре показателя выбранного месяца', () => {
  const metrics = buildHomeMetrics(makeCheck())

  assert.deepEqual(metrics.map(metric => metric.id), ['hours', 'entries', 'employees', 'findings'])
  assert.equal(metrics[0].value, '1 234,6'.replace(' ', ' '))
  assert.equal(metrics[1].value, '410')
  assert.equal(metrics[2].value, '23')
  assert.equal(metrics[3].value, '0')
})

test('buildHomeMetrics: без ответа проверки — прочерки, а не нули', () => {
  const metrics = buildHomeMetrics(null)

  assert.deepEqual(metrics.map(metric => metric.value), ['—', '—', '—', '—'])
  assert.ok(metrics.every(metric => metric.tone === 'neutral'))
})

test('buildHomeMetrics: блокеры красят находки в тревожный тон и объясняют, сколько мешает закрытию', () => {
  const metrics = buildHomeMetrics(makeCheck({
    can_close: false,
    blockers: [{ code: 'no_project', title: 'Без проекта', why: '', count: 12 }],
    warnings: [{ code: 'duplicates', title: 'Дубли', why: '', count: 4 }],
  }))

  assert.equal(metrics[3].value, '2')
  assert.equal(metrics[3].tone, 'danger')
  assert.match(metrics[3].hint, /мешают закрыть месяц: 1/)
})

test('buildHomeMetrics: одни предупреждения — тон предупреждающий, закрытию ничего не мешает', () => {
  const metrics = buildHomeMetrics(makeCheck({
    warnings: [{ code: 'zero_hours', title: 'Нулевые часы', why: '', count: 3 }],
  }))

  assert.equal(metrics[3].tone, 'warning')
  assert.match(metrics[3].hint, /ничего не мешает/)
})

test('countPeriodFindings и countPeriodBlockers считают находки, а не записи за ними', () => {
  const check = makeCheck({
    blockers: [{ code: 'a', title: 'a', why: '', count: 300 }],
    warnings: [
      { code: 'b', title: 'b', why: '', count: 10 },
      { code: 'c', title: 'c', why: '', count: 2 },
    ],
  })

  assert.equal(countPeriodBlockers(check), 1)
  assert.equal(countPeriodFindings(check), 3)
  assert.equal(countPeriodFindings(null), 0)
})

// --- Таблица проектов ---

test('buildProjectRows: архивные проекты в таблицу не попадают', () => {
  const rows = buildProjectRows([
    makeCard(),
    makeCard({ project_id: '102', is_archived: true }),
  ])

  assert.equal(rows.length, 1)
  assert.equal(rows[0].id, '101')
})

test('buildProjectRows: пустые поля подменяются понятной подписью, а не пустотой', () => {
  const rows = buildProjectRows([
    makeCard({ company_name: null, curator_name: '  ', our_legal_entity_name: null, project_hours_budget: null }),
  ])

  assert.equal(rows[0].companyName, 'Компания не указана')
  assert.equal(rows[0].curatorName, 'Куратор не указан')
  assert.equal(rows[0].legalEntityName, 'Не указано')
  assert.equal(rows[0].hoursBudget, 'поддержка')
})

test('filterProjectRows: быстрый фильтр ищет по названию, компании, куратору, стадии и ID', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', project_name: 'Портал ОРТК', company_name: 'ОРТК', curator_name: 'Егор' }),
    makeCard({ project_id: '2', project_name: 'ЛК агента', company_name: 'ЭлВЛифт', curator_name: 'Мария', stage: 'В просчете' }),
  ])

  assert.deepEqual(filterProjectRows(rows, 'ортк').map(row => row.id), ['1'])
  assert.deepEqual(filterProjectRows(rows, 'мария').map(row => row.id), ['2'])
  assert.deepEqual(filterProjectRows(rows, 'просчете').map(row => row.id), ['2'])
  assert.deepEqual(filterProjectRows(rows, '2').map(row => row.id), ['2'])
})

test('filterProjectRows: пустой запрос ничего не отсеивает', () => {
  const rows = buildProjectRows([makeCard(), makeCard({ project_id: '2' })])

  assert.equal(filterProjectRows(rows, '').length, 2)
  assert.equal(filterProjectRows(rows, '   ').length, 2)
})

test('sortProjectRows: по умолчанию сверху те, по кому дольше всех не списывали', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', last_writeoff_days: 2 }),
    makeCard({ project_id: '2', last_writeoff_days: 91 }),
    makeCard({ project_id: '3', last_writeoff_days: 31 }),
  ])

  assert.deepEqual(sortProjectRows(rows).map(row => row.id), ['2', '3', '1'])
})

test('sortProjectRows: имена сортируются по-русски и исходный массив не портится', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', project_name: 'Ёлка' }),
    makeCard({ project_id: '2', project_name: 'Ангар' }),
  ])
  const sorted = sortProjectRows(rows, 'name', 'asc')

  assert.deepEqual(sorted.map(row => row.name), ['Ангар', 'Ёлка'])
  assert.deepEqual(rows.map(row => row.id), ['1', '2'])
})
