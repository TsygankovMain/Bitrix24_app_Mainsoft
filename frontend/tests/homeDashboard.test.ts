import test from 'node:test'
import assert from 'node:assert/strict'

import type { PeriodCheckResult, PeriodRow } from '../app/types/period'
import type { ProjectBoardCardRecord, ProjectBoardSummary } from '../app/types/project-board'
import {
  applyProjectQuickFilter,
  buildHomeMetrics,
  buildMonthClosingMetric,
  buildProjectPanel,
  buildProjectRows,
  buildProjectUtilization,
  countPeriodBlockers,
  countPeriodFindings,
  countProjectQuickFilters,
  filterProjectRows,
  findPeriodRow,
  formatHours,
  formatLastWriteoff,
  formatMoney,
  formatMonthTitle,
  formatMonthValue,
  initialsOf,
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

function makeSummary(overrides: Partial<ProjectBoardSummary> = {}): ProjectBoardSummary {
  return {
    total_count: 18,
    active_count: 14,
    archived_count: 4,
    support_count: 3,
    inactive_30_count: 2,
    inactive_90_count: 1,
    ...overrides,
  }
}

function makePeriodRow(overrides: Partial<PeriodRow> = {}): PeriodRow {
  return {
    year: 2026,
    month: 8,
    title: 'Август 2026',
    hours: 800,
    entries: 400,
    closed: true,
    closed_at: '2026-09-02T10:15:00+03:00',
    late_arrivals: 2,
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

test('buildHomeMetrics: четыре показателя выбранного месяца — часы, находки, простой, закрытие', () => {
  const metrics = buildHomeMetrics({
    check: makeCheck(),
    portfolio: makeSummary(),
    period: makePeriodRow({ month: 9 }),
    periodsLoaded: true,
  })

  assert.deepEqual(metrics.map(metric => metric.id), ['hours', 'findings', 'inactive', 'closing'])
  assert.equal(metrics[0].value, formatHours(1234.56))
  assert.match(metrics[0].hint, /410 записей/)
  assert.match(metrics[0].hint, /23 сотрудник/)
  assert.equal(metrics[1].value, '0')
  assert.equal(metrics[2].value, '2')
  assert.match(metrics[2].hint, /90\+ дней: 1/)
  assert.equal(metrics[3].value, 'Месяц закрыт')
  assert.equal(metrics[3].asBadge, true)
})

test('buildHomeMetrics: без ответов ручек — прочерки, а не нули', () => {
  const metrics = buildHomeMetrics(null)

  assert.deepEqual(metrics.map(metric => metric.value), ['—', '—', '—', '—'])
  assert.ok(metrics.every(metric => metric.tone === 'neutral'))
})

test('buildHomeMetrics: старый вызов с одним результатом проверки продолжает работать', () => {
  const metrics = buildHomeMetrics(makeCheck())

  assert.equal(metrics[0].value, formatHours(1234.56))
  // Портфель не передан — показатель простоя честно молчит, а не показывает ноль.
  assert.equal(metrics[2].value, '—')
})

test('buildHomeMetrics: блокеры красят находки в тревожный тон и объясняют, сколько мешает закрытию', () => {
  const metrics = buildHomeMetrics({
    check: makeCheck({
      can_close: false,
      blockers: [{ code: 'no_project', title: 'Без проекта', why: '', count: 12 }],
      warnings: [{ code: 'duplicates', title: 'Дубли', why: '', count: 4 }],
    }),
  })

  assert.equal(metrics[1].value, '2')
  assert.equal(metrics[1].tone, 'danger')
  assert.match(metrics[1].hint, /мешают закрыть месяц: 1/)
})

test('buildHomeMetrics: одни предупреждения — тон предупреждающий, закрытию ничего не мешает', () => {
  const metrics = buildHomeMetrics({
    check: makeCheck({
      warnings: [{ code: 'zero_hours', title: 'Нулевые часы', why: '', count: 3 }],
    }),
  })

  assert.equal(metrics[1].tone, 'warning')
  assert.match(metrics[1].hint, /ничего не мешает/)
})

test('buildHomeMetrics: простой без проектов старше 90 дней не красится в красное', () => {
  const metrics = buildHomeMetrics({
    check: makeCheck(),
    portfolio: makeSummary({ inactive_30_count: 3, inactive_90_count: 0 }),
  })

  assert.equal(metrics[2].value, '3')
  assert.equal(metrics[2].tone, 'warning')
  assert.match(metrics[2].hint, /старше 90 дней нет/)
})

// --- Статус закрытия месяца ---

test('findPeriodRow: из журнала выбирается строка ровно за выбранный месяц', () => {
  const rows = [makePeriodRow({ month: 7 }), makePeriodRow({ month: 8 }), makePeriodRow({ year: 2025, month: 8 })]

  assert.equal(findPeriodRow(rows, { year: 2026, month: 8 })?.title, 'Август 2026')
  assert.equal(findPeriodRow(rows, { year: 2026, month: 12 }), null)
  assert.equal(findPeriodRow(rows, null), null)
  assert.equal(findPeriodRow(null, { year: 2026, month: 8 }), null)
})

test('buildMonthClosingMetric: журнал ещё не отвечал — это не «месяц открыт»', () => {
  const metric = buildMonthClosingMetric(null, false)

  assert.equal(metric.value, '—')
  assert.match(metric.hint, /ещё не ответил/)
})

test('buildMonthClosingMetric: закрытый месяц показывает дату и опоздавшие часы', () => {
  const metric = buildMonthClosingMetric(makePeriodRow(), true)

  assert.equal(metric.value, 'Месяц закрыт')
  assert.equal(metric.tone, 'success')
  assert.match(metric.hint, /02\.09/)
  assert.match(metric.hint, /после закрытия пришло 2 ч/)
})

test('buildMonthClosingMetric: закрытый месяц без опоздавших записей говорит об этом прямо', () => {
  const metric = buildMonthClosingMetric(makePeriodRow({ late_arrivals: 0 }), true)

  assert.match(metric.hint, /записей не приходило/)
})

test('buildMonthClosingMetric: незакрытый месяц с блокерами — тревожный тон', () => {
  const metric = buildMonthClosingMetric(null, true, makeCheck({
    can_close: false,
    blockers: [{ code: 'no_project', title: 'Без проекта', why: '', count: 12 }],
  }))

  assert.equal(metric.value, 'Месяц открыт')
  assert.equal(metric.tone, 'danger')
  assert.match(metric.hint, /мешают находки: 1/)
})

test('buildMonthClosingMetric: переоткрытый месяц показывает причину', () => {
  const metric = buildMonthClosingMetric(
    makePeriodRow({ closed: false, reopened_at: '2026-09-05T09:00:00+03:00', reopen_reason: 'Забыли часы' }),
    true
  )

  assert.equal(metric.value, 'Переоткрыт')
  assert.equal(metric.tone, 'warning')
  assert.match(metric.hint, /Забыли часы/)
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

// --- Быстрые фильтры таблицы проектов ---

test('applyProjectQuickFilter: «Активные» ничего не отсеивает — архив в таблицу и так не попадает', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1' }),
    makeCard({ project_id: '2', is_support: true }),
  ])

  assert.equal(applyProjectQuickFilter(rows, 'active').length, 2)
})

test('applyProjectQuickFilter: «Поддержка» ловит и признак is_support, и тип проекта', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1' }),
    makeCard({ project_id: '2', is_support: true }),
    makeCard({ project_id: '3', project_type: 'support' }),
  ])

  assert.deepEqual(applyProjectQuickFilter(rows, 'support').map(row => row.id), ['2', '3'])
})

test('applyProjectQuickFilter: «Под риском» — и по дням простоя, и по автостадии', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', last_writeoff_days: 3 }),
    makeCard({ project_id: '2', last_writeoff_days: 34 }),
    // Автостадия отстаёт на сутки, но сама по себе тоже признак риска.
    makeCard({ project_id: '3', last_writeoff_days: 0, stage: 'Нет списаний 3 месяца' }),
  ])

  assert.deepEqual(
    applyProjectQuickFilter(rows, 'risk').map(row => row.id).sort(),
    ['2', '3']
  )
})

test('applyProjectQuickFilter: «Мои» сравнивает ID куратора, а не имя', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', curator_user_id: '11', curator_name: 'Егор' }),
    makeCard({ project_id: '2', curator_user_id: '42', curator_name: 'Егор' }),
  ])

  assert.deepEqual(applyProjectQuickFilter(rows, 'mine', { currentUserId: 11 }).map(row => row.id), ['1'])
})

test('applyProjectQuickFilter: без известного пользователя «Мои» не выдаёт чужие проекты за свои', () => {
  const rows = buildProjectRows([makeCard({ project_id: '1', curator_user_id: '11' })])

  assert.equal(applyProjectQuickFilter(rows, 'mine', { currentUserId: 0 }).length, 0)
  assert.equal(applyProjectQuickFilter(rows, 'mine').length, 0)
})

test('countProjectQuickFilters: счётчики считаются от полного списка', () => {
  const rows = buildProjectRows([
    makeCard({ project_id: '1', curator_user_id: '11', last_writeoff_days: 1 }),
    makeCard({ project_id: '2', is_support: true, last_writeoff_days: 40 }),
    makeCard({ project_id: '3', last_writeoff_days: 95 }),
  ])

  assert.deepEqual(countProjectQuickFilters(rows, { currentUserId: '11' }), {
    active: 3,
    support: 1,
    risk: 2,
    mine: 1,
  })
})

// --- Ячейки и панель проекта ---

test('formatLastWriteoff: свежие дни читаются словами', () => {
  assert.equal(formatLastWriteoff(0), 'сегодня')
  assert.equal(formatLastWriteoff(1), 'вчера')
  assert.equal(formatLastWriteoff(34), '34 дн.')
  assert.equal(formatLastWriteoff(null), 'сегодня')
})

test('buildProjectUtilization: без бюджета полосы нет, показываем часы', () => {
  const [row] = buildProjectRows([makeCard({ budget_utilization_percent: null, actual_hours: 46 })])
  const utilization = buildProjectUtilization(row)

  assert.equal(utilization.isEmpty, true)
  assert.equal(utilization.label, '46 ч')
  assert.equal(utilization.barPercent, 0)
})

test('buildProjectUtilization: перерасход упирается в 100% ширины, но красится отдельно', () => {
  const [row] = buildProjectRows([makeCard({ budget_utilization_percent: 117 })])
  const utilization = buildProjectUtilization(row)

  assert.equal(utilization.barPercent, 100)
  assert.equal(utilization.label, '117%')
  assert.equal(utilization.tone, 'danger')
})

test('buildProjectUtilization: приближение к бюджету предупреждает заранее', () => {
  const [row] = buildProjectRows([makeCard({ budget_utilization_percent: 82 })])

  assert.equal(buildProjectUtilization(row).tone, 'warning')
  assert.equal(buildProjectUtilization(row).barPercent, 82)
})

test('initialsOf: два слова превращаются в две буквы, пустое имя — в прочерк', () => {
  assert.equal(initialsOf('Анна Воронцова'), 'АВ')
  assert.equal(initialsOf('  Егор  '), 'Е')
  assert.equal(initialsOf(''), '—')
  assert.equal(initialsOf(null), '—')
})

test('formatMoney: рубли без копеек и с разделителями разрядов', () => {
  assert.equal(formatMoney(1092000), (1092000).toLocaleString('ru-RU') + ' ₽')
  assert.equal(formatMoney(null), '0 ₽')
})

test('buildProjectPanel: четыре показателя выбранного проекта из той же карточки', () => {
  const [row] = buildProjectRows([makeCard({
    project_name: 'Внедрение CRM',
    company_name: 'ООО «Северный ветер»',
    curator_name: 'Анна Воронцова',
    planned_hours: 400,
    actual_hours: 312,
    hourly_rate: 3500,
    actual_cost_amount: 1092000,
    our_legal_entity_name: 'ООО «Вектор Софт»',
  })])
  const panel = buildProjectPanel(row)

  assert.ok(panel)
  assert.equal(panel.name, 'Внедрение CRM')
  assert.equal(panel.subtitle, 'ООО «Северный ветер» · куратор Анна Воронцова')
  assert.deepEqual(panel.stats.map(stat => stat.id), ['budget', 'rate', 'amount', 'legal-entity'])
  assert.equal(panel.stats[0].value, '400 / 312 ч')
  assert.equal(panel.stats[3].value, 'ООО «Вектор Софт»')
})

test('buildProjectPanel: без плана часов бюджет не выдумывается', () => {
  const [row] = buildProjectRows([makeCard({ planned_hours: null, actual_hours: 46, hourly_rate: 0 })])
  const panel = buildProjectPanel(row)

  assert.equal(panel?.stats[0].value, '46 ч (без плана)')
  assert.equal(panel?.stats[1].value, 'не задана')
})

test('buildProjectPanel: без строки — нечего показывать', () => {
  assert.equal(buildProjectPanel(null), null)
})
