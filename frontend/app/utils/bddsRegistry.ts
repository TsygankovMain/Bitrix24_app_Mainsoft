/**
 * Модель экранов БДДС: чипы, фильтр, показатели, тексты статуса и прогноза.
 *
 * Здесь только ЧИСТЫЕ функции. Компоненты (pages/finance/bdds/**) рисуют то,
 * что вернули эти функции, и сами ничего не считают: node:test через tsx не
 * резолвит .vue, и логика, оставшаяся внутри компонента, ревью не проходит
 * (урок формы «Создать проект», см. featureFlags.ts).
 *
 * ИМЕНА С ПРЕФИКСОМ bdds. Nuxt автоимпортирует всё из app/utils, и
 * совпадение имён с projectBoard.ts / projectBoardView.ts / homeDashboard.ts
 * даёт предупреждение сборки «Duplicated imports» и молча выигрывающий
 * чужой экспорт.
 *
 * Утилиты доски (полоса освоения, поиск, давность списаний) НЕ копируются:
 * строка реестра — та же карточка проекта, и её рисуют те же функции
 * (buildBoardUtilization, matchesBoardSearch, formatBoardActivity).
 */

import { formatProjectCurrency, formatProjectDate, formatProjectHours, formatProjectPercent } from './projectBoard'
import { matchesBoardSearch } from './projectBoardView'
import type { BddsNotifierRunResult, BddsProjectRecord, BddsThresholds, BddsTotals } from '~/types/bdds'

// --- Статусы ---------------------------------------------------------------

export type BddsStatusTone = 'ok' | 'warning' | 'danger' | 'neutral'

/**
 * Цветовая зона статуса.
 *
 * «Граница» у поддержки — жёлтая, как «Риск»: это тоже «пока не страшно, но
 * смотреть надо». «Плюс» — зелёная, «Минус» — красная.
 */
export function bddsStatusTone(status?: string | null): BddsStatusTone {
  const normalized = String(status || '').trim()

  if (normalized === 'Перерасход' || normalized === 'Минус') {
    return 'danger'
  }
  if (normalized === 'Риск' || normalized === 'Граница') {
    return 'warning'
  }
  if (normalized === 'Норма' || normalized === 'Плюс') {
    return 'ok'
  }

  return 'neutral'
}

export type BddsStatusFilterId = 'all' | 'ok' | 'risk' | 'over' | 'nolimit'

export const BDDS_STATUS_FILTERS: Array<{ id: BddsStatusFilterId, label: string }> = [
  { id: 'all', label: 'Все' },
  { id: 'ok', label: 'Норма' },
  { id: 'risk', label: 'Риск' },
  { id: 'over', label: 'Перерасход' },
  { id: 'nolimit', label: 'Без лимита' },
]

/**
 * Проект попадает в чип.
 *
 * Чип «Без лимита» ловит и поддержку, и обычный проект без заведённого
 * плана — по признаку has_budget, а не по названию статуса: у поддержки
 * статус называется «Плюс» / «Граница» / «Минус», и по статусу она в этот
 * чип не попала бы, хотя именно там её и ищут.
 */
export function matchesBddsStatusFilter(row: BddsProjectRecord, filter: BddsStatusFilterId): boolean {
  const status = String(row.budget_health_status || '').trim()

  switch (filter) {
    case 'ok':
      return status === 'Норма' || status === 'Плюс'
    case 'risk':
      return status === 'Риск' || status === 'Граница'
    case 'over':
      return status === 'Перерасход' || status === 'Минус'
    case 'nolimit':
      return !row.has_budget
    default:
      return true
  }
}

export type BddsChip = {
  id: BddsStatusFilterId
  label: string
  count: number
  tone: BddsStatusTone
}

/** Чипы со счётчиками. Счёт всегда по ВСЕМ строкам, а не по отфильтрованным. */
export function buildBddsChips(rows: BddsProjectRecord[]): BddsChip[] {
  const list = rows || []

  return BDDS_STATUS_FILTERS.map(chip => ({
    id: chip.id,
    label: chip.label,
    count: chip.id === 'all'
      ? list.length
      : list.filter(row => matchesBddsStatusFilter(row, chip.id)).length,
    tone: chip.id === 'all' ? 'neutral' : bddsStatusTone(chip.label),
  }))
}

export type BddsFilterState = {
  status: BddsStatusFilterId
  query: string
  /** Только проекты с заведённым лимитом (галочка «Только с лимитом»). */
  onlyWithBudget: boolean
  /** Только проекты, где прогноз выходит за план. */
  onlyForecastOverrun: boolean
}

export const DEFAULT_BDDS_FILTERS: BddsFilterState = {
  status: 'all',
  query: '',
  onlyWithBudget: false,
  onlyForecastOverrun: false,
}

export function bddsForecastExceedsPlan(row: BddsProjectRecord): boolean {
  const overrun = Number(row.forecast_overrun_amount)
  return Number.isFinite(overrun) && overrun > 0
}

export function filterBddsProjects(
  rows: BddsProjectRecord[],
  filters: BddsFilterState
): BddsProjectRecord[] {
  return (rows || []).filter((row) => {
    if (!matchesBddsStatusFilter(row, filters.status)) {
      return false
    }
    if (filters.onlyWithBudget && !row.has_budget) {
      return false
    }
    if (filters.onlyForecastOverrun && !bddsForecastExceedsPlan(row)) {
      return false
    }

    return matchesBoardSearch(row, filters.query)
  })
}

export function countActiveBddsFilters(filters: BddsFilterState): number {
  let count = 0

  if (filters.status !== 'all') count += 1
  if (filters.query.trim()) count += 1
  if (filters.onlyWithBudget) count += 1
  if (filters.onlyForecastOverrun) count += 1

  return count
}

// --- Подписи проекта -------------------------------------------------------

/** «ООО Клиент · куратор Егор Цыганков · до 31.12.2026» — вторая строка. */
export function bddsProjectSubtitle(row: BddsProjectRecord): string {
  const parts: string[] = []

  if (row.company_name) {
    parts.push(String(row.company_name))
  }
  if (row.curator_name) {
    parts.push(`куратор ${row.curator_name}`)
  }
  if (row.project_end_date) {
    parts.push(`до ${formatProjectDate(row.project_end_date)}`)
  }

  return parts.join(' · ')
}

/**
 * План — деньгами и часами одной подписью.
 *
 * «Без лимита» вместо нуля и прочерка: у проекта поддержки плана нет по
 * существу, и прочерк читался бы как «данные не загрузились».
 */
export function formatBddsPlan(row: BddsProjectRecord): string {
  if (!row.has_budget) {
    return 'Без лимита'
  }

  const parts: string[] = []
  if (row.planned_amount !== null && row.planned_amount !== undefined) {
    parts.push(formatProjectCurrency(row.planned_amount))
  }
  if (row.planned_hours !== null && row.planned_hours !== undefined) {
    parts.push(formatProjectHours(row.planned_hours))
  }

  return parts.join(' · ') || 'Без лимита'
}

/** Остаток. Отрицательный остаток — это перерасход, и он подписан словом. */
export function formatBddsRemaining(row: BddsProjectRecord): string {
  if (row.budget_remaining === null || row.budget_remaining === undefined) {
    return '—'
  }

  const value = Number(row.budget_remaining)
  if (value < 0) {
    return `${formatProjectCurrency(Math.abs(value))} сверх плана`
  }

  return formatProjectCurrency(value)
}

// --- Прогноз ---------------------------------------------------------------

export type BddsForecastView = {
  /** Сумма прогноза либо «—», если посчитать нечем. */
  value: string
  /** «+120 000 ₽ к плану» / «экономия 80 000 ₽» либо пустая строка. */
  deviation: string
  tone: BddsStatusTone
  /** Почему именно столько — подсказкой у цифры. */
  explanation: string
  /** Прогноз не посчитан: показываем причину, а не ноль. */
  isEmpty: boolean
}

/**
 * Как читается прогноз в интерфейсе.
 *
 * Формула — линейная экстраполяция по текущему темпу (вариант A записки,
 * вопрос 3): факт затрат делим на число начавшихся месяцев проекта и
 * добавляем этот темп на каждый полный месяц до даты окончания. Она
 * объяснима одной фразой, и эта фраза лежит в подсказке у цифры: прогноз,
 * который человек не может проверить в уме, он проигнорирует.
 *
 * Прогноз НИКОГДА не меняет статус проекта: статус считается только по
 * факту. Иначе средний темп, который врёт на проектах с неровной загрузкой
 * (разработка в начале, приёмка в конце), рассылал бы уведомления.
 */
export function describeBddsForecast(row: BddsProjectRecord): BddsForecastView {
  const amount = row.forecast_cost_amount

  if (amount === null || amount === undefined) {
    return {
      value: '—',
      deviation: '',
      tone: 'neutral',
      explanation: String(row.forecast_reason || 'Прогноз не посчитан.'),
      isEmpty: true,
    }
  }

  const overrun = row.forecast_overrun_amount
  let deviation = ''
  let tone: BddsStatusTone = 'neutral'

  if (overrun !== null && overrun !== undefined) {
    const value = Number(overrun)
    if (value > 0) {
      deviation = `${formatProjectCurrency(value)} сверх плана`
      tone = 'danger'
    } else if (value < 0) {
      deviation = `экономия ${formatProjectCurrency(Math.abs(value))}`
      tone = 'ok'
    } else {
      deviation = 'ровно в план'
    }
  }

  return {
    value: formatProjectCurrency(amount),
    deviation,
    tone,
    explanation: String(row.forecast_reason || ''),
    isEmpty: false,
  }
}

/** Одна строка о методе прогноза — в шапку экрана, чтобы не спрашивали. */
export const BDDS_FORECAST_METHOD_HINT = 'Прогноз = факт затрат + средний месячный темп × число полных месяцев до даты окончания проекта. Темп = факт ÷ число начавшихся месяцев. Прогноз не влияет на статус: статус считается только по факту.'

// --- Оговорки по данным ----------------------------------------------------

/**
 * Часы без снимка ставки: сумма факта по ним — оценка.
 *
 * Возвращает null, когда оговаривать нечего. Молчать нельзя: на стенде
 * такие записи есть, и человек, который сверяет сумму с отчётом по часам,
 * обязан знать, почему она может разойтись.
 */
export function describeBddsRateGap(row: BddsProjectRecord): string | null {
  const hours = Number(row.actual_hours_without_rate_snapshot)

  if (!Number.isFinite(hours) || hours <= 0) {
    return null
  }

  const rate = Number(row.fallback_hourly_rate)
  const rateText = Number.isFinite(rate) && rate > 0
    ? ` по текущей ставке карточки (${formatProjectCurrency(rate)}/ч)`
    : ''

  return `${formatProjectHours(hours)} списано без снимка ставки: их стоимость посчитана${rateText}, а не по ставке на момент списания. Эта часть суммы — оценка.`
}

/** Проект без лимита: что показываем вместо статуса и полосы освоения. */
export function describeBddsNoBudget(row: BddsProjectRecord): string {
  if (row.is_support) {
    return `Поддержка: плана нет, контролируется финансовый результат — ${formatProjectCurrency(row.actual_financial_result)}.`
  }

  return 'Плановый лимит в карточке проекта не заведён: освоение и статус не считаются.'
}

// --- Показатели портфеля ---------------------------------------------------

export type BddsKpi = {
  id: string
  label: string
  value: string
  hint: string
  tone: BddsStatusTone
  /** Откуда цифра: списания, операции смарт-процесса или расчёт. */
  source: 'списания' | 'операции' | 'расчёт'
}

/**
 * Пять показателей над реестром — те же, что в макете.
 *
 * Итог ПЛАНА считается только по проектам с лимитом (так отдаёт сервер):
 * иначе освоение портфеля делилось бы на неполный план и всегда выглядело
 * бы хуже, чем есть. Факт при этом по всем проектам — деньги истрачены
 * независимо от того, заведён ли лимит.
 */
export function buildBddsKpis(
  totals: BddsTotals,
  statusCounts: Record<string, number>,
  thresholds: BddsThresholds
): BddsKpi[] {
  const attention = Number(statusCounts?.attention || 0)
  const risk = Number(statusCounts?.['Риск'] || 0)
  const overrun = Number(statusCounts?.['Перерасход'] || 0)

  return [
    {
      id: 'plan',
      label: 'План выбытий',
      value: formatProjectCurrency(totals.planned_amount),
      hint: `по ${totals.with_budget_count} проектам с лимитом · без лимита ${totals.without_budget_count}`,
      tone: 'neutral',
      source: 'расчёт',
    },
    {
      id: 'fact',
      label: 'Факт затрат',
      value: formatProjectCurrency(totals.actual_cost_amount),
      hint: `${formatProjectHours(totals.actual_hours)} × ставка на момент списания`,
      tone: 'neutral',
      source: 'списания',
    },
    {
      id: 'utilization',
      label: 'Освоение бюджета',
      value: totals.budget_utilization_percent === null
        ? '—'
        : formatProjectPercent(totals.budget_utilization_percent),
      hint: `порог риска ${thresholds.risk_percent}% · перерасхода ${thresholds.overrun_percent}%`,
      tone: bddsUtilizationTone(totals.budget_utilization_percent, thresholds),
      source: 'расчёт',
    },
    {
      id: 'financial-result',
      label: 'Финансовый результат',
      value: formatProjectCurrency(totals.actual_financial_result),
      hint: `поступления ${formatProjectCurrency(totals.actual_income_amount)} − выбытия ${formatProjectCurrency(totals.actual_expense_amount + totals.actual_cost_amount)}`,
      tone: totals.actual_financial_result < 0 ? 'danger' : 'ok',
      source: 'операции',
    },
    {
      id: 'attention',
      label: 'Требуют внимания',
      value: String(attention),
      hint: `${risk} риск · ${overrun} перерасход · ${totals.without_budget_count} без лимита`,
      tone: attention > 0 ? 'warning' : 'ok',
      source: 'расчёт',
    },
  ]
}

/** Зона по проценту освоения и порогам портала. */
export function bddsUtilizationTone(
  percent: number | null | undefined,
  thresholds: Pick<BddsThresholds, 'risk_percent' | 'overrun_percent'>
): BddsStatusTone {
  // null проверяется ОТДЕЛЬНО от Number.isFinite: Number(null) === 0, то
  // есть «освоение не считается» превратилось бы в зелёный ноль процентов —
  // ровно то, чего не должно быть у проекта без лимита.
  if (percent === null || percent === undefined) {
    return 'neutral'
  }

  const value = Number(percent)

  if (!Number.isFinite(value)) {
    return 'neutral'
  }
  if (value > Number(thresholds.overrun_percent)) {
    return 'danger'
  }
  if (value >= Number(thresholds.risk_percent)) {
    return 'warning'
  }

  return 'ok'
}

/** Ширина полосы освоения, 0–100. Перерасход упирается в 100 и красится. */
export function bddsBarPercent(percent: number | null | undefined): number {
  const value = Number(percent)

  if (!Number.isFinite(value) || value <= 0) {
    return 0
  }

  return Math.min(100, Math.round(value * 10) / 10)
}

// --- Прогон уведомлений ----------------------------------------------------

/**
 * Итог прогона уведомлений человеческим текстом.
 *
 * Нужен кнопке «Проверить сейчас» в настройках: без неё нотификатор нечем
 * вызвать из приложения вовсе — ручка рассчитана на внешнее расписание, и
 * проверить, что уведомления доходят, было бы можно только дождавшись
 * ночного прогона.
 *
 * Отдельно разбираем status=disabled: «отправлено 0» при выключенной
 * настройке читается как «событий нет», и человек пошёл бы искать причину
 * в данных вместо тумблера, который сам же и выключил.
 */
export function describeBddsNotifierRun(result: BddsNotifierRunResult | null | undefined): string {
  if (!result) {
    return ''
  }

  if (String(result.status || '') === 'disabled') {
    return 'Уведомления выключены настройкой — прогон ничего не отправил.'
  }

  const checked = Number(result.checked || 0)
  const sent = Number(result.sent || 0)
  const cooldown = Number(result.cooldown_skipped || 0)
  const errors = Number(result.errors || 0)

  const parts = [`Проверено проектов: ${checked}`, `отправлено: ${sent}`]

  if (cooldown > 0) {
    parts.push(`отложено паузой: ${cooldown}`)
  }
  if (errors > 0) {
    parts.push(`ошибок отправки: ${errors}`)
  }
  if (sent === 0 && cooldown === 0 && errors === 0) {
    parts.push('новых событий нет')
  }

  return `${parts.join(' · ')}.`
}
