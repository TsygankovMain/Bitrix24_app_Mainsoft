import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BOARD_RISK_DAYS,
  DEFAULT_PROJECT_BOARD_FILTERS,
  boardCardRiskReasons,
  buildBoardColumnStats,
  buildBoardEmptyState,
  buildBoardColumns,
  buildBoardInitials,
  buildBoardUtilization,
  buildBoardViewStorageKey,
  countActiveBoardFilters,
  filterBoardCards,
  formatBoardActivity,
  formatBoardHours,
  formatBoardMoneyShort,
  getBoardStageDotClass,
  isBoardCardAtRisk,
  isBoardCardMine,
  matchesBoardSearch,
  normalizeBoardFilters,
  parseBoardViewState,
  serializeBoardViewState,
  sortBoardCards,
} from '../app/utils/projectBoardView'
import type { ProjectBoardCardRecord } from '../app/types/project-board'

function makeCard(overrides: Partial<ProjectBoardCardRecord> = {}): ProjectBoardCardRecord {
  return {
    id: '1',
    project_item_id: null,
    project_id: '101',
    project_name: 'Внедрение CRM',
    stage: 'В работе',
    manual_stage: 'В работе',
    is_archived: false,
    archived_at: null,
    project_hours_budget: null,
    hourly_rate: 3000,
    is_support: false,
    project_type: 'delivery',
    budget_mode: 'hours',
    planned_budget_amount: null,
    planned_hours: null,
    planned_amount: null,
    actual_hours: 0,
    actual_cost_amount: 0,
    actual_income_amount: 0,
    actual_expense_amount: 0,
    actual_financial_result: 0,
    hours_remaining: null,
    budget_remaining: null,
    budget_utilization_mode: 'none',
    budget_utilization_ratio: null,
    budget_utilization_percent: null,
    budget_health_status: 'Без лимита',
    curator_user_id: '7',
    curator_name: 'Анна Воронцова',
    project_start_date: null,
    project_end_date: null,
    company_id: '12',
    company_name: 'ООО «Северный ветер»',
    our_legal_entity_id: '3',
    our_legal_entity_name: 'ООО «Мейнсофт»',
    last_writeoff_at: '2026-09-11',
    last_writeoff_days: 1,
    stage_source: 'manual',
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

// --- Риск ---

test('boardCardRiskReasons: давность списаний и бюджет — два независимых признака', () => {
  assert.deepEqual(boardCardRiskReasons(makeCard()), [])

  assert.deepEqual(
    boardCardRiskReasons(makeCard({ last_writeoff_days: BOARD_RISK_DAYS })),
    ['Нет списаний 30 дн.']
  )

  assert.deepEqual(
    boardCardRiskReasons(makeCard({ budget_health_status: 'Перерасход' })),
    ['Бюджет: перерасход']
  )

  assert.equal(
    boardCardRiskReasons(makeCard({ last_writeoff_days: 97, budget_health_status: 'Риск' })).length,
    2
  )
})

test('boardCardRiskReasons: автостадия считается риском даже при свежем счётчике дней', () => {
  // Ночное задание ставит стадию раньше, чем пересчитывается счётчик, и наоборот.
  const card = makeCard({ stage: 'Нет списаний 3 месяца', last_writeoff_days: 0 })

  assert.equal(isBoardCardAtRisk(card), true)
  assert.deepEqual(boardCardRiskReasons(card), ['Нет списаний'])
})

test('isBoardCardMine: без известного пользователя ничьих проектов нет', () => {
  const card = makeCard({ curator_user_id: '7' })

  assert.equal(isBoardCardMine(card, 7), true)
  assert.equal(isBoardCardMine(card, '7'), true)
  assert.equal(isBoardCardMine(card, '8'), false)
  assert.equal(isBoardCardMine(card, 0), false)
  assert.equal(isBoardCardMine(card, null), false)
})

// --- Фильтры ---

test('normalizeBoardFilters: мусор из хранилища превращается в набор по умолчанию', () => {
  assert.deepEqual(normalizeBoardFilters(null), DEFAULT_PROJECT_BOARD_FILTERS)
  assert.deepEqual(normalizeBoardFilters('строка'), DEFAULT_PROJECT_BOARD_FILTERS)
  assert.deepEqual(normalizeBoardFilters([1, 2]), DEFAULT_PROJECT_BOARD_FILTERS)

  assert.deepEqual(
    normalizeBoardFilters({ search: '  crm ', curatorId: 7, projectType: 'нет такого', sort: 'нет такой', onlyRisk: 'да' }),
    {
      ...DEFAULT_PROJECT_BOARD_FILTERS,
      search: 'crm',
      curatorId: '7',
    }
  )
})

test('countActiveBoardFilters: считаем только то, что прячет проекты, — сортировка не в счёт', () => {
  assert.equal(countActiveBoardFilters(DEFAULT_PROJECT_BOARD_FILTERS), 0)
  assert.equal(countActiveBoardFilters({ ...DEFAULT_PROJECT_BOARD_FILTERS, sort: 'activity' }), 0)
  assert.equal(countActiveBoardFilters({ ...DEFAULT_PROJECT_BOARD_FILTERS, search: '   ' }), 0)
  assert.equal(
    countActiveBoardFilters({
      ...DEFAULT_PROJECT_BOARD_FILTERS,
      search: 'crm',
      curatorId: '7',
      onlyRisk: true,
    }),
    3
  )
})

test('matchesBoardSearch: ищем по названию, компании, ИНН и куратору', () => {
  const card = makeCard({ company_inn: '7325001122' })

  assert.equal(matchesBoardSearch(card, ''), true)
  assert.equal(matchesBoardSearch(card, 'внедрение'), true)
  assert.equal(matchesBoardSearch(card, 'северный'), true)
  assert.equal(matchesBoardSearch(card, '73250011'), true)
  assert.equal(matchesBoardSearch(card, 'воронцова'), true)
  assert.equal(matchesBoardSearch(card, 'кедр'), false)
})

test('filterBoardCards: фильтры складываются, а не заменяют друг друга', () => {
  const cards = [
    makeCard({ project_id: '1', curator_user_id: '7', is_support: false, last_writeoff_days: 0 }),
    makeCard({ project_id: '2', curator_user_id: '7', is_support: true, project_type: 'support', last_writeoff_days: 40 }),
    makeCard({ project_id: '3', curator_user_id: '8', is_support: false, last_writeoff_days: 90 }),
  ]

  const mineAndRisk = filterBoardCards(
    cards,
    { ...DEFAULT_PROJECT_BOARD_FILTERS, onlyMine: true, onlyRisk: true },
    { currentUserId: '7' }
  )

  assert.deepEqual(mineAndRisk.map(card => card.project_id), ['2'])

  const deliveryOnly = filterBoardCards(cards, { ...DEFAULT_PROJECT_BOARD_FILTERS, projectType: 'delivery' })
  assert.deepEqual(deliveryOnly.map(card => card.project_id), ['1', '3'])

  const supportOnly = filterBoardCards(cards, { ...DEFAULT_PROJECT_BOARD_FILTERS, projectType: 'support' })
  assert.deepEqual(supportOnly.map(card => card.project_id), ['2'])
})

test('filterBoardCards: «мои» без известного пользователя не прячет доску целиком по ошибке', () => {
  const cards = [makeCard({ project_id: '1', curator_user_id: '7' })]

  // Пользователь ещё не подгрузился: честнее показать пусто, чем чужие проекты
  // под видом своих. Проверка фиксирует поведение, чтобы оно не менялось молча.
  assert.deepEqual(
    filterBoardCards(cards, { ...DEFAULT_PROJECT_BOARD_FILTERS, onlyMine: true }, { currentUserId: 0 }),
    []
  )
})

test('sortBoardCards: четыре порядка, карточки без числа всегда внизу', () => {
  const cards = [
    makeCard({ project_id: '1', project_name: 'Бета', last_writeoff_days: 5, budget_utilization_percent: 20, planned_amount: 100000 }),
    makeCard({ project_id: '2', project_name: 'Альфа', last_writeoff_days: 40, budget_utilization_percent: null, planned_amount: 500000 }),
    makeCard({ project_id: '3', project_name: 'Гамма', last_writeoff_days: 1, budget_utilization_percent: 95, planned_amount: null }),
  ]

  assert.deepEqual(sortBoardCards(cards, 'name').map(card => card.project_name), ['Альфа', 'Бета', 'Гамма'])
  assert.deepEqual(sortBoardCards(cards, 'activity').map(card => card.project_id), ['2', '1', '3'])
  assert.deepEqual(sortBoardCards(cards, 'utilization').map(card => card.project_id), ['3', '1', '2'])
  assert.deepEqual(sortBoardCards(cards, 'budget').map(card => card.project_id), ['2', '1', '3'])
})

test('sortBoardCards: исходный массив не переставляется', () => {
  const cards = [makeCard({ project_name: 'Бета' }), makeCard({ project_name: 'Альфа' })]
  sortBoardCards(cards, 'name')

  assert.deepEqual(cards.map(card => card.project_name), ['Бета', 'Альфа'])
})

// --- Подписи ---

test('formatBoardActivity: сегодня, вчера, дни и «списаний нет»', () => {
  assert.equal(formatBoardActivity(makeCard({ last_writeoff_at: null })), 'Списаний нет')
  assert.equal(formatBoardActivity(makeCard({ last_writeoff_days: 0 })), 'сегодня')
  assert.equal(formatBoardActivity(makeCard({ last_writeoff_days: 1 })), 'вчера')
  assert.equal(formatBoardActivity(makeCard({ last_writeoff_days: 34 })), '34 дн.')
})

// Intl для ru-RU разделяет разряды НЕРАЗРЫВНЫМ пробелом (U+00A0), а не обычным.
// Подписи сравниваем с ним же — иначе тест «падает на невидимом символе».
const NBSP = '\u00A0'

test('formatBoardMoneyShort: миллионы и тысячи вместо длинного числа', () => {
  assert.equal(formatBoardMoneyShort(1_240_000), '1,2 млн ₽')
  assert.equal(formatBoardMoneyShort(320_000), '320 тыс ₽')
  assert.equal(formatBoardMoneyShort(4200), `4${NBSP}200 ₽`)
  assert.equal(formatBoardMoneyShort(0), '—')
  assert.equal(formatBoardMoneyShort(null), '—')
})

test('formatBoardHours: целые часы с разделителем разрядов', () => {
  assert.equal(formatBoardHours(400), '400 ч')
  assert.equal(formatBoardHours(1234.6), `1${NBSP}235 ч`)
  assert.equal(formatBoardHours(null), '0 ч')
})

test('buildBoardInitials: две буквы из имени, прочерк — если имени нет', () => {
  assert.equal(buildBoardInitials('Анна Воронцова'), 'АВ')
  assert.equal(buildBoardInitials('Ким'), 'К')
  assert.equal(buildBoardInitials('  '), '—')
  assert.equal(buildBoardInitials(null), '—')
})

test('getBoardStageDotClass: у незнакомой стадии свой нейтральный цвет, а не пустая строка', () => {
  assert.equal(getBoardStageDotClass('В работе'), 'bg-emerald-500')
  assert.equal(getBoardStageDotClass('Согласование у клиента'), 'bg-slate-300')
  assert.equal(getBoardStageDotClass(null), 'bg-slate-300')
})

test('buildBoardUtilization: без бюджета полосы нет, а есть факт', () => {
  const result = buildBoardUtilization(makeCard({ actual_hours: 27 }))

  assert.equal(result.isEmpty, true)
  assert.equal(result.barPercent, 0)
  assert.equal(result.label, '27 ч без лимита')
})

test('buildBoardUtilization: часовой бюджет — «факт из плана», перерасход упирается в 100', () => {
  const result = buildBoardUtilization(makeCard({
    budget_utilization_mode: 'hours',
    planned_hours: 160,
    actual_hours: 188,
    budget_utilization_percent: 117.5,
    budget_health_status: 'Перерасход',
  }))

  assert.equal(result.label, '188 из 160 ч')
  assert.equal(result.barPercent, 100)
  assert.equal(result.tone, 'danger')
  assert.equal(result.isEmpty, false)
})

test('buildBoardUtilization: денежный бюджет печатается деньгами', () => {
  const result = buildBoardUtilization(makeCard({
    budget_utilization_mode: 'amount',
    planned_amount: 1_200_000,
    actual_cost_amount: 640_000,
    budget_utilization_percent: 53.3,
    budget_health_status: 'Риск',
  }))

  assert.equal(result.label, '640 тыс ₽ из 1,2 млн ₽')
  assert.equal(result.tone, 'warning')
})

// --- Колонки ---

test('buildBoardColumnStats: счётчик, риски и сумма часов с деньгами', () => {
  const stats = buildBoardColumnStats([
    makeCard({ project_id: '1', planned_hours: 400, actual_hours: 312, planned_amount: 1_200_000 }),
    makeCard({ project_id: '2', planned_hours: 120, actual_hours: 64, last_writeoff_days: 40 }),
  ])

  assert.equal(stats.count, 2)
  assert.equal(stats.riskCount, 1)
  assert.equal(stats.actualHours, 376)
  assert.equal(stats.plannedHours, 520)
  assert.equal(stats.summaryLabel, '376/520 ч · 1,2 млн ₽')
})

test('buildBoardColumnStats: пустая колонка — нулевые числа и пустая подпись', () => {
  const stats = buildBoardColumnStats([])

  assert.equal(stats.count, 0)
  assert.equal(stats.summaryLabel, '')
})

test('buildBoardColumns: карточка попадает в колонку и по id стадии, и по её названию', () => {
  const stages = [
    { id: 'В работе', title: 'В работе', kind: 'manual' as const, can_drop: true },
    { id: '7', title: 'Успех', kind: 'manual' as const, can_drop: true },
    { id: 'auto-30', title: 'Нет списаний 1 месяц', kind: 'auto' as const, can_drop: false },
  ]

  const columns = buildBoardColumns(
    stages,
    [
      makeCard({ project_id: '1', project_name: 'Бета', stage: 'В работе' }),
      makeCard({ project_id: '2', project_name: 'Альфа', stage: 'В работе' }),
      makeCard({ project_id: '3', stage: '7' }),
      makeCard({ project_id: '4', stage: 'Нет списаний 1 месяц', last_writeoff_days: 40 }),
    ],
    'name'
  )

  assert.deepEqual(columns.map(column => column.title), ['В работе', 'Успех', 'Нет списаний 1 месяц'])
  assert.deepEqual(columns[0]?.cards.map(card => card.project_name), ['Альфа', 'Бета'])
  assert.equal(columns[1]?.cards.length, 1)
  assert.equal(columns[2]?.canDrop, false)
  assert.equal(columns[2]?.stats.riskCount, 1)
  assert.equal(columns[0]?.dotClass, 'bg-emerald-500')
})

// --- Хранение ---

test('buildBoardViewStorageKey: ключ разделяет порталы и пользователей', () => {
  assert.equal(
    buildBoardViewStorageKey({ portal: 'https://Mainsoft.bitrix24.ru/', userId: 11 }),
    'ms-project-board-view-v1:mainsoft.bitrix24.ru:11'
  )
  assert.equal(
    buildBoardViewStorageKey({}),
    'ms-project-board-view-v1:unknown:unknown'
  )
})

test('parseBoardViewState: сохранённое состояние возвращается целиком, битое — по умолчанию', () => {
  const state = {
    view: 'archive' as const,
    filters: { ...DEFAULT_PROJECT_BOARD_FILTERS, search: 'crm', onlyMine: true, sort: 'activity' as const },
  }

  assert.deepEqual(parseBoardViewState(serializeBoardViewState(state)), state)
  assert.deepEqual(parseBoardViewState('{не json'), {
    view: 'board',
    filters: DEFAULT_PROJECT_BOARD_FILTERS,
  })
  assert.deepEqual(parseBoardViewState(null), {
    view: 'board',
    filters: DEFAULT_PROJECT_BOARD_FILTERS,
  })
  assert.equal(parseBoardViewState('{"view":"нет такого"}').view, 'board')
})

// --- Пустые состояния ---

test('buildBoardEmptyState: пока карточки видны, заглушки нет', () => {
  assert.equal(
    buildBoardEmptyState({ view: 'board', totalCards: 10, visibleCount: 3, scopeCount: 8, activeFilters: 2 }),
    null
  )
})

test('buildBoardEmptyState: доска без единого проекта зовёт синхронизировать, а не сбрасывать фильтры', () => {
  const state = buildBoardEmptyState({ view: 'board', totalCards: 0, visibleCount: 0, scopeCount: 0, activeFilters: 3 })

  assert.equal(state?.title, 'Доска пока пустая')
  assert.equal(state?.showSync, true)
  assert.equal(state?.showReset, false)
})

test('buildBoardEmptyState: проекты спрятал отбор — предлагаем снять его и говорим, сколько их всего', () => {
  const state = buildBoardEmptyState({ view: 'board', totalCards: 40, visibleCount: 0, scopeCount: 37, activeFilters: 1 })

  assert.equal(state?.title, 'Под выбранные фильтры проектов нет')
  assert.equal(state?.hint.includes('37'), true)
  assert.equal(state?.showReset, true)
  assert.equal(state?.showSync, false)
})

test('buildBoardEmptyState: пустой архив без фильтров — не «сбросьте фильтры» и не «синхронизируйте»', () => {
  const state = buildBoardEmptyState({ view: 'archive', totalCards: 12, visibleCount: 0, scopeCount: 0, activeFilters: 0 })

  assert.equal(state?.title, 'В архиве пусто')
  assert.equal(state?.showSync, false)
  assert.equal(state?.showReset, false)
})

test('buildBoardEmptyState: все проекты уехали в архив — доска объясняет это, а не молчит', () => {
  const state = buildBoardEmptyState({ view: 'board', totalCards: 12, visibleCount: 0, scopeCount: 0, activeFilters: 0 })

  assert.equal(state?.title, 'Активных проектов нет')
  assert.equal(state?.hint.includes('Архив'), true)
})
