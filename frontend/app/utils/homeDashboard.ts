/**
 * Главная страница: показатели месяца и таблица проектов.
 *
 * Раньше главная была набором плиток-кнопок: она отвечала на вопрос «куда
 * пойти», но не отвечала ни на один вопрос про работу. Меню разделов взяло
 * навигацию на себя, и место освободилось под то, ради чего приложение вообще
 * открывают, — сколько часов в месяце и что с проектами.
 *
 * Цифры берутся ТОЛЬКО из того, что уже отдают существующие ручки:
 *  - показатели месяца — из `/api/periods/check` (PeriodCheckResult.stats),
 *    там же лежат находки проверки;
 *  - таблица проектов — из `/api/homepage-portfolio` (карточки доски).
 * Ничего, что пришлось бы досчитывать на сервере, здесь нет и быть не должно:
 * выдуманный показатель дороже отсутствующего.
 */

import type { PeriodCheckResult, PeriodRow } from '../types/period'
import type { ProjectBoardCardRecord, ProjectBoardSummary } from '../types/project-board'

export type HomeMetricTone = 'neutral' | 'success' | 'warning' | 'danger'

export type HomeMetric = {
  id: string
  label: string
  /** Уже отформатированное значение — карточка его только печатает. */
  value: string
  hint: string
  tone: HomeMetricTone
  /**
   * Значение печатается бейджем, а не крупной цифрой.
   *
   * Статус закрытия месяца — не число: «Август закрыт» крупным шрифтом в ряду
   * с «842 ч» читается как поломка вёрстки. В макете это именно бейдж.
   */
  asBadge?: boolean
}

const MONTH_NAMES = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]

/** Значение для `<input type="month">` из даты. */
export function formatMonthValue(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')

  return `${year}-${month}`
}

/**
 * Разбор значения `<input type="month">`.
 *
 * Пустое или кривое значение — не ошибка: поле можно очистить, и падать из-за
 * этого нельзя. Возвращаем null, а вызывающий сам решает, что показать.
 */
export function parseMonthValue(value: string | null | undefined): { year: number, month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value || '').trim())

  if (!match) {
    return null
  }

  const year = Number(match[1])
  const month = Number(match[2])

  if (!Number.isFinite(year) || month < 1 || month > 12) {
    return null
  }

  return { year, month }
}

export function formatMonthTitle(value: string | null | undefined): string {
  const parsed = parseMonthValue(value)

  if (!parsed) {
    return 'Месяц не выбран'
  }

  return `${MONTH_NAMES[parsed.month - 1]} ${parsed.year}`
}

/** Часы печатаем с одним знаком: половинки часа в учёте обычное дело. */
export function formatHours(value: number | null | undefined): string {
  const hours = Number(value || 0)

  if (!Number.isFinite(hours)) {
    return '0'
  }

  return (Math.round(hours * 10) / 10).toLocaleString('ru-RU')
}

export function formatCount(value: number | null | undefined): string {
  const count = Number(value || 0)

  return Number.isFinite(count) ? Math.trunc(count).toLocaleString('ru-RU') : '0'
}

/**
 * Находки проверки месяца: блокеры плюс предупреждения.
 *
 * Считаем НАХОДКИ, а не записи за ними: «3 находки» — это то, что человек
 * может разобрать за раз, а «412 записей» пугает и не говорит, с чего начать.
 */
export function countPeriodFindings(check: PeriodCheckResult | null | undefined): number {
  if (!check) {
    return 0
  }

  return (check.blockers?.length || 0) + (check.warnings?.length || 0)
}

/** Блокеры — то, из-за чего месяц нельзя закрыть. Именно их показывает счётчик в меню. */
export function countPeriodBlockers(check: PeriodCheckResult | null | undefined): number {
  return check?.blockers?.length || 0
}

/** Дата закрытия в коротком виде: «02.09». Пустая строка, если даты нет. */
export function formatShortDate(value: string | null | undefined): string {
  const raw = String(value || '').trim()

  if (!raw) {
    return ''
  }

  const parsed = new Date(raw)

  if (Number.isNaN(parsed.getTime())) {
    return ''
  }

  return parsed.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

/**
 * Строка журнала закрытия за выбранный месяц.
 *
 * `/api/periods` отдаёт ВСЕ месяцы разом, отдельной ручки «статус одного
 * месяца» нет. Поэтому выбираем нужный здесь, а не просим у сервера.
 */
export function findPeriodRow(
  rows: PeriodRow[] | null | undefined,
  month: { year: number, month: number } | null
): PeriodRow | null {
  if (!month) {
    return null
  }

  return (rows || []).find(row => row.year === month.year && row.month === month.month) || null
}

export type HomeMetricsInput = {
  /** Ответ `/api/periods/check` за выбранный месяц. */
  check?: PeriodCheckResult | null
  /** Строка журнала `/api/periods` за тот же месяц. */
  period?: PeriodRow | null
  /** Журнал закрытия уже отвечал: null в `period` тогда значит «месяц не закрывали». */
  periodsLoaded?: boolean
  /** Сводка `/api/homepage/portfolio`. */
  portfolio?: ProjectBoardSummary | null
}

/**
 * Четыре показателя выбранного месяца — по макету «вариант A».
 *
 * В макете это «часы», «учтённость», «без списаний 30+ дней» и «статус
 * закрытия месяца». Три из четырёх собираются из того, что уже отдают ручки;
 * УЧТЁННОСТИ среди них нет: деление часов на учтённые и неучтённые считает
 * только отчёт по проектам и задачам, за период и с фильтрами, и на главной
 * его пришлось бы либо гонять целиком, либо заводить новую ручку — то есть
 * менять бэкенд. Вместо неё в этом месте стоят находки проверки месяца: это
 * тоже показатель «всё ли в порядке за месяц», и он уже посчитан. Выдуманный
 * показатель дороже отсутствующего.
 *
 * Проверка ещё не ответила — показываем прочерки, а не нули: ноль часов и
 * «мы пока не знаем» для человека означают противоположное.
 */
export function buildHomeMetrics(input?: HomeMetricsInput | PeriodCheckResult | null): HomeMetric[] {
  // Старый вызов передавал сюда сам результат проверки. Оставлено ради вызовов,
  // которым портфель и журнал закрытия не нужны.
  const normalized: HomeMetricsInput = input && 'stats' in (input as PeriodCheckResult)
    ? { check: input as PeriodCheckResult }
    : ((input || {}) as HomeMetricsInput)

  const check = normalized.check
  const stats = check?.stats
  const portfolio = normalized.portfolio
  const period = normalized.period
  const blockers = countPeriodBlockers(check)
  const findings = countPeriodFindings(check)
  const dash = '—'

  const inactive30 = portfolio ? Math.max(0, Number(portfolio.inactive_30_count || 0)) : null
  const inactive90 = portfolio ? Math.max(0, Number(portfolio.inactive_90_count || 0)) : null

  return [
    {
      id: 'hours',
      label: 'Часов за месяц',
      value: stats ? formatHours(stats.hours) : dash,
      hint: stats
        ? `${formatCount(stats.entries)} записей · ${formatCount(stats.employees)} сотрудников`
        : 'Отражено в выбранном месяце',
      tone: 'neutral',
    },
    {
      id: 'findings',
      label: 'Находок проверки',
      value: check ? formatCount(findings) : dash,
      hint: blockers > 0
        ? `Из них мешают закрыть месяц: ${formatCount(blockers)}`
        : 'Закрытию месяца ничего не мешает',
      tone: blockers > 0 ? 'danger' : findings > 0 ? 'warning' : 'neutral',
    },
    {
      id: 'inactive',
      label: 'Без списаний 30+ дней',
      value: inactive30 === null ? dash : formatCount(inactive30),
      hint: inactive90 === null
        ? 'Проектов, по которым давно не списывали'
        : inactive90 > 0
          ? `Из них 90+ дней: ${formatCount(inactive90)}`
          : 'Проектов старше 90 дней нет',
      tone: inactive90 && inactive90 > 0 ? 'danger' : inactive30 && inactive30 > 0 ? 'warning' : 'neutral',
    },
    buildMonthClosingMetric(period, normalized.periodsLoaded === true, check),
  ]
}

/**
 * Статус закрытия месяца.
 *
 * Отдельная функция, потому что это единственный показатель, у которого
 * значение — не число, а состояние: «закрыт», «открыт», «переоткрыт».
 * Отличать «журнал ещё не ответил» от «месяц не закрывали» обязательно:
 * во втором случае прочерк соврал бы про закрытый месяц.
 */
export function buildMonthClosingMetric(
  period: PeriodRow | null | undefined,
  periodsLoaded: boolean,
  check?: PeriodCheckResult | null
): HomeMetric {
  if (!periodsLoaded) {
    return {
      id: 'closing',
      label: 'Закрытие месяца',
      value: '—',
      hint: 'Журнал закрытия ещё не ответил',
      tone: 'neutral',
      asBadge: true,
    }
  }

  if (period?.closed) {
    const closedAt = formatShortDate(period.closed_at)
    const lateHours = Number(period.late_arrivals || 0)
    const lateText = lateHours > 0
      ? `после закрытия пришло ${formatHours(lateHours)} ч`
      : 'после закрытия записей не приходило'

    return {
      id: 'closing',
      label: 'Закрытие месяца',
      value: 'Месяц закрыт',
      hint: closedAt ? `${closedAt} · ${lateText}` : lateText,
      tone: 'success',
      asBadge: true,
    }
  }

  const blockers = countPeriodBlockers(check)

  if (period?.reopened_at) {
    return {
      id: 'closing',
      label: 'Закрытие месяца',
      value: 'Переоткрыт',
      hint: period.reopen_reason
        ? `Причина: ${period.reopen_reason}`
        : `Переоткрыт ${formatShortDate(period.reopened_at) || 'позже'}`,
      tone: 'warning',
      asBadge: true,
    }
  }

  return {
    id: 'closing',
    label: 'Закрытие месяца',
    value: 'Месяц открыт',
    hint: blockers > 0
      ? `Закрыть мешают находки: ${formatCount(blockers)}`
      : 'Часы за месяц ещё можно править',
    tone: blockers > 0 ? 'danger' : 'neutral',
    asBadge: true,
  }
}

export type ProjectRow = {
  id: string
  name: string
  companyName: string
  curatorName: string
  /** Нужен быстрому фильтру «Мои»: имя куратора для этого ненадёжно. */
  curatorUserId: string
  stage: string
  lastWriteoffDays: number
  actualHours: number
  plannedHours: number | null
  hourlyRate: number
  actualCostAmount: number
  /** Освоение бюджета, %. null — бюджета нет, полосу рисовать не от чего. */
  utilizationPercent: number | null
  hoursBudget: string
  legalEntityName: string
  isSupport: boolean
  card: ProjectBoardCardRecord
}

function textOrDash(value: unknown, fallback: string): string {
  const text = String(value ?? '').trim()

  return text || fallback
}

export function buildProjectRows(cards: ProjectBoardCardRecord[] | null | undefined): ProjectRow[] {
  return (cards || [])
    .filter(card => !card.is_archived)
    .map(card => ({
      id: String(card.project_id),
      name: textOrDash(card.project_name, `Проект ${card.project_id}`),
      companyName: textOrDash(card.company_name, 'Компания не указана'),
      curatorName: textOrDash(card.curator_name, 'Куратор не указан'),
      curatorUserId: String(card.curator_user_id || '').trim(),
      stage: textOrDash(card.stage, 'Без стадии'),
      lastWriteoffDays: Number(card.last_writeoff_days || 0),
      actualHours: Number(card.actual_hours || 0),
      plannedHours: card.planned_hours === null || card.planned_hours === undefined
        ? null
        : Number(card.planned_hours),
      hourlyRate: Number(card.hourly_rate || 0),
      actualCostAmount: Number(card.actual_cost_amount || 0),
      // Осторожно с Number(null): это 0, а не NaN, и «бюджета нет» превратилось бы
      // в «освоено 0%» — то есть в полосу там, где полосе взяться неоткуда.
      utilizationPercent: card.budget_utilization_percent === null
        || card.budget_utilization_percent === undefined
        || !Number.isFinite(Number(card.budget_utilization_percent))
        ? null
        : Number(card.budget_utilization_percent),
      hoursBudget: textOrDash(card.project_hours_budget, 'поддержка'),
      legalEntityName: textOrDash(card.our_legal_entity_name, 'Не указано'),
      isSupport: card.is_support === true || String(card.project_type || '') === 'support',
      card,
    }))
}

/**
 * Быстрый фильтр таблицы.
 *
 * Ищем по всему, что человек видит в строке, плюс по идентификатору проекта:
 * ID в таблице не показан, но его приносят из Битрикса в переписке, и искать
 * по нему приходится чаще, чем кажется.
 */
export function filterProjectRows(rows: ProjectRow[], query: string | null | undefined): ProjectRow[] {
  const needle = String(query || '').trim().toLowerCase()

  if (!needle) {
    return rows
  }

  return rows.filter(row => [
    row.name,
    row.companyName,
    row.curatorName,
    row.stage,
    row.legalEntityName,
    row.id,
  ].some(value => value.toLowerCase().includes(needle)))
}

export type ProjectSortKey = 'name' | 'stage' | 'lastWriteoffDays' | 'actualHours' | 'hourlyRate'

/**
 * Сортировка таблицы.
 *
 * По умолчанию сверху лежат самые «молчащие» проекты — те, по которым дольше
 * всех не было списаний: это и есть то, ради чего на таблицу смотрят.
 */
export function sortProjectRows(
  rows: ProjectRow[],
  key: ProjectSortKey = 'lastWriteoffDays',
  direction: 'asc' | 'desc' = 'desc'
): ProjectRow[] {
  const sign = direction === 'asc' ? 1 : -1

  return [...rows].sort((left, right) => {
    const leftValue = left[key]
    const rightValue = right[key]

    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return (leftValue - rightValue) * sign
    }

    return String(leftValue).localeCompare(String(rightValue), 'ru') * sign
  })
}

// --- Быстрые фильтры таблицы проектов ---

export type ProjectQuickFilterId = 'active' | 'support' | 'risk' | 'mine'

export type ProjectQuickFilter = {
  id: ProjectQuickFilterId
  label: string
}

/**
 * Быстрые фильтры над таблицей проектов — по макету «вариант A».
 *
 * Ровно четыре: больше в одну строку с полем поиска не влезает, а пятый
 * («архив») здесь бессмыслен — архивные проекты в таблицу не попадают вовсе
 * (см. buildProjectRows).
 */
export const PROJECT_QUICK_FILTERS: ProjectQuickFilter[] = [
  { id: 'active', label: 'Активные' },
  { id: 'support', label: 'Поддержка' },
  { id: 'risk', label: 'Под риском' },
  { id: 'mine', label: 'Мои' },
]

/** Сколько дней без списаний считаем риском. Та же граница, что у стадии «Нет списаний 1 месяц». */
export const PROJECT_RISK_DAYS = 30

export type ProjectQuickFilterContext = {
  /** ID текущего пользователя портала — для фильтра «Мои». */
  currentUserId?: string | number | null
}

/**
 * Проект «под риском».
 *
 * Считаем по двум признакам сразу: автостадия «Нет списаний…» ставится ночным
 * заданием и может отстать на сутки, а число дней приходит из той же карточки
 * и всегда свежее.
 */
export function isProjectAtRisk(row: ProjectRow): boolean {
  return row.lastWriteoffDays >= PROJECT_RISK_DAYS || row.stage.includes('Нет списаний')
}

export function isProjectMine(row: ProjectRow, context?: ProjectQuickFilterContext): boolean {
  const currentUserId = String(context?.currentUserId ?? '').trim()

  return currentUserId !== '' && row.curatorUserId === currentUserId
}

export function matchesProjectQuickFilter(
  row: ProjectRow,
  filterId: ProjectQuickFilterId,
  context?: ProjectQuickFilterContext
): boolean {
  switch (filterId) {
    case 'support':
      return row.isSupport
    case 'risk':
      return isProjectAtRisk(row)
    case 'mine':
      return isProjectMine(row, context)
    default:
      return true
  }
}

export function applyProjectQuickFilter(
  rows: ProjectRow[],
  filterId: ProjectQuickFilterId,
  context?: ProjectQuickFilterContext
): ProjectRow[] {
  if (filterId === 'active') {
    return rows
  }

  return rows.filter(row => matchesProjectQuickFilter(row, filterId, context))
}

/** Числа на чипах. Считаем от полного списка, а не от отфильтрованного: иначе счётчики обнулялись бы сами о себя. */
export function countProjectQuickFilters(
  rows: ProjectRow[],
  context?: ProjectQuickFilterContext
): Record<ProjectQuickFilterId, number> {
  return {
    active: rows.length,
    support: rows.filter(row => matchesProjectQuickFilter(row, 'support', context)).length,
    risk: rows.filter(row => matchesProjectQuickFilter(row, 'risk', context)).length,
    mine: rows.filter(row => matchesProjectQuickFilter(row, 'mine', context)).length,
  }
}

// --- Панель выбранного проекта ---

/**
 * Строка, о которой рассказывает боковая панель.
 *
 * Подстановки «первой строки списка» здесь намеренно нет. Пока панель была
 * колонкой макета, пустое место справа читалось как поломка, и панель
 * подставляла первый проект отбора. Теперь панель открывается поверх
 * содержимого по клику — показать в ней не тот проект, который открыли,
 * значит подменить сотруднику карточку у него под руками. Если выбранный
 * проект выпал из отбора, панели просто нечего показывать и она закрывается.
 */
export function findProjectRowById(
  rows: ProjectRow[] | null | undefined,
  id: string | null | undefined
): ProjectRow | null {
  const needle = String(id || '').trim()

  if (!needle) {
    return null
  }

  return (rows || []).find(row => row.id === needle) || null
}

/**
 * Цвет бейджа стадии.
 *
 * Живёт в утилитах, потому что стадию рисуют двое — строка таблицы на главной
 * и боковая панель проекта, — и раскраска у них обязана совпадать.
 * Автоматические стадии («нет списаний…») важнее ручных: именно они сообщают
 * о проблеме, поэтому проверяются первыми.
 */
export function getProjectStageClass(stage: string | null | undefined): string {
  const normalized = String(stage || '')

  if (normalized.includes('Нет списаний 3 месяца')) {
    return 'bg-rose-100 text-rose-700'
  }

  if (normalized.includes('Нет списаний 1 месяц')) {
    return 'bg-amber-100 text-amber-700'
  }

  if (normalized.includes('В просчете')) {
    return 'bg-indigo-100 text-indigo-700'
  }

  if (normalized.includes('В работе')) {
    return 'bg-emerald-100 text-emerald-700'
  }

  return 'bg-slate-100 text-slate-700'
}

export type ProjectPanelStat = {
  id: string
  label: string
  value: string
}

export type ProjectPanel = {
  id: string
  name: string
  stage: string
  /** «ООО «Северный ветер» · куратор Анна Воронцова» — одной строкой, как в макете. */
  subtitle: string
  stats: ProjectPanelStat[]
}

/** Деньги печатаем целыми рублями: копейки в панели проекта ничего не решают. */
export function formatMoney(value: number | null | undefined): string {
  const amount = Number(value || 0)

  if (!Number.isFinite(amount)) {
    return '0 ₽'
  }

  return `${Math.round(amount).toLocaleString('ru-RU')} ₽`
}

/**
 * Боковая панель выбранного проекта — по макету «вариант A».
 *
 * Все четыре показателя берутся из той же карточки доски, что и строка
 * таблицы: отдельного запроса панель не делает, поэтому выбор проекта
 * мгновенный и не зависит от сети.
 */
export function buildProjectPanel(row: ProjectRow | null | undefined): ProjectPanel | null {
  if (!row) {
    return null
  }

  const budget = row.plannedHours && row.plannedHours > 0
    ? `${formatHours(row.plannedHours)} / ${formatHours(row.actualHours)} ч`
    : `${formatHours(row.actualHours)} ч (без плана)`

  return {
    id: row.id,
    name: row.name,
    stage: row.stage,
    subtitle: `${row.companyName} · куратор ${row.curatorName}`,
    stats: [
      { id: 'budget', label: 'Бюджет / факт', value: budget },
      { id: 'rate', label: 'Ставка', value: row.hourlyRate > 0 ? `${formatMoney(row.hourlyRate)}/ч` : 'не задана' },
      { id: 'amount', label: 'Факт, ₽', value: formatMoney(row.actualCostAmount) },
      { id: 'legal-entity', label: 'Наше юрлицо', value: row.legalEntityName },
    ],
  }
}

// --- Ячейки таблицы проектов ---

/**
 * Когда списывали в последний раз.
 *
 * «Сегодня» и «вчера» словами: в колонке, где всё остальное — числа, именно
 * свежие проекты должны читаться без арифметики в голове.
 */
export function formatLastWriteoff(days: number | null | undefined): string {
  const value = Math.max(0, Math.trunc(Number(days || 0)))

  if (!Number.isFinite(value)) {
    return '—'
  }

  if (value === 0) {
    return 'сегодня'
  }

  if (value === 1) {
    return 'вчера'
  }

  return `${formatCount(value)} дн.`
}

export type ProjectUtilization = {
  /** Ширина полосы, 0–100. Перерасход упирается в 100 и красится отдельно. */
  barPercent: number
  label: string
  tone: 'neutral' | 'warning' | 'danger'
  /** Полосы нет: у проекта нет бюджета, показываем только часы. */
  isEmpty: boolean
}

/**
 * Освоение бюджета для колонки таблицы.
 *
 * Бюджета может не быть вовсе (поддержка) — тогда вместо полосы печатаем
 * фактические часы: пустая полоса читалась бы как «ноль освоения», а это
 * неправда.
 */
export function buildProjectUtilization(row: ProjectRow): ProjectUtilization {
  const percent = row.utilizationPercent

  if (percent === null) {
    return {
      barPercent: 0,
      label: `${formatHours(row.actualHours)} ч`,
      tone: 'neutral',
      isEmpty: true,
    }
  }

  const rounded = Math.round(percent)

  return {
    barPercent: Math.max(0, Math.min(100, rounded)),
    label: `${formatCount(rounded)}%`,
    tone: rounded > 100 ? 'danger' : rounded >= 80 ? 'warning' : 'neutral',
    isEmpty: false,
  }
}

/** Инициалы для кружка куратора: «Анна Воронцова» → «АВ». */
export function initialsOf(name: string | null | undefined): string {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)

  if (!parts.length) {
    return '—'
  }

  return parts.slice(0, 2).map(part => part[0].toUpperCase()).join('')
}
