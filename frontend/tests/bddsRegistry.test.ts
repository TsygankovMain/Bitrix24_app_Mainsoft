import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BDDS_STATUS_FILTERS,
  bddsBarPercent,
  bddsForecastExceedsPlan,
  bddsProjectSubtitle,
  bddsStatusTone,
  bddsUtilizationTone,
  buildBddsChips,
  buildBddsKpis,
  countActiveBddsFilters,
  DEFAULT_BDDS_FILTERS,
  describeBddsForecast,
  describeBddsNotifierRun,
  describeBddsNoBudget,
  describeBddsRateGap,
  filterBddsProjects,
  formatBddsPlan,
  formatBddsRemaining,
  matchesBddsStatusFilter,
} from '../app/utils/bddsRegistry'
import type { BddsProjectRecord, BddsThresholds, BddsTotals } from '../app/types/bdds'

const THRESHOLDS: BddsThresholds = {
  risk_percent: 80,
  overrun_percent: 100,
  support_boundary_amount: 100000,
  notifications_enabled: true,
  notify_cooldown_hours: 12,
  notify_user_ids: [],
}

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
    project_hours_budget: 500,
    planned_budget_amount: 1000000,
    curator_user_id: '11',
    curator_name: 'Егор Цыганков',
    company_id: '15',
    company_name: 'ООО Клиент',
    our_legal_entity_id: '7',
    our_legal_entity_name: 'ООО Майнсофт',
    project_start_date: '2026-04-01',
    project_end_date: '2026-12-31',
    last_writeoff_at: '2026-09-10T10:00:00+03:00',
    last_writeoff_days: 2,
    planned_hours: 500,
    planned_amount: 1000000,
    actual_hours: 300,
    actual_cost_amount: 600000,
    actual_income_amount: 400000,
    actual_expense_amount: 0,
    actual_financial_result: -200000,
    hours_remaining: 200,
    budget_remaining: 400000,
    budget_utilization_mode: 'amount',
    budget_utilization_ratio: 0.6,
    budget_utilization_percent: 60,
    budget_health_status: 'Норма',
    budget_health_reason: 'Освоение бюджета: 60%.',
    risk_threshold_ratio: 0.8,
    overrun_threshold_ratio: 1,
    has_budget: true,
    actual_hours_without_rate_snapshot: 0,
    fallback_hourly_rate: 2000,
    forecast_cost_amount: 900000,
    forecast_overrun_amount: -100000,
    forecast_monthly_rate: 100000,
    forecast_months_elapsed: 6,
    forecast_months_left: 3,
    forecast_method: 'linear_pace',
    forecast_reason: 'Факт 600000.00 ₽ за 6 мес. плюс текущий темп 100000.00 ₽/мес. × 3 мес. до конца проекта.',
    ...overrides,
  }
}

const support = () => project({
  project_id: '74',
  project_name: 'Поддержка',
  is_support: true,
  project_type: 'support',
  budget_mode: 'support',
  planned_budget_amount: null,
  project_hours_budget: null,
  planned_amount: null,
  planned_hours: null,
  budget_remaining: null,
  hours_remaining: null,
  budget_utilization_mode: 'support',
  budget_utilization_ratio: null,
  budget_utilization_percent: null,
  budget_health_status: 'Граница',
  support_health_status: 'Граница',
  has_budget: false,
  forecast_cost_amount: null,
  forecast_overrun_amount: null,
  forecast_months_elapsed: null,
  forecast_months_left: null,
  forecast_monthly_rate: null,
  forecast_reason: 'Прогноз у проектов поддержки не считается: у них нет плана, контролируется финансовый результат.',
})

test('зоны статуса: «Граница» жёлтая как «Риск», «Плюс» зелёный как «Норма»', () => {
  assert.equal(bddsStatusTone('Норма'), 'ok')
  assert.equal(bddsStatusTone('Плюс'), 'ok')
  assert.equal(bddsStatusTone('Риск'), 'warning')
  assert.equal(bddsStatusTone('Граница'), 'warning')
  assert.equal(bddsStatusTone('Перерасход'), 'danger')
  assert.equal(bddsStatusTone('Минус'), 'danger')
  assert.equal(bddsStatusTone('Без лимита'), 'neutral')
  assert.equal(bddsStatusTone(null), 'neutral')
})

test('чип «Без лимита» ловит поддержку по признаку has_budget, а не по названию статуса', () => {
  const rows = [project(), support()]

  assert.equal(matchesBddsStatusFilter(rows[1]!, 'nolimit'), true)
  // У поддержки статус «Граница» — по статусу она попала бы в «Риск», и
  // человек искал бы её в чипе «Без лимита» напрасно.
  assert.equal(matchesBddsStatusFilter(rows[1]!, 'risk'), true)
  assert.equal(matchesBddsStatusFilter(rows[0]!, 'nolimit'), false)
})

test('чипы считаются по всему портфелю и включают «Все»', () => {
  const chips = buildBddsChips([
    project(),
    project({ project_id: '81', budget_health_status: 'Перерасход' }),
    support(),
  ])

  assert.deepEqual(chips.map(chip => chip.id), BDDS_STATUS_FILTERS.map(item => item.id))
  assert.equal(chips.find(chip => chip.id === 'all')?.count, 3)
  assert.equal(chips.find(chip => chip.id === 'ok')?.count, 1)
  assert.equal(chips.find(chip => chip.id === 'over')?.count, 1)
  assert.equal(chips.find(chip => chip.id === 'nolimit')?.count, 1)
})

test('фильтр по статусу, поиску, лимиту и прогнозу складываются', () => {
  const rows = [
    project(),
    project({ project_id: '81', project_name: 'Второй', forecast_overrun_amount: 50000 }),
    support(),
  ]

  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS }).length, 3)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, onlyWithBudget: true }).length, 2)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, onlyForecastOverrun: true }).length, 1)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, query: 'втор' }).length, 1)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, status: 'nolimit' }).length, 1)
})

test('поиск смотрит и в клиента, и в куратора — как на доске проектов', () => {
  const rows = [project()]

  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, query: 'ООО Клиент' }).length, 1)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, query: 'Цыганков' }).length, 1)
  assert.equal(filterBddsProjects(rows, { ...DEFAULT_BDDS_FILTERS, query: 'нет такого' }).length, 0)
})

test('счётчик активных фильтров не считает пустой поиск', () => {
  assert.equal(countActiveBddsFilters({ ...DEFAULT_BDDS_FILTERS }), 0)
  assert.equal(countActiveBddsFilters({ ...DEFAULT_BDDS_FILTERS, query: '   ' }), 0)
  assert.equal(countActiveBddsFilters({
    ...DEFAULT_BDDS_FILTERS,
    status: 'risk',
    query: 'портал',
    onlyWithBudget: true,
  }), 3)
})

/**
 * Пробелы в суммах — НЕРАЗРЫВНЫЕ: их ставит Intl.NumberFormat('ru-RU').
 * Сравнивать с обычным пробелом бессмысленно: строки выглядят одинаково, а
 * тест падает с «одинаковыми» значениями в отчёте.
 */
function plain(value: string): string {
  return value.replace(/\u00a0/g, ' ')
}

test('план у проекта без лимита — «Без лимита», а не ноль и не прочерк', () => {
  assert.equal(formatBddsPlan(support()), 'Без лимита')
  assert.equal(plain(formatBddsPlan(project())), '1 000 000 ₽ · 500 ч')
})

test('отрицательный остаток подписан словами «сверх плана»', () => {
  assert.equal(
    plain(formatBddsRemaining(project({ budget_remaining: -120000 }))),
    '120 000 ₽ сверх плана'
  )
  assert.equal(formatBddsRemaining(support()), '—')
})

test('прогноз: экономия и выход за план различаются текстом и зоной', () => {
  const saving = describeBddsForecast(project())
  assert.equal(saving.isEmpty, false)
  assert.equal(saving.tone, 'ok')
  assert.match(saving.deviation, /экономия/)

  const overrun = describeBddsForecast(project({
    forecast_cost_amount: 1088000,
    forecast_overrun_amount: 88000,
  }))
  assert.equal(overrun.tone, 'danger')
  assert.match(overrun.deviation, /сверх плана/)
  assert.match(overrun.explanation, /темп/)
})

test('прогноз не посчитан — показываем ПРИЧИНУ, а не ноль', () => {
  const view = describeBddsForecast(project({
    forecast_cost_amount: null,
    forecast_overrun_amount: null,
    forecast_reason: 'Прогноз не посчитан: в карточке проекта не задана дата окончания.',
  }))

  assert.equal(view.isEmpty, true)
  assert.equal(view.value, '—')
  assert.match(view.explanation, /дата окончания/)
})

test('прогноз ровно в план не красится ни в красный, ни в зелёный', () => {
  const view = describeBddsForecast(project({ forecast_overrun_amount: 0 }))

  assert.equal(view.tone, 'neutral')
  assert.equal(view.deviation, 'ровно в план')
})

test('прогноз без плана не может «выходить за план»', () => {
  assert.equal(bddsForecastExceedsPlan(support()), false)
  assert.equal(bddsForecastExceedsPlan(project({ forecast_overrun_amount: null })), false)
  assert.equal(bddsForecastExceedsPlan(project({ forecast_overrun_amount: 1 })), true)
})

test('часы без снимка ставки оговариваются, а при нуле оговорки нет', () => {
  assert.equal(describeBddsRateGap(project()), null)

  const note = describeBddsRateGap(project({
    actual_hours_without_rate_snapshot: 4,
    fallback_hourly_rate: 1500,
  }))
  assert.ok(note)
  assert.match(note!, /4 ч/)
  assert.match(note!, /оценка/)
})

test('проект без лимита объясняется по-разному у поддержки и у обычного проекта', () => {
  assert.match(describeBddsNoBudget(support()), /Поддержка/)
  assert.match(describeBddsNoBudget(support()), /финансовый результат/)
  assert.match(
    describeBddsNoBudget(project({ has_budget: false, is_support: false })),
    /лимит в карточке проекта не заведён/
  )
})

test('вторая строка проекта: клиент, куратор, срок', () => {
  assert.equal(
    bddsProjectSubtitle(project()),
    'ООО Клиент · куратор Егор Цыганков · до 31.12.2026'
  )
  assert.equal(
    bddsProjectSubtitle(project({ company_name: null, curator_name: null, project_end_date: null })),
    ''
  )
})

test('зона освоения считается по порогам ПОРТАЛА, а не по 80/100 в коде', () => {
  const strict = { risk_percent: 50, overrun_percent: 55 }

  assert.equal(bddsUtilizationTone(60, THRESHOLDS), 'ok')
  assert.equal(bddsUtilizationTone(60, strict), 'danger')
  assert.equal(bddsUtilizationTone(80, THRESHOLDS), 'warning')
  assert.equal(bddsUtilizationTone(100, THRESHOLDS), 'warning')
  assert.equal(bddsUtilizationTone(100.1, THRESHOLDS), 'danger')
  assert.equal(bddsUtilizationTone(null, THRESHOLDS), 'neutral')
})

test('полоса освоения упирается в 100 и не уходит в минус', () => {
  assert.equal(bddsBarPercent(0), 0)
  assert.equal(bddsBarPercent(-5), 0)
  assert.equal(bddsBarPercent(62.34), 62.3)
  assert.equal(bddsBarPercent(180), 100)
  assert.equal(bddsBarPercent(null), 0)
})

test('показатели портфеля: пять карточек, порог в подсказке, источник цифры', () => {
  const totals: BddsTotals = {
    projects_count: 3,
    with_budget_count: 2,
    without_budget_count: 1,
    planned_amount: 1000000,
    planned_hours: 500,
    actual_cost_amount: 700000,
    actual_cost_amount_with_budget: 600000,
    actual_hours: 350,
    actual_income_amount: 400000,
    actual_expense_amount: 50000,
    actual_financial_result: -350000,
    budget_remaining: 400000,
    budget_utilization_percent: 60,
  }

  const kpis = buildBddsKpis(totals, { 'Риск': 1, 'Перерасход': 1, attention: 2 }, THRESHOLDS)

  assert.equal(kpis.length, 5)
  assert.deepEqual(kpis.map(kpi => kpi.id), [
    'plan', 'fact', 'utilization', 'financial-result', 'attention',
  ])
  assert.equal(kpis[0]!.source, 'расчёт')
  assert.equal(kpis[1]!.source, 'списания')
  assert.equal(plain(kpis[2]!.hint), 'порог риска 80% · перерасхода 100%')
  assert.equal(kpis[3]!.tone, 'danger')
  assert.equal(kpis[4]!.value, '2')
  assert.match(kpis[4]!.hint, /1 риск · 1 перерасход · 1 без лимита/)
})

test('пустое освоение портфеля — прочерк, а не ноль процентов', () => {
  const totals: BddsTotals = {
    projects_count: 1,
    with_budget_count: 0,
    without_budget_count: 1,
    planned_amount: 0,
    planned_hours: 0,
    actual_cost_amount: 20000,
    actual_cost_amount_with_budget: 0,
    actual_hours: 10,
    actual_income_amount: 0,
    actual_expense_amount: 0,
    actual_financial_result: -20000,
    budget_remaining: null,
    budget_utilization_percent: null,
  }

  const kpis = buildBddsKpis(totals, { attention: 0 }, THRESHOLDS)

  assert.equal(kpis[2]!.value, '—')
  assert.equal(kpis[2]!.tone, 'neutral')
})

test('итог прогона уведомлений: выключенная настройка объясняется отдельно', () => {
  assert.equal(
    describeBddsNotifierRun({ status: 'disabled' }),
    'Уведомления выключены настройкой — прогон ничего не отправил.'
  )
})

test('итог прогона: «новых событий нет» вместо трёх нулей', () => {
  assert.equal(
    describeBddsNotifierRun({ status: 'ok', checked: 12, sent: 0 }),
    'Проверено проектов: 12 · отправлено: 0 · новых событий нет.'
  )
})

test('итог прогона показывает паузу и ошибки отправки', () => {
  assert.equal(
    describeBddsNotifierRun({ status: 'ok', checked: 12, sent: 2, cooldown_skipped: 1, errors: 1 }),
    'Проверено проектов: 12 · отправлено: 2 · отложено паузой: 1 · ошибок отправки: 1.'
  )
})

test('прогона не было — текста нет', () => {
  assert.equal(describeBddsNotifierRun(null), '')
})
