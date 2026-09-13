/**
 * Модель доски проектов: фильтры, сортировка, колонки и подписи карточки.
 *
 * Зачем отдельный файл рядом с projectBoard.ts. В projectBoard.ts живут
 * форматтеры и палитра стадий — то, что нужно ещё и дроверу, и хронологии.
 * Здесь — ВИД ДОСКИ: что показывается, в каком порядке и что попадает в
 * колонку. Это и есть логика, которую переделывал редизайн, и её обязано
 * проверять ревью, а не глаз на живом портале.
 *
 * Здесь только ЧИСТЫЕ функции: node:test через tsx не резолвит .vue, поэтому
 * всё, что осталось бы внутри компонента, тестами закрыть нельзя. Компоненты
 * (components/projects/*.vue) рисуют то, что вернули эти функции, и сами
 * ничего не считают.
 *
 * ИМЕНА С ПРЕФИКСОМ Board. Nuxt автоимпортирует всё из app/utils, и совпадение
 * имён с homeDashboard.ts (там уже есть isProjectAtRisk, formatHours) даёт
 * предупреждение сборки «Duplicated imports» и молча выигрывающий чужой
 * экспорт. Поэтому здесь всё зовётся ...Board... даже там, где короткое имя
 * читалось бы приятнее.
 */

import type { ProjectBoardCardRecord, ProjectBoardResponse } from '../types/project-board'

/**
 * Что читает функция доски — и ничего сверх того.
 *
 * Понадобилось экрану БДДС: строка его реестра — та же карточка проекта, но
 * без служебных полей доски (id записи, ручная стадия, источник стадии), и
 * рисовать её обязаны ТЕ ЖЕ функции. Требовать полный ProjectBoardCardRecord
 * означало бы либо копию этих функций под БДДС, либо выдуманные поля в её
 * контракте. Сужение обратно совместимо: полная карточка доски подходит под
 * любой из типов ниже.
 */
type BoardSearchable = Partial<Pick<
  ProjectBoardCardRecord,
  'project_name' | 'project_id' | 'curator_name' | 'company_name'
  | 'company_inn' | 'our_legal_entity_name' | 'our_legal_entity_inn' | 'stage'
>>

type BoardRiskable = Partial<Pick<
  ProjectBoardCardRecord,
  'last_writeoff_days' | 'stage' | 'budget_health_status'
>>

type BoardSupportable = Partial<Pick<ProjectBoardCardRecord, 'is_support' | 'project_type'>>

type BoardCurated = Partial<Pick<ProjectBoardCardRecord, 'curator_user_id'>>

type BoardActive = Partial<Pick<ProjectBoardCardRecord, 'last_writeoff_at' | 'last_writeoff_days'>>

type BoardBudgeted = Partial<Pick<
  ProjectBoardCardRecord,
  'budget_utilization_percent' | 'budget_health_status' | 'budget_utilization_mode'
  | 'planned_hours' | 'planned_amount' | 'project_hours_budget' | 'planned_budget_amount'
  | 'actual_cost_amount' | 'actual_hours'
>>

// --- Риск ---

/**
 * Сколько дней без списаний считаем риском.
 *
 * Та же граница, что у автостадии «Нет списаний 1 месяц» и что в таблице
 * проектов на главной (homeDashboard.ts::PROJECT_RISK_DAYS).
 */
export const BOARD_RISK_DAYS = 30

/** Статусы бюджета, при которых проект считается проблемным. */
const BOARD_RISK_BUDGET_STATUSES = new Set(['Риск', 'Перерасход', 'Минус'])

/**
 * Почему проект под риском — человеческим текстом, для подсказки на карточке.
 *
 * Признаков ДВА, и они независимы:
 *  - давно не списывают (автостадия ставится ночным заданием и может отстать
 *    на сутки, поэтому смотрим и на число дней, и на стадию);
 *  - бюджет в минусе.
 *
 * Отличие от главной осознанное: там «под риском» — только про неактивность,
 * потому что колонки бюджета в той таблице нет. На доске статус бюджета
 * нарисован на каждой карточке, и человек, нажавший «Под риском», ждёт, что
 * перерасход тоже попадёт в отбор.
 */
export function boardCardRiskReasons(card: BoardRiskable): string[] {
  const reasons: string[] = []
  const days = Number(card.last_writeoff_days || 0)
  const stage = String(card.stage || '')

  if (days >= BOARD_RISK_DAYS || stage.includes('Нет списаний')) {
    reasons.push(days > 0 ? `Нет списаний ${days} дн.` : 'Нет списаний')
  }

  const budgetStatus = String(card.budget_health_status || '').trim()
  if (BOARD_RISK_BUDGET_STATUSES.has(budgetStatus)) {
    reasons.push(budgetStatus === 'Риск' ? 'Бюджет на грани' : `Бюджет: ${budgetStatus.toLowerCase()}`)
  }

  return reasons
}

export function isBoardCardAtRisk(card: BoardRiskable): boolean {
  return boardCardRiskReasons(card).length > 0
}

export function isBoardCardMine(card: BoardCurated, currentUserId?: string | number | null): boolean {
  const userId = String(currentUserId ?? '').trim()

  if (!userId || userId === '0') {
    return false
  }

  return String(card.curator_user_id || '').trim() === userId
}

export function isBoardCardSupport(card: BoardSupportable): boolean {
  return Boolean(card.is_support || String(card.project_type || '').toLowerCase() === 'support')
}

// --- Фильтры ---

export type ProjectBoardSortId = 'name' | 'activity' | 'utilization' | 'budget'

export const PROJECT_BOARD_SORTS: Array<{ id: ProjectBoardSortId, label: string }> = [
  { id: 'name', label: 'По названию' },
  { id: 'activity', label: 'Сначала без списаний' },
  { id: 'utilization', label: 'По освоению бюджета' },
  { id: 'budget', label: 'По размеру бюджета' },
]

export type ProjectBoardProjectType = 'all' | 'support' | 'delivery'

export type ProjectBoardFilterState = {
  search: string
  curatorId: string
  companyId: string
  legalEntityId: string
  projectType: ProjectBoardProjectType
  onlyMine: boolean
  onlyRisk: boolean
  sort: ProjectBoardSortId
}

export const DEFAULT_PROJECT_BOARD_FILTERS: ProjectBoardFilterState = {
  search: '',
  curatorId: '',
  companyId: '',
  legalEntityId: '',
  projectType: 'all',
  onlyMine: false,
  onlyRisk: false,
  sort: 'name',
}

function readString(source: Record<string, unknown>, key: string): string {
  const value = source[key]
  return typeof value === 'string' || typeof value === 'number' ? String(value).trim() : ''
}

/** Разбор сохранённого набора: чужой и старый формат не должен ронять страницу. */
export function normalizeBoardFilters(raw: unknown): ProjectBoardFilterState {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ...DEFAULT_PROJECT_BOARD_FILTERS }
  }

  const source = raw as Record<string, unknown>
  const projectType = readString(source, 'projectType')
  const sort = readString(source, 'sort')

  return {
    search: readString(source, 'search'),
    curatorId: readString(source, 'curatorId'),
    companyId: readString(source, 'companyId'),
    legalEntityId: readString(source, 'legalEntityId'),
    projectType: projectType === 'support' || projectType === 'delivery' ? projectType : 'all',
    onlyMine: source.onlyMine === true,
    onlyRisk: source.onlyRisk === true,
    sort: PROJECT_BOARD_SORTS.some(item => item.id === sort) ? sort as ProjectBoardSortId : 'name',
  }
}

/**
 * Сколько фильтров сейчас включено.
 *
 * Число едет на кнопку «Сбросить»: без него человек не видит, что доска
 * показывает не всё, и решает, что проекты потерялись. Сортировка сюда не
 * входит — она ничего не прячет.
 */
export function countActiveBoardFilters(filters: ProjectBoardFilterState): number {
  let count = 0

  if (filters.search.trim()) count += 1
  if (filters.curatorId) count += 1
  if (filters.companyId) count += 1
  if (filters.legalEntityId) count += 1
  if (filters.projectType !== 'all') count += 1
  if (filters.onlyMine) count += 1
  if (filters.onlyRisk) count += 1

  return count
}

export function matchesBoardSearch(card: BoardSearchable, rawQuery: string): boolean {
  const query = String(rawQuery || '').trim().toLowerCase()

  if (!query) {
    return true
  }

  return [
    card.project_name,
    card.project_id,
    card.curator_name,
    card.company_name,
    card.company_inn,
    card.our_legal_entity_name,
    card.our_legal_entity_inn,
    card.stage,
  ].some(value => String(value || '').toLowerCase().includes(query))
}

export type ProjectBoardFilterContext = {
  currentUserId?: string | number | null
}

export function filterBoardCards(
  cards: ProjectBoardCardRecord[],
  filters: ProjectBoardFilterState,
  context?: ProjectBoardFilterContext
): ProjectBoardCardRecord[] {
  return (cards || []).filter((card) => {
    if (filters.projectType === 'support' && !isBoardCardSupport(card)) {
      return false
    }

    if (filters.projectType === 'delivery' && isBoardCardSupport(card)) {
      return false
    }

    if (filters.curatorId && String(card.curator_user_id || '') !== filters.curatorId) {
      return false
    }

    if (filters.companyId && String(card.company_id || '') !== filters.companyId) {
      return false
    }

    if (filters.legalEntityId && String(card.our_legal_entity_id || '') !== filters.legalEntityId) {
      return false
    }

    if (filters.onlyMine && !isBoardCardMine(card, context?.currentUserId)) {
      return false
    }

    if (filters.onlyRisk && !isBoardCardAtRisk(card)) {
      return false
    }

    return matchesBoardSearch(card, filters.search)
  })
}

function boardCardName(card: ProjectBoardCardRecord): string {
  return String(card.project_name || '')
}

function boardCardBudgetWeight(card: ProjectBoardCardRecord): number {
  const amount = Number(card.planned_amount ?? card.planned_budget_amount ?? 0)
  if (Number.isFinite(amount) && amount > 0) {
    return amount
  }

  const hours = Number(card.planned_hours ?? card.project_hours_budget ?? 0)
  const rate = Number(card.hourly_rate || 0)

  return Number.isFinite(hours) && hours > 0 ? hours * (Number.isFinite(rate) ? rate : 0) : 0
}

/**
 * Порядок карточек внутри колонки.
 *
 * Сортировка общая на всю доску, а не своя у каждой колонки: человек выбирает
 * «сначала без списаний» один раз и ждёт этого во всех стадиях сразу.
 * Карточки без нужного числа всегда уезжают вниз — иначе проект без бюджета
 * оказывался бы «самым освоенным».
 */
export function sortBoardCards(
  cards: ProjectBoardCardRecord[],
  sort: ProjectBoardSortId
): ProjectBoardCardRecord[] {
  const sorted = [...(cards || [])]

  switch (sort) {
    case 'activity':
      return sorted.sort((left, right) => {
        const diff = Number(right.last_writeoff_days || 0) - Number(left.last_writeoff_days || 0)
        return diff !== 0 ? diff : boardCardName(left).localeCompare(boardCardName(right), 'ru')
      })
    case 'utilization':
      return sorted.sort((left, right) => {
        const leftValue = Number(left.budget_utilization_percent)
        const rightValue = Number(right.budget_utilization_percent)
        const leftHas = Number.isFinite(leftValue)
        const rightHas = Number.isFinite(rightValue)

        if (leftHas && rightHas && leftValue !== rightValue) {
          return rightValue - leftValue
        }
        if (leftHas !== rightHas) {
          return leftHas ? -1 : 1
        }

        return boardCardName(left).localeCompare(boardCardName(right), 'ru')
      })
    case 'budget':
      return sorted.sort((left, right) => {
        const diff = boardCardBudgetWeight(right) - boardCardBudgetWeight(left)
        return diff !== 0 ? diff : boardCardName(left).localeCompare(boardCardName(right), 'ru')
      })
    default:
      return sorted.sort((left, right) => boardCardName(left).localeCompare(boardCardName(right), 'ru'))
  }
}

// --- Подписи ---

function roundHours(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.round(parsed) : 0
}

export function formatBoardHours(value?: number | null): string {
  return `${new Intl.NumberFormat('ru-RU').format(roundHours(value))} ч`
}

/**
 * Деньги на доске — короткой формой.
 *
 * В заголовок колонки шириной 260 px «1 240 000 ₽» не помещается, а точность
 * до рубля там и не нужна: это ориентир «сколько денег стоит в стадии».
 */
export function formatBoardMoneyShort(value?: number | null): string {
  const amount = Number(value)

  if (!Number.isFinite(amount) || amount === 0) {
    return '—'
  }

  const absolute = Math.abs(amount)
  const sign = amount < 0 ? '−' : ''

  if (absolute >= 1_000_000) {
    const millions = Math.round(absolute / 100_000) / 10
    return `${sign}${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(millions)} млн ₽`
  }

  if (absolute >= 10_000) {
    return `${sign}${new Intl.NumberFormat('ru-RU').format(Math.round(absolute / 1000))} тыс ₽`
  }

  return `${sign}${new Intl.NumberFormat('ru-RU').format(Math.round(absolute))} ₽`
}

/** «сегодня» / «вчера» / «34 дн.» — давность последнего списания. */
export function formatBoardActivity(card: BoardActive): string {
  if (!card.last_writeoff_at) {
    return 'Списаний нет'
  }

  const days = roundHours(card.last_writeoff_days)

  if (days <= 0) {
    return 'сегодня'
  }

  if (days === 1) {
    return 'вчера'
  }

  return `${days} дн.`
}

/** Инициалы куратора для кружка на карточке. */
export function buildBoardInitials(name?: string | null): string {
  const parts = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)

  if (parts.length === 0) {
    return '—'
  }

  const first = parts[0] as string
  const second = parts[1]

  return `${first.charAt(0)}${second ? second.charAt(0) : ''}`.toUpperCase()
}

const BOARD_AVATAR_TONES = [
  'bg-sky-100 text-sky-700',
  'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700',
  'bg-violet-100 text-violet-700',
  'bg-cyan-100 text-cyan-700',
  'bg-rose-100 text-rose-700',
] as const

/** Цвет кружка — по имени, чтобы один и тот же куратор всегда был одного цвета. */
export function getBoardAvatarToneClass(name?: string | null): string {
  const normalized = String(name || '').trim()
  const fallback = BOARD_AVATAR_TONES[BOARD_AVATAR_TONES.length - 1] as string

  if (!normalized) {
    return 'bg-slate-100 text-slate-500'
  }

  const hash = Array.from(normalized).reduce((acc, char) => acc + char.charCodeAt(0), 0)

  return BOARD_AVATAR_TONES[hash % BOARD_AVATAR_TONES.length] || fallback
}

const BOARD_STAGE_DOTS: Record<string, string> = {
  'Новый': 'bg-sky-400',
  'В просчете': 'bg-amber-400',
  'В работе': 'bg-emerald-500',
  'Нет списаний 1 месяц': 'bg-orange-400',
  'Нет списаний 3 месяца': 'bg-rose-500',
  'Успех': 'bg-emerald-600',
  'Провал': 'bg-slate-400',
}

export function getBoardStageDotClass(stage?: string | null): string {
  return BOARD_STAGE_DOTS[String(stage || '').trim()] || 'bg-slate-300'
}

// --- Освоение бюджета на карточке ---

export type BoardUtilization = {
  /** Ширина полосы, 0–100. Перерасход упирается в 100 и красится отдельно. */
  barPercent: number
  /** «312/400 ч» или «180/250 тыс ₽» — факт и план одной подписью. */
  label: string
  tone: 'neutral' | 'warning' | 'danger'
  /** Полосы нет: бюджет не задан, показываем только факт. */
  isEmpty: boolean
}

/**
 * Освоение для компактной карточки.
 *
 * Пустая полоса у проекта без бюджета читается как «ноль освоения», а это
 * неправда, поэтому в таком случае полосы нет вовсе — только фактические часы.
 * Режим (часы или деньги) берём у бэкенда: он же считает и процент.
 */
export function buildBoardUtilization(card: BoardBudgeted): BoardUtilization {
  const percentValue = Number(card.budget_utilization_percent)
  const hasPercent = Number.isFinite(percentValue)
  const status = String(card.budget_health_status || '').trim()
  const tone: BoardUtilization['tone'] = status === 'Перерасход' || status === 'Минус'
    ? 'danger'
    : status === 'Риск' || status === 'Граница'
      ? 'warning'
      : 'neutral'

  const mode = String(card.budget_utilization_mode || '')
  const plannedHours = Number(card.planned_hours ?? card.project_hours_budget)
  const plannedAmount = Number(card.planned_amount ?? card.planned_budget_amount)

  if (mode === 'amount' && Number.isFinite(plannedAmount) && plannedAmount > 0) {
    return {
      barPercent: hasPercent ? Math.max(0, Math.min(percentValue, 100)) : 0,
      label: `${formatBoardMoneyShort(card.actual_cost_amount)} из ${formatBoardMoneyShort(plannedAmount)}`,
      tone,
      isEmpty: false,
    }
  }

  if (Number.isFinite(plannedHours) && plannedHours > 0) {
    return {
      barPercent: hasPercent ? Math.max(0, Math.min(percentValue, 100)) : 0,
      label: `${new Intl.NumberFormat('ru-RU').format(roundHours(card.actual_hours))} из ${formatBoardHours(plannedHours)}`,
      tone,
      isEmpty: false,
    }
  }

  return {
    barPercent: 0,
    label: `${formatBoardHours(card.actual_hours)} без лимита`,
    tone: 'neutral',
    isEmpty: true,
  }
}

// --- Колонки ---

export type ProjectBoardColumnStats = {
  count: number
  riskCount: number
  actualHours: number
  plannedHours: number
  plannedAmount: number
  /** «312/400 ч · 1,2 млн ₽» — что стоит в стадии, одной строкой под заголовком. */
  summaryLabel: string
}

export type ProjectBoardColumnModel = {
  id: string
  title: string
  kind: string
  canDrop: boolean
  dotClass: string
  cards: ProjectBoardCardRecord[]
  stats: ProjectBoardColumnStats
}

export function buildBoardColumnStats(cards: ProjectBoardCardRecord[]): ProjectBoardColumnStats {
  const list = cards || []
  let actualHours = 0
  let plannedHours = 0
  let plannedAmount = 0
  let riskCount = 0

  for (const card of list) {
    actualHours += Number(card.actual_hours) || 0

    const cardPlannedHours = Number(card.planned_hours ?? card.project_hours_budget)
    if (Number.isFinite(cardPlannedHours) && cardPlannedHours > 0) {
      plannedHours += cardPlannedHours
    }

    const cardPlannedAmount = Number(card.planned_amount ?? card.planned_budget_amount)
    if (Number.isFinite(cardPlannedAmount) && cardPlannedAmount > 0) {
      plannedAmount += cardPlannedAmount
    }

    if (isBoardCardAtRisk(card)) {
      riskCount += 1
    }
  }

  const parts: string[] = []

  if (plannedHours > 0) {
    parts.push(`${new Intl.NumberFormat('ru-RU').format(roundHours(actualHours))}/${formatBoardHours(plannedHours)}`)
  } else if (actualHours > 0) {
    parts.push(formatBoardHours(actualHours))
  }

  if (plannedAmount > 0) {
    parts.push(formatBoardMoneyShort(plannedAmount))
  }

  return {
    count: list.length,
    riskCount,
    actualHours,
    plannedHours,
    plannedAmount,
    summaryLabel: parts.join(' · '),
  }
}

/**
 * Колонки доски.
 *
 * Стадию карточки сопоставляем и с id, и с заголовком стадии: бэкенд отдаёт
 * стадии словарём, где id и title у части стадий совпадают, а у части — нет
 * (так было и до редизайна, ломать это нельзя).
 */
export function buildBoardColumns(
  stages: ProjectBoardResponse['stages'],
  cards: ProjectBoardCardRecord[],
  sort: ProjectBoardSortId = 'name'
): ProjectBoardColumnModel[] {
  return (stages || []).map((stage) => {
    const stageCards = sortBoardCards(
      (cards || []).filter(card => card.stage === stage.title || card.stage === stage.id),
      sort
    )

    return {
      id: String(stage.id),
      title: String(stage.title),
      kind: String(stage.kind || ''),
      canDrop: Boolean(stage.can_drop),
      dotClass: getBoardStageDotClass(stage.title),
      cards: stageCards,
      stats: buildBoardColumnStats(stageCards),
    }
  })
}

// --- Хранение выбранных фильтров ---

/**
 * Фильтры доски запоминаем в localStorage браузера.
 *
 * Причина та же, что у пресетов отчётов (utils/reportFilterPresets.ts):
 * серверного места под пользовательские настройки в приложении нет, а
 * заводить ради этого эндпоинт — менять бэкенд. Ключ включает портал и
 * пользователя: один браузер открывает демостенд, дев и боевой портал, где
 * ID кураторов и компаний разные, и общий ключ молча фильтровал бы доску по
 * чужим ID.
 */
export const PROJECT_BOARD_VIEW_STORAGE_PREFIX = 'ms-project-board-view-v1'

export function buildBoardViewStorageKey(scope: {
  portal?: string | null
  userId?: string | number | null
}): string {
  const portal = String(scope.portal || '')
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/\/+$/, '')
  const userId = String(scope.userId ?? '').trim()

  return `${PROJECT_BOARD_VIEW_STORAGE_PREFIX}:${portal || 'unknown'}:${userId || 'unknown'}`
}

export type ProjectBoardView = 'board' | 'timeline' | 'archive'

export type ProjectBoardViewState = {
  view: ProjectBoardView
  filters: ProjectBoardFilterState
}

export const DEFAULT_PROJECT_BOARD_VIEW_STATE: ProjectBoardViewState = {
  view: 'board',
  filters: DEFAULT_PROJECT_BOARD_FILTERS,
}

export function serializeBoardViewState(state: ProjectBoardViewState): string {
  return JSON.stringify({
    view: state.view,
    filters: state.filters,
  })
}

/** Разбор сохранённого состояния. Любой мусор в хранилище — это состояние по умолчанию, а не падение. */
export function parseBoardViewState(raw: string | null | undefined): ProjectBoardViewState {
  if (!raw) {
    return { view: 'board', filters: { ...DEFAULT_PROJECT_BOARD_FILTERS } }
  }

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const view = String(parsed?.view || '')

    return {
      view: view === 'timeline' || view === 'archive' ? view : 'board',
      filters: normalizeBoardFilters(parsed?.filters),
    }
  } catch {
    return { view: 'board', filters: { ...DEFAULT_PROJECT_BOARD_FILTERS } }
  }
}

// --- Пустые состояния ---

export type BoardEmptyState = {
  title: string
  hint: string
  /** Показать кнопку «Синхронизировать»: проектов нет вообще, их нужно забрать из Битрикса. */
  showSync: boolean
  /** Показать кнопку «Сбросить фильтры»: проекты есть, но их спрятал отбор. */
  showReset: boolean
}

/**
 * Что написать вместо доски, когда показывать нечего.
 *
 * Причины «пусто» разные, и один общий текст на все случаи врёт как минимум в
 * двух из них: «сбросьте фильтры» при пустых фильтрах отправляет человека
 * искать несуществующую причину, а «синхронизируйте» при живых 40 проектах,
 * спрятанных отбором, толкает лишний раз тратить лимит синхронизации.
 * Поэтому состояние вычисляется явно и проверено тестами.
 */
export function buildBoardEmptyState(params: {
  view: ProjectBoardView
  /** Всего карточек на доске, вместе с архивом. */
  totalCards: number
  /** Сколько видно сейчас, после фильтров. */
  visibleCount: number
  /** Сколько всего в этом виде (активные или архивные) без учёта фильтров. */
  scopeCount: number
  activeFilters: number
}): BoardEmptyState | null {
  if (params.visibleCount > 0) {
    return null
  }

  if (params.totalCards === 0) {
    return {
      title: 'Доска пока пустая',
      hint: 'Проекты приезжают из рабочих групп и смарт-процесса Битрикс24. Нажмите «Синхронизировать» — приложение заберёт их и разложит по стадиям.',
      showSync: true,
      showReset: false,
    }
  }

  if (params.activeFilters > 0) {
    return {
      title: 'Под выбранные фильтры проектов нет',
      hint: params.view === 'archive'
        ? `Всего в архиве: ${params.scopeCount}. Снимите отбор — и проекты вернутся.`
        : `Всего активных проектов: ${params.scopeCount}. Снимите отбор — и доска вернётся.`,
      showSync: false,
      showReset: true,
    }
  }

  if (params.view === 'archive') {
    return {
      title: 'В архиве пусто',
      hint: 'Сюда попадают проекты, отправленные в архив из карточки проекта.',
      showSync: false,
      showReset: false,
    }
  }

  return {
    title: 'Активных проектов нет',
    hint: 'Все проекты отправлены в архив. Загляните во вкладку «Архив» или создайте новый проект.',
    showSync: false,
    showReset: false,
  }
}
