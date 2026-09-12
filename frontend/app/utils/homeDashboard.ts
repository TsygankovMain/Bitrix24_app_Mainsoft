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

import type { PeriodCheckResult } from '../types/period'
import type { ProjectBoardCardRecord } from '../types/project-board'

export type HomeMetricTone = 'neutral' | 'warning' | 'danger'

export type HomeMetric = {
  id: string
  label: string
  /** Уже отформатированное значение — карточка его только печатает. */
  value: string
  hint: string
  tone: HomeMetricTone
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

/**
 * Четыре показателя месяца.
 *
 * Проверка ещё не ответила — показываем прочерки, а не нули: ноль часов и
 * «мы пока не знаем» для человека означают противоположное.
 */
export function buildHomeMetrics(check: PeriodCheckResult | null | undefined): HomeMetric[] {
  const stats = check?.stats
  const blockers = countPeriodBlockers(check)
  const findings = countPeriodFindings(check)
  const dash = '—'

  return [
    {
      id: 'hours',
      label: 'Часов за месяц',
      value: stats ? formatHours(stats.hours) : dash,
      hint: 'Отражено в выбранном месяце',
      tone: 'neutral',
    },
    {
      id: 'entries',
      label: 'Записей',
      value: stats ? formatCount(stats.entries) : dash,
      hint: 'Строк учёта за месяц',
      tone: 'neutral',
    },
    {
      id: 'employees',
      label: 'Сотрудников списали',
      value: stats ? formatCount(stats.employees) : dash,
      hint: 'Внесли хотя бы один час',
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
  ]
}

export type ProjectRow = {
  id: string
  name: string
  companyName: string
  curatorName: string
  stage: string
  lastWriteoffDays: number
  actualHours: number
  hourlyRate: number
  hoursBudget: string
  legalEntityName: string
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
      stage: textOrDash(card.stage, 'Без стадии'),
      lastWriteoffDays: Number(card.last_writeoff_days || 0),
      actualHours: Number(card.actual_hours || 0),
      hourlyRate: Number(card.hourly_rate || 0),
      hoursBudget: textOrDash(card.project_hours_budget, 'поддержка'),
      legalEntityName: textOrDash(card.our_legal_entity_name, 'Не указано'),
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
