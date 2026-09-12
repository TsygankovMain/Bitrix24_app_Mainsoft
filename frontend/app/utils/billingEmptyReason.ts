/**
 * Почему предпросмотр пуст.
 *
 * «По этому отбору часов не нашлось» — самый дорогой текст этого экрана:
 * человек видит ноль строк и не знает, сломалось приложение, неверно выбран
 * период или всё уже выставлено. Причин ровно три, и каждая требует РАЗНОГО
 * действия, поэтому они разбираются здесь, а не одной общей фразой в шаблоне.
 *
 * Главный случай — незакрытый месяц. Галочка «только закрытые месяцы» включена
 * по умолчанию (контракт, правило 3), и на текущем месяце она честно
 * выбрасывает все записи ещё в отборе: на сервере фильтр `only_closed_periods`
 * срабатывает РАНЬШЕ, чем накапливаются предупреждения (billing_service.py::
 * collect — `continue` до регистрации open_periods), поэтому предупреждения
 * period_open в ответе не будет. Ноль строк и ни одного слова. Отличить эту
 * ситуацию можно только сверив период со списком закрытых месяцев
 * (/api/periods), что экран и делает.
 *
 * Что можно предложить: снять галочку — но лишь когда настройка приложения
 * billing_allow_open_period это разрешает, иначе сервер всё равно откажет и
 * кнопка будет обманом; либо уйти закрывать месяц (/settings/periods).
 */

import { formatBillingPeriod, formatRecordsRu } from './billingFormat'
import type { BillingWarningPayload } from '~/types/billing'

/** Месяц периода: то, чем оперирует закрытие месяца. */
export type BillingMonth = {
  year: number
  month: number
  /** Ключ «2026-09» — сравнение и dedup. */
  key: string
  /** «сентябрь 2026» — для текста. */
  title: string
}

/** Строка периода из /api/periods — берём только то, что нужно для ответа. */
export type BillingPeriodState = {
  year?: number | string | null
  month?: number | string | null
  closed?: boolean | null
}

export type BillingEmptyReasonCode = 'period_open' | 'all_invoiced' | 'no_hours'

export type BillingEmptyAction = {
  id: 'drop-closed-filter' | 'close-period' | 'open-registry'
  label: string
  /** Маршрут приложения, если действие — переход. */
  to?: string
}

export type BillingEmptyReason = {
  code: BillingEmptyReasonCode
  title: string
  text: string
  actions: BillingEmptyAction[]
}

const MONTHS_NOMINATIVE = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]

/** Защита от абсурдного периода: 10 лет месяцев хватит любому счёту. */
const MAX_MONTHS = 120

function monthTitle(year: number, month: number): string {
  return `${MONTHS_NOMINATIVE[month - 1] || month} ${year}`
}

function parseIsoDate(value: string | null | undefined): { year: number, month: number } | null {
  const match = String(value || '').trim().slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/)
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

/** Месяцы, которые задевает период отбора. Пустой или битый период — пустой список. */
export function listBillingMonths(
  dateFrom: string | null | undefined,
  dateTo: string | null | undefined
): BillingMonth[] {
  const from = parseIsoDate(dateFrom)
  const to = parseIsoDate(dateTo)

  if (!from || !to) {
    return []
  }

  // Перевёрнутый период — пустой список, а не «один месяц». Такой отбор до
  // предпросмотра не доходит (validateBillingFilter не пускает), и делать вид,
  // что он что-то значит, незачем. Сравниваем ISO-строки, а не месяцы:
  // 30.09 -> 01.09 перевёрнут ровно так же, как 30.09 -> 01.08.
  if (String(dateFrom).trim().slice(0, 10) > String(dateTo).trim().slice(0, 10)) {
    return []
  }

  const start = from.year * 12 + (from.month - 1)
  const end = to.year * 12 + (to.month - 1)

  const months: BillingMonth[] = []

  for (let index = start; index <= end && months.length < MAX_MONTHS; index += 1) {
    const year = Math.floor(index / 12)
    const month = (index % 12) + 1

    months.push({
      year,
      month,
      key: `${year}-${String(month).padStart(2, '0')}`,
      title: monthTitle(year, month),
    })
  }

  return months
}

/**
 * Незакрытые месяцы периода.
 *
 * Месяц, которого нет в ответе /api/periods, считается НЕ закрытым: список
 * отдаёт состояния известных периодов, и отсутствие записи означает «его не
 * закрывали». Ошибаться здесь надо в сторону «не закрыт»: назвать открытый
 * месяц закрытым значит увести человека мимо настоящей причины.
 *
 * periods = null — список не загрузился. Тогда мы не знаем ничего и
 * возвращаем пустой список: врать про закрытость нельзя в обе стороны.
 */
export function findOpenMonths(
  months: BillingMonth[],
  periods: BillingPeriodState[] | null | undefined
): BillingMonth[] {
  if (!Array.isArray(periods)) {
    return []
  }

  const closed = new Set<string>()

  for (const row of periods) {
    if (row?.closed !== true) {
      continue
    }

    const year = Number(row?.year)
    const month = Number(row?.month)

    if (!Number.isFinite(year) || !Number.isFinite(month)) {
      continue
    }

    closed.add(`${year}-${String(month).padStart(2, '0')}`)
  }

  return months.filter(item => !closed.has(item.key))
}

function findWarning(
  warnings: BillingWarningPayload[] | null | undefined,
  code: string
): BillingWarningPayload | null {
  if (!Array.isArray(warnings)) {
    return null
  }

  return warnings.find(item => String(item?.code || '').trim() === code) || null
}

function listMonthTitles(months: BillingMonth[]): string {
  return months.map(item => item.title).join(', ')
}

/** Какие фильтры сузили отбор — их и стоит ослабить, когда часов просто нет. */
function describeNarrowing(filters: BillingEmptyReasonInput['filters']): string[] {
  const parts: string[] = []

  if (filters?.billableOnly) {
    parts.push('«только оплачиваемые»')
  }

  const projects = Array.isArray(filters?.projectIds) ? filters.projectIds.length : 0
  if (projects) {
    parts.push(`проекты (${projects})`)
  }

  const employees = Array.isArray(filters?.employeeIds) ? filters.employeeIds.length : 0
  if (employees) {
    parts.push(`сотрудники (${employees})`)
  }

  const tasks = Array.isArray(filters?.taskIds) ? filters.taskIds.length : 0
  if (tasks) {
    parts.push(`задачи (${tasks})`)
  }

  return parts
}

export type BillingEmptyReasonInput = {
  dateFrom: string
  dateTo: string
  /** Галочка «только закрытые месяцы». */
  onlyClosedPeriods: boolean
  /** Настройка приложения billing_allow_open_period. */
  allowOpenPeriod: boolean
  warnings?: BillingWarningPayload[] | null
  /** Ответ /api/periods. null — состояние месяцев неизвестно. */
  periods?: BillingPeriodState[] | null
  /** Имя выбранного клиента — чтобы не звать его «клиентом». */
  companyName?: string | null
  filters?: {
    billableOnly?: boolean
    projectIds?: string[]
    employeeIds?: string[]
    taskIds?: string[]
  }
}

const CLOSE_PERIOD_ACTION: BillingEmptyAction = {
  id: 'close-period',
  label: 'Перейти к закрытию месяца',
  to: '/settings/periods',
}

const REGISTRY_ACTION: BillingEmptyAction = {
  id: 'open-registry',
  label: 'Открыть реестр документов',
  to: '/finance/billing',
}

const DROP_FILTER_ACTION: BillingEmptyAction = {
  id: 'drop-closed-filter',
  label: 'Снять галочку «только закрытые месяцы»',
}

function periodOpenReason(
  input: BillingEmptyReasonInput,
  openMonths: BillingMonth[]
): BillingEmptyReason {
  const titles = listMonthTitles(openMonths)
  const many = openMonths.length > 1
  const subject = many ? `Месяцы ${titles} не закрыты` : `Месяц ${titles} не закрыт`

  const allowance = input.allowOpenPeriod
    ? 'Настройка приложения «Разрешить выставление за открытый период» включена — галочку можно снять '
      + 'и выставить счёт по текущим часам, помня, что они ещё могут измениться.'
    : 'Настройка приложения «Разрешить выставление за открытый период» выключена, поэтому снять галочку '
      + 'нечем: сервер откажет в выставлении. Закройте месяц или попросите администратора включить настройку.'

  return {
    code: 'period_open',
    title: `${subject} — выставлять по умолчанию нельзя`,
    text: `Стоит галочка «только закрытые месяцы», а ${many ? 'эти месяцы' : 'этот месяц'} ещё не `
      + `${many ? 'закрыты' : 'закрыт'}, поэтому в отбор не попало ни одной записи. ${allowance}`,
    actions: input.allowOpenPeriod
      ? [DROP_FILTER_ACTION, CLOSE_PERIOD_ACTION]
      : [CLOSE_PERIOD_ACTION],
  }
}

function allInvoicedReason(
  input: BillingEmptyReasonInput,
  warning: BillingWarningPayload
): BillingEmptyReason {
  const raw = warning?.count
  const count = typeof raw === 'number' ? raw : Number(raw)
  const subject = Number.isFinite(count) && count > 0
    ? formatRecordsRu(Math.trunc(count))
    : 'Все записи'
  const period = formatBillingPeriod(input.dateFrom, input.dateTo)

  return {
    code: 'all_invoiced',
    title: 'Эти часы уже выставлены',
    text: `${subject} за ${period || 'выбранный период'} уже попали в действующие документы, `
      + 'поэтому выставлять больше нечего. Один и тот же час в счёт дважды не уходит — если счёт нужно '
      + 'переделать, отмените прежний документ, и его списания снова станут свободными.',
    actions: [REGISTRY_ACTION],
  }
}

function noHoursReason(input: BillingEmptyReasonInput): BillingEmptyReason {
  const period = formatBillingPeriod(input.dateFrom, input.dateTo)
  const company = String(input.companyName || '').trim()
  const narrowing = describeNarrowing(input.filters)

  const head = company
    ? `За ${period || 'выбранный период'} по клиенту «${company}» нет ни одного списания.`
    : `За ${period || 'выбранный период'} по этому отбору нет ни одного списания.`

  const tail = narrowing.length
    ? ` Отбор сужают: ${narrowing.join(', ')} — снимите лишнее или расширьте период.`
    : ' Проверьте период и клиента: часы могли отразить в другом месяце или на проекте другого заказчика.'

  return {
    code: 'no_hours',
    title: 'В периоде нет часов',
    text: `${head}${tail}`,
    actions: [],
  }
}

/**
 * Причина пустого предпросмотра и что с ней делать.
 *
 * Порядок разбора не произволен. Сначала проверяется, мог ли отбор вообще
 * что-то вернуть: если галочка «только закрытые месяцы» стоит, а закрытых
 * месяцев в периоде нет ни одного, то никакая другая причина просто не успела
 * сработать — сервер выбросил записи раньше всех прочих проверок. Только потом
 * смотрим «уже выставлено» (это состояние данных, а не отбора) и, если и его
 * нет, частично открытый период. Общее «часов нет» остаётся последним.
 */
export function resolveBillingEmptyReason(input: BillingEmptyReasonInput): BillingEmptyReason {
  const months = listBillingMonths(input.dateFrom, input.dateTo)
  const openMonths = input.onlyClosedPeriods ? findOpenMonths(months, input.periods) : []
  const everyMonthOpen = months.length > 0 && openMonths.length === months.length

  if (everyMonthOpen) {
    return periodOpenReason(input, openMonths)
  }

  const alreadyInvoiced = findWarning(input.warnings, 'already_invoiced')
  if (alreadyInvoiced) {
    return allInvoicedReason(input, alreadyInvoiced)
  }

  if (openMonths.length) {
    return periodOpenReason(input, openMonths)
  }

  return noHoursReason(input)
}
