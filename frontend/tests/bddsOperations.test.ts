/**
 * Операции поступлений и списаний: разбор ответа, итоги, форма, тексты.
 *
 * Проверяется не форматирование, а три места, где интерфейс денег легко
 * соврал бы и никто бы этого не заметил:
 *
 *  1. «сервер не считал итог» против «итог равен нулю»;
 *  2. «смарт-процесс не настроен» против «операций нет»;
 *  3. «остаток бюджета не изменился» против «остаток посчитан неверно».
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BDDS_OPERATIONS_NOT_CONFIGURED_TEXT,
  BDDS_OPERATIONS_PAGE_SIZE,
  BDDS_OPERATION_AMOUNT_LIMIT,
  BDDS_OPERATION_MANUAL_SOURCE,
  BDDS_OPERATION_NO_RIGHTS_TEXT,
  buildBddsOperationsQuery,
  countActiveBddsOperationFilters,
  DEFAULT_BDDS_OPERATION_FILTERS,
  defaultBddsOperationForm,
  describeBddsBudgetImpact,
  describeBddsOperationDuplicate,
  describeBddsOperationFormBlock,
  describeBddsOperationPeriodError,
  describeBddsOperationTotals,
  describeBddsOperationsEmpty,
  firstDayOfMonth,
  formatBddsOperationAmount,
  formatBddsOperationAuthor,
  formatBddsOperationDate,
  formatBddsOperationDelta,
  formatBddsOperationSignedAmount,
  formatBddsOperationSource,
  isIsoDate,
  normalizeBddsOperation,
  parseBddsOperationAmount,
  parseBddsOperationsPage,
  readBddsOperationType,
  sumBddsOperations,
  toIsoDate,
  validateBddsOperationForm,
} from '../app/utils/bddsOperations'
import type { BddsOperationsResponse, BddsProjectRecord } from '../app/types/bdds'

// ---------------------------------------------------------------------------
// Разбор типа операции
// ---------------------------------------------------------------------------

test('тип операции читается во всех написаниях портала', () => {
  for (const value of ['income', 'IN', ' Поступление ', 'доход', 'incomes']) {
    assert.equal(readBddsOperationType(value), 'income', `не разобрано: ${value}`)
  }
  for (const value of ['expense', 'out', 'Расход', 'списание', 'выбытие', 'expense_other']) {
    assert.equal(readBddsOperationType(value), 'expense', `не разобрано: ${value}`)
  }
})

test('непонятный тип остаётся нераспознанным, а не становится списанием', () => {
  // Отнести чужое значение к списаниям «по умолчанию» — это молча
  // исправить данные клиента: сумма уехала бы не в ту сторону итога.
  assert.equal(readBddsOperationType('перевод'), null)
  assert.equal(readBddsOperationType(''), null)
  assert.equal(readBddsOperationType(null), null)
})

// ---------------------------------------------------------------------------
// Разбор строки и страницы
// ---------------------------------------------------------------------------

test('операция разбирается с положительной суммой и знаком по типу', () => {
  const row = normalizeBddsOperation({
    id: '9',
    title: 'Аванс по этапу 2',
    operation_type: 'расход',
    amount: -12000.5,
    operation_date: '2026-08-20',
    comment: 'договор 14/26',
    responsible_user_id: '11',
    source: 'manual',
    project_item_id: '500',
  })

  assert.equal(row.type, 'expense')
  assert.equal(row.typeLabel, 'Списание')
  assert.equal(row.amount, 12000.5)
  assert.equal(row.signedAmount, -12000.5)
  assert.equal(row.purpose, 'Аванс по этапу 2')
  assert.equal(row.comment, 'договор 14/26')
  assert.equal(row.authorId, '11')
})

test('операция без полей не роняет разбор и не выдумывает сумму', () => {
  const row = normalizeBddsOperation({})

  assert.equal(row.id, '')
  assert.equal(row.type, null)
  assert.equal(row.typeLabel, 'Тип не распознан')
  assert.equal(row.amount, 0)
  assert.equal(row.signedAmount, 0)
  assert.equal(row.currency, 'RUB')
  assert.equal(row.date, null)
})

test('страница операций разбирается вместе с постраничностью и итогами', () => {
  const page = parseBddsOperationsPage({
    operations: [
      { id: '5', operation_type: 'expense', amount: 1000, operation_date: '2026-09-05' },
      { id: '3', operation_type: 'income', amount: 5000, operation_date: '2026-08-01' },
    ],
    count: 2,
    entity_type_id: 1040,
    offset: 2,
    limit: 2,
    total: 5,
    has_more: true,
    truncated: false,
    totals: { income: 15000, expense: 6000, net: 9000, count: 5 },
  })

  assert.equal(page.rows.length, 2)
  assert.equal(page.offset, 2)
  assert.equal(page.total, 5)
  assert.equal(page.hasMore, true)
  assert.equal(page.entityTypeId, 1040)
  assert.deepEqual(page.totals, { income: 15000, expense: 6000, net: 9000, count: 5 })
})

test('отсутствие total и totals означает «сервер не считал», а не нуль', () => {
  // Самая дорогая ошибка этого экрана: выдать длину окна страницы за
  // количество всех операций проекта, а сумму видимых строк — за итог.
  const page = parseBddsOperationsPage({
    operations: [{ id: '1', operation_type: 'income', amount: 100 }],
    count: 1,
  } as BddsOperationsResponse)

  assert.equal(page.total, null)
  assert.equal(page.totals, null)
  assert.equal(page.hasMore, false)
  assert.equal(page.limit, BDDS_OPERATIONS_PAGE_SIZE)
})

test('страница выдерживает пустой и мусорный ответ', () => {
  const empty = parseBddsOperationsPage(null)
  assert.deepEqual(empty.rows, [])
  assert.equal(empty.total, null)

  const broken = parseBddsOperationsPage({
    operations: null,
    count: 'много',
    total: 'все',
    totals: { income: 'мало' },
  } as unknown as BddsOperationsResponse)
  assert.deepEqual(broken.rows, [])
  assert.equal(broken.total, null)
  assert.equal(broken.totals, null)
})

// ---------------------------------------------------------------------------
// Суммы и итоги
// ---------------------------------------------------------------------------

test('итог по загруженным строкам складывает типы врозь', () => {
  const rows = [
    normalizeBddsOperation({ operation_type: 'income', amount: 10000 }),
    normalizeBddsOperation({ operation_type: 'income', amount: 5000.25 }),
    normalizeBddsOperation({ operation_type: 'expense', amount: 2000 }),
    normalizeBddsOperation({ operation_type: 'перевод', amount: 999 }),
  ]

  assert.deepEqual(sumBddsOperations(rows), {
    income: 15000.25,
    expense: 2000,
    net: 13000.25,
    // Нераспознанная операция считается строкой, но НЕ суммой: иначе итог
    // сойдётся, а по какой он статье — неизвестно.
    count: 4,
  })
})

test('подпись под итогами различает выборку, её часть и загруженное', () => {
  const withTotals = parseBddsOperationsPage({
    operations: [], count: 0, totals: { income: 1, expense: 0, net: 1, count: 7 },
  })
  assert.match(describeBddsOperationTotals(withTotals), /по всей выборке: 7 оп\./)

  const truncated = parseBddsOperationsPage({
    operations: [], count: 0, truncated: true, totals: { income: 1, expense: 0, net: 1, count: 7 },
  })
  assert.match(describeBddsOperationTotals(truncated), /по прочитанной части/)

  const без = parseBddsOperationsPage({ operations: [{ id: '1' }], count: 1 })
  assert.match(describeBddsOperationTotals(без), /сервер не считал/)
})

// ---------------------------------------------------------------------------
// Фильтры реестра
// ---------------------------------------------------------------------------

test('фильтры считаются и складываются в запрос', () => {
  const filters = {
    projectItemId: '500',
    dateFrom: '2026-08-01',
    dateTo: '2026-08-31',
    type: 'expense' as const,
  }

  assert.equal(countActiveBddsOperationFilters(filters), 4)
  assert.equal(countActiveBddsOperationFilters(DEFAULT_BDDS_OPERATION_FILTERS), 0)

  assert.deepEqual(buildBddsOperationsQuery({ filters, offset: 20, withTotals: true }), {
    limit: String(BDDS_OPERATIONS_PAGE_SIZE),
    offset: '20',
    project_item_id: '500',
    date_from: '2026-08-01',
    date_to: '2026-08-31',
    operation_type: 'expense',
    totals: '1',
  })
})

test('не-ISO граница периода в запрос не уходит', () => {
  // Сервер принимает только ГГГГ-ММ-ДД и прочее отбрасывает молча. Отправить
  // «01.08.2026» значит показать выборку без периода как выборку с периодом.
  const query = buildBddsOperationsQuery({
    filters: { ...DEFAULT_BDDS_OPERATION_FILTERS, dateFrom: '01.08.2026', dateTo: '2026-02-31' },
  })

  assert.equal(query.date_from, undefined)
  assert.equal(query.date_to, undefined)
})

test('перевёрнутый период объясняется до запроса', () => {
  const reversed = { ...DEFAULT_BDDS_OPERATION_FILTERS, dateFrom: '2026-09-01', dateTo: '2026-08-01' }
  assert.match(describeBddsOperationPeriodError(reversed), /позже его конца/)

  const normal = { ...DEFAULT_BDDS_OPERATION_FILTERS, dateFrom: '2026-08-01', dateTo: '2026-09-01' }
  assert.equal(describeBddsOperationPeriodError(normal), '')
  assert.equal(describeBddsOperationPeriodError(DEFAULT_BDDS_OPERATION_FILTERS), '')
})

// ---------------------------------------------------------------------------
// Форма
// ---------------------------------------------------------------------------

test('сумма разбирается в русском написании', () => {
  assert.equal(parseBddsOperationAmount('15 000,50'), 15000.5)
  assert.equal(parseBddsOperationAmount('15000.5'), 15000.5)
  assert.equal(parseBddsOperationAmount(' 12 000 '), 12000)
  assert.equal(parseBddsOperationAmount(''), null)
  assert.equal(parseBddsOperationAmount('15 000 руб'), null)
})

test('заполненная форма превращается в тело запроса с источником manual', () => {
  const result = validateBddsOperationForm({
    form: {
      type: 'expense',
      amount: '15 000,50',
      date: '2026-09-01',
      purpose: 'Аванс подрядчику',
      comment: 'договор 14/26',
    },
    projectItemId: '500',
  })

  assert.equal(result.valid, true)
  assert.deepEqual(result.payload, {
    project_item_id: '500',
    operation_type: 'expense',
    amount: 15000.5,
    operation_date: '2026-09-01',
    title: 'Аванс подрядчику',
    comment: 'договор 14/26',
    // Источник обязан быть manual: у операции по проекту нет сделки, а
    // сервер требует сделку у всякой операции с другим источником.
    source: BDDS_OPERATION_MANUAL_SOURCE,
  })
})

test('пустой комментарий уходит как null, а не как пустая строка', () => {
  const result = validateBddsOperationForm({
    form: { type: 'income', amount: '1000', date: '2026-09-01', purpose: 'Аванс', comment: '  ' },
    projectItemId: '500',
  })

  assert.equal(result.payload?.comment, null)
})

test('форма не пропускает нулевую сумму, чужую дату и пустое назначение', () => {
  const result = validateBddsOperationForm({
    form: { type: 'expense', amount: '0', date: '01.09.2026', purpose: '  ', comment: '' },
    projectItemId: '500',
  })

  assert.equal(result.valid, false)
  assert.equal(result.payload, null)
  assert.match(result.errors.amount || '', /больше нуля/)
  assert.match(result.errors.date || '', /дату/)
  assert.match(result.errors.purpose || '', /назначение/)
})

test('сумма без разрядов отклоняется как опечатка', () => {
  const result = validateBddsOperationForm({
    form: {
      type: 'expense',
      amount: String(BDDS_OPERATION_AMOUNT_LIMIT + 1),
      date: '2026-09-01',
      purpose: 'Аванс',
      comment: '',
    },
    projectItemId: '500',
  })

  assert.equal(result.valid, false)
  assert.match(result.errors.amount || '', /разряды/)
})

test('без элемента смарт-процесса проекта форма не отправляется', () => {
  const result = validateBddsOperationForm({
    form: { type: 'expense', amount: '1000', date: '2026-09-01', purpose: 'Аванс', comment: '' },
    projectItemId: '',
  })

  assert.equal(result.valid, false)
  assert.equal(result.payload, null)
  // Ошибки полей при этом НЕТ: человек всё заполнил верно, дело не в нём.
  assert.deepEqual(result.errors, {})
})

test('форма по умолчанию — списание на сегодня', () => {
  const form = defaultBddsOperationForm(new Date(2026, 8, 12))

  assert.equal(form.type, 'expense')
  assert.equal(form.date, '2026-09-12')
  assert.equal(form.amount, '')
})

test('два запрета формы различаются текстом', () => {
  const noItem = describeBddsOperationFormBlock({ projectItemId: '', canCreate: true })
  assert.match(noItem, /не к чему/)

  const noRights = describeBddsOperationFormBlock({ projectItemId: '500', canCreate: false })
  assert.equal(noRights, BDDS_OPERATION_NO_RIGHTS_TEXT)
  assert.match(noRights, /администратор портала/)
  assert.match(noRights, /Бухгалтерия/)

  assert.equal(describeBddsOperationFormBlock({ projectItemId: '500', canCreate: true }), '')
})

test('повтор объясняется вместе с правилом, по которому он найден', () => {
  const row = normalizeBddsOperation({
    id: '4242', operation_type: 'expense', amount: 15000, operation_date: '2026-09-01',
  })
  const text = describeBddsOperationDuplicate(row)

  assert.match(text, /уже есть/)
  assert.match(text, /01\.09\.2026/)
  assert.match(text, /15\s000\s₽/)
  // Главное в этом тексте — что назначение в проверку не входит: иначе
  // человек будет менять назначение и удивляться повтору.
  assert.match(text, /назначение в проверку не входит/)

  assert.match(describeBddsOperationDuplicate(null), /уже есть/)
})

// ---------------------------------------------------------------------------
// Состояния экрана
// ---------------------------------------------------------------------------

test('«смарт-процесс не настроен» и «операций нет» — разные тексты', () => {
  // Первое ведёт в настройки, второе — рабочее состояние. Показать вместо
  // отказа пустой список значит отправить человека искать ошибку в данных.
  assert.match(BDDS_OPERATIONS_NOT_CONFIGURED_TEXT, /настройках приложения/)
  assert.match(BDDS_OPERATIONS_NOT_CONFIGURED_TEXT, /план и факт по часам/i)

  const emptyProject = describeBddsOperationsEmpty({ filtersActive: 0, scope: 'project' })
  assert.match(emptyProject, /по этому проекту операций пока нет/i)
  assert.doesNotMatch(emptyProject, /настроен/)

  const emptyRegistry = describeBddsOperationsEmpty({ filtersActive: 0, scope: 'registry' })
  assert.match(emptyRegistry, /ни по одному проекту/)

  const filtered = describeBddsOperationsEmpty({ filtersActive: 2, scope: 'registry' })
  assert.match(filtered, /под фильтры/i)
})

// ---------------------------------------------------------------------------
// Влияние на бюджет
// ---------------------------------------------------------------------------

function project(overrides: Partial<BddsProjectRecord> = {}): BddsProjectRecord {
  return {
    project_id: '73',
    project_item_id: '500',
    project_name: 'Портал для сети автосалонов',
    stage: 'В работе',
    is_archived: false,
    is_support: false,
    project_type: 'delivery',
    budget_mode: 'amount',
    hourly_rate: 2000,
    project_hours_budget: null,
    planned_budget_amount: 100000,
    curator_user_id: '11',
    curator_name: 'Егор Цыганков',
    company_id: null,
    company_name: null,
    our_legal_entity_id: null,
    our_legal_entity_name: null,
    project_start_date: '2026-04-01',
    project_end_date: '2026-12-31',
    last_writeoff_at: null,
    last_writeoff_days: 0,
    planned_hours: null,
    planned_amount: 100000,
    actual_hours: 10,
    actual_cost_amount: 20000,
    actual_income_amount: 0,
    actual_expense_amount: 0,
    actual_financial_result: -20000,
    hours_remaining: null,
    budget_remaining: 80000,
    budget_utilization_mode: 'amount',
    budget_utilization_ratio: 0.2,
    budget_utilization_percent: 20,
    budget_health_status: 'Норма',
    risk_threshold_ratio: 0.8,
    overrun_threshold_ratio: 1,
    has_budget: true,
    actual_hours_without_rate_snapshot: 0,
    fallback_hourly_rate: 2000,
    forecast_cost_amount: null,
    forecast_overrun_amount: null,
    forecast_monthly_rate: null,
    forecast_months_elapsed: null,
    forecast_months_left: null,
    forecast_method: 'linear_pace',
    forecast_reason: '',
    ...overrides,
  }
}

test('влияние операции считается сравнением ответов сервера', () => {
  const before = project()
  const after = project({
    actual_expense_amount: 15000,
    actual_financial_result: -35000,
  })

  const impact = describeBddsBudgetImpact(before, after)
  assert.ok(impact)

  const byId = Object.fromEntries((impact?.rows || []).map(row => [row.id, row]))
  assert.equal(byId.expense?.delta, 15000)
  assert.equal(byId.expense?.changed, true)
  assert.equal(byId.result?.delta, -15000)
  assert.equal(byId.result?.changed, true)
})

test('неизменившийся остаток объясняется, а не выглядит поломкой', () => {
  // На этапе 1 остаток бюджета — это план минус стоимость списанных часов
  // (project_budget_service), и операция в него не входит. Без пояснения
  // человек, добавивший расход на 300 000 ₽, пойдёт искать сбой расчёта.
  const before = project()
  const after = project({ actual_expense_amount: 300000, actual_financial_result: -320000 })

  const impact = describeBddsBudgetImpact(before, after)
  const remaining = impact?.rows.find(row => row.id === 'remaining')

  assert.equal(remaining?.changed, false)
  assert.equal(remaining?.delta, 0)
  assert.match(impact?.note || '', /по списанным часам/)
  assert.match(impact?.note || '', /финансовый результат/)
})

test('изменившийся остаток обходится без пояснения', () => {
  const before = project()
  const after = project({ actual_cost_amount: 30000, budget_remaining: 70000 })

  const impact = describeBddsBudgetImpact(before, after)

  assert.equal(impact?.rows.find(row => row.id === 'remaining')?.changed, true)
  assert.equal(impact?.note, '')
})

test('проект без лимита не выдумывает остаток', () => {
  const before = project({ has_budget: false, planned_amount: null, budget_remaining: null })
  const after = project({
    has_budget: false,
    planned_amount: null,
    budget_remaining: null,
    actual_income_amount: 5000,
    actual_financial_result: -15000,
  })

  const impact = describeBddsBudgetImpact(before, after)
  const remaining = impact?.rows.find(row => row.id === 'remaining')

  assert.equal(remaining?.before, null)
  assert.equal(remaining?.delta, null)
  assert.equal(remaining?.changed, false)
})

test('без одного из снимков влияние не показывается вовсе', () => {
  assert.equal(describeBddsBudgetImpact(null, project()), null)
  assert.equal(describeBddsBudgetImpact(project(), null), null)
})

// ---------------------------------------------------------------------------
// Форматирование
// ---------------------------------------------------------------------------

test('копейки операции не округляются до рубля', () => {
  // Операция — документ: 12 000,50 ₽ обязаны остаться 12 000,50 ₽, иначе в
  // интерфейсе стоит сумма, которой в CRM нет.
  assert.equal(formatBddsOperationAmount(12000.5).replace(/ /g, ' '), '12 000,50 ₽')
  assert.equal(formatBddsOperationAmount(12000).replace(/ /g, ' '), '12 000 ₽')
  assert.equal(formatBddsOperationAmount(null), '—')
  assert.equal(formatBddsOperationAmount(undefined), '—')
})

test('знак суммы берётся из типа, а не из числа', () => {
  const income = normalizeBddsOperation({ operation_type: 'income', amount: 5000 })
  const expense = normalizeBddsOperation({ operation_type: 'expense', amount: 5000 })
  const unknown = normalizeBddsOperation({ operation_type: 'перевод', amount: 5000 })

  assert.match(formatBddsOperationSignedAmount(income), /^\+/)
  assert.match(formatBddsOperationSignedAmount(expense), /^−/)
  assert.doesNotMatch(formatBddsOperationSignedAmount(unknown), /^[+−]/)
})

test('изменение показателя подписано «без изменений», а не нулём', () => {
  assert.equal(formatBddsOperationDelta(0), 'без изменений')
  assert.equal(formatBddsOperationDelta(0.001), 'без изменений')
  assert.equal(formatBddsOperationDelta(null), '—')
  assert.match(formatBddsOperationDelta(1500), /^\+/)
  assert.match(formatBddsOperationDelta(-1500), /^−/)
})

test('дата и источник читаются человеком', () => {
  assert.equal(formatBddsOperationDate('2026-08-20'), '20.08.2026')
  assert.equal(formatBddsOperationDate('2026-08-20T00:00:00+03:00'), '20.08.2026')
  assert.equal(formatBddsOperationDate(''), '—')
  assert.equal(formatBddsOperationDate('что-то'), 'что-то')

  assert.equal(formatBddsOperationSource('manual'), 'вручную')
  assert.equal(formatBddsOperationSource('deal_embed'), 'из сделки')
  assert.equal(formatBddsOperationSource('import_1c'), 'import_1c')
  assert.equal(formatBddsOperationSource(''), '—')
})

test('автор без имени в справочнике показывается идентификатором', () => {
  // По id человека находят в портале, по пустой ячейке — нет.
  assert.equal(formatBddsOperationAuthor('11', { 11: 'Цыганков Егор' }), 'Цыганков Егор')
  assert.equal(formatBddsOperationAuthor('12', { 11: 'Цыганков Егор' }), 'сотрудник #12')
  assert.equal(formatBddsOperationAuthor('12', null), 'сотрудник #12')
  assert.equal(formatBddsOperationAuthor('', null), '—')
})

test('проверка ISO-даты не пропускает несуществующие числа', () => {
  assert.equal(isIsoDate('2026-09-12'), true)
  assert.equal(isIsoDate('2026-02-31'), false)
  assert.equal(isIsoDate('12.09.2026'), false)
  assert.equal(isIsoDate(''), false)
  assert.equal(isIsoDate(null), false)
})

test('пресет «этот месяц» даёт границы месяца', () => {
  const day = new Date(2026, 8, 12)

  assert.equal(firstDayOfMonth(day), '2026-09-01')
  assert.equal(toIsoDate(day), '2026-09-12')
})
