/**
 * Операции поступлений и списаний по проектам: разбор, итоги, форма, тексты.
 *
 * Что это за сущность. Операция — элемент смарт-процесса «Доходы-расходы
 * (App)» на портале. Приложение её НЕ хранит: в нашей БД лежат часы и
 * карточки проектов, а деньги мимо часов (авансы, этапы договора,
 * подрядчики, лицензии) ведутся в CRM, и оттуда же их читает расчёт
 * бюджета (finance_operation_service → project_budget_service). Поэтому
 * экран операций — это вид на портал, а не вторая бухгалтерия.
 *
 * Почему всё расчётное здесь, а не в компонентах. Ровно по причине из
 * bddsRegistry.ts: node:test через tsx не резолвит .vue, и логика,
 * оставшаяся внутри компонента, тестами не покрывается. Здесь только чистые
 * функции — ни Vue, ни обращений к сети.
 *
 * ГЛАВНОЕ, что этот файл обязан говорить честно, — три вещи, в которых
 * интерфейс легко соврать:
 *
 *  1. «Смарт-процесс не настроен» ≠ «операций нет». Первое — незаполненная
 *     настройка приложения, и человека надо вести в настройки. Второе —
 *     рабочее состояние. Пустая таблица вместо отказа заставляет искать
 *     ошибку в данных вместо настройки (тексты — NOT_CONFIGURED / EMPTY).
 *  2. Итог по видимой странице — не итог по выборке. Сервер считает итоги по
 *     всей выборке только при totals=1; если он их не посчитал, показывать
 *     сумму загруженных строк как «итого» нельзя.
 *  3. Операция НЕ меняет остаток бюджета проекта. Остаток на этапе 1 — это
 *     план минус стоимость СПИСАННЫХ ЧАСОВ (project_budget_service:
 *     budget_remaining = planned_amount − actual_cost_amount), а списания и
 *     поступления попадают только в финансовый результат. Показать «остаток
 *     не изменился» без объяснения значит выглядеть сломанным.
 */

import type {
  BddsOperationCreatePayload,
  BddsOperationTotals,
  BddsOperationType,
  BddsOperationsResponse,
  BddsProjectRecord,
  ProjectFinanceOperationRecord,
} from '~/types/bdds'
import { buildMappingStepLink } from './fieldMapping'

/** Размер страницы списка. Столько же просит «Показать ещё». */
export const BDDS_OPERATIONS_PAGE_SIZE = 20

/**
 * Источник операции, заведённой с экрана БДДС.
 *
 * Именно 'manual', и это не косметика: finance_operation_service требует
 * deal_id у всякой операции, у которой источник НЕ manual (операция из
 * вкладки сделки всегда привязана к сделке). Операция по проекту сделки не
 * знает, поэтому источник обязан быть manual — иначе сервер ответит 400.
 */
export const BDDS_OPERATION_MANUAL_SOURCE = 'manual'

export const BDDS_OPERATION_TYPE_LABELS: Record<BddsOperationType, string> = {
  income: 'Поступление',
  expense: 'Списание',
}

/** Варианты для переключателя типа в форме и в фильтре. */
export const BDDS_OPERATION_TYPE_OPTIONS: Array<{ id: BddsOperationType, label: string }> = [
  { id: 'income', label: BDDS_OPERATION_TYPE_LABELS.income },
  { id: 'expense', label: BDDS_OPERATION_TYPE_LABELS.expense },
]

/**
 * Как портал мог записать тип.
 *
 * Тот же набор написаний, что сводит сервер
 * (FinanceOperationService._normalize_operation_type): операции заводят и
 * руками в CRM, и стадией смарт-процесса, и русским текстом. Список здесь
 * нужен на случай, когда строка до фронта дошла ненормализованной — раньше
 * такие элементы читались как «списание» просто потому, что не 'income'.
 */
const INCOME_SPELLINGS = new Set(['income', 'in', 'поступление', 'доход'])
const EXPENSE_SPELLINGS = new Set(['expense', 'out', 'расход', 'затрата', 'списание', 'выбытие'])

/** Тип операции либо null. null — «портал написал что-то третье». */
export function readBddsOperationType(value: unknown): BddsOperationType | null {
  const text = String(value ?? '').trim().toLowerCase()
  if (!text) {
    return null
  }
  if (INCOME_SPELLINGS.has(text)) {
    return 'income'
  }
  if (EXPENSE_SPELLINGS.has(text)) {
    return 'expense'
  }
  // Префикс — последний рубеж: 'expenses', 'expense_other' и подобное.
  if (text.startsWith('exp') || text.startsWith('расх')) {
    return 'expense'
  }
  if (text.startsWith('inc') || text.startsWith('пост') || text.startsWith('дох')) {
    return 'income'
  }
  return null
}

/** Строка списка: всё, что рисует таблица, посчитано один раз. */
export type BddsOperationRow = {
  /** id элемента смарт-процесса. Пустая строка — элемент без id. */
  id: string
  /** Тип либо null: null рисуется как «тип не распознан», а не как списание. */
  type: BddsOperationType | null
  typeLabel: string
  /** Сумма всегда положительная — знак несёт тип. */
  amount: number
  /** Сумма со знаком: поступление +, списание −. Для итогов и сортировок. */
  signedAmount: number
  currency: string
  date: string | null
  /** Назначение платежа — заголовок элемента СП. */
  purpose: string
  comment: string
  /** Автор операции: ответственный элемента СП. */
  authorId: string
  source: string
  projectItemId: string
  dealId: string
}

/**
 * Одна операция из ответа сервера.
 *
 * Тип, не поддающийся разбору, остаётся null, а сумма не уходит ни в
 * поступления, ни в списания. Отнести непонятную запись к списаниям
 * «по умолчанию» — это молча исправить данные клиента.
 */
export function normalizeBddsOperation(raw: ProjectFinanceOperationRecord | null | undefined): BddsOperationRow {
  const source = raw || {}
  const type = readBddsOperationType(source.operation_type)
  const amountValue = Number(source.amount)
  const amount = Number.isFinite(amountValue) ? Math.abs(Math.round(amountValue * 100) / 100) : 0

  return {
    id: String(source.id ?? '').trim(),
    type,
    typeLabel: type ? BDDS_OPERATION_TYPE_LABELS[type] : 'Тип не распознан',
    amount,
    signedAmount: type === 'expense' ? -amount : (type === 'income' ? amount : 0),
    currency: String(source.currency ?? '').trim() || 'RUB',
    date: String(source.operation_date ?? '').trim() || null,
    purpose: String(source.title ?? '').trim(),
    comment: String(source.comment ?? '').trim(),
    authorId: String(source.responsible_user_id ?? '').trim(),
    source: String(source.source ?? '').trim(),
    projectItemId: String(source.project_item_id ?? '').trim(),
    dealId: String(source.deal_id ?? '').trim(),
  }
}

/** Страница операций так, как её держит экран. */
export type BddsOperationsPage = {
  rows: BddsOperationRow[]
  /** Сколько строк на этой странице. */
  count: number
  offset: number
  limit: number
  /** Всего в выборке либо null — «сервер не считал». */
  total: number | null
  hasMore: boolean
  /** Выборка длиннее предела одного прохода по смарт-процессу. */
  truncated: boolean
  /** Итоги по выборке либо null. null — считать их самим НЕЛЬЗЯ. */
  totals: BddsOperationTotals | null
  entityTypeId: number | null
}

/**
 * Разбор ответа GET /api/finance-operations.
 *
 * Терпим к форме: у ручки исторически было три поля (operations, count,
 * entity_type_id), постраничность и итоги добавлены позже, и экран обязан
 * работать против обоих ответов — иначе выкатка фронта впереди бэкенда
 * ломает список. Чего разбор НЕ делает — не выдумывает total и totals: их
 * отсутствие означает «неизвестно», и это состояние экран показывает как
 * есть.
 */
export function parseBddsOperationsPage(raw: BddsOperationsResponse | null | undefined): BddsOperationsPage {
  const payload = raw || ({} as BddsOperationsResponse)
  const operations = Array.isArray(payload.operations) ? payload.operations : []
  const rows = operations.map(normalizeBddsOperation)

  const limitValue = Number(payload.limit)
  const offsetValue = Number(payload.offset)
  const totalValue = Number(payload.total)
  const entityTypeValue = Number(payload.entity_type_id)

  return {
    rows,
    count: Number.isFinite(Number(payload.count)) ? Number(payload.count) : rows.length,
    offset: Number.isFinite(offsetValue) && offsetValue >= 0 ? offsetValue : 0,
    limit: Number.isFinite(limitValue) && limitValue > 0 ? limitValue : BDDS_OPERATIONS_PAGE_SIZE,
    total: payload.total === null || payload.total === undefined || !Number.isFinite(totalValue)
      ? null
      : totalValue,
    hasMore: Boolean(payload.has_more),
    truncated: Boolean(payload.truncated),
    totals: readBddsOperationTotals(payload.totals),
    entityTypeId: Number.isFinite(entityTypeValue) && entityTypeValue > 0 ? entityTypeValue : null,
  }
}

function readBddsOperationTotals(raw: unknown): BddsOperationTotals | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const source = raw as Record<string, unknown>
  const income = Number(source.income)
  const expense = Number(source.expense)
  if (!Number.isFinite(income) || !Number.isFinite(expense)) {
    return null
  }

  const count = Number(source.count)
  const net = Number(source.net)

  return {
    income: round2(income),
    expense: round2(expense),
    net: Number.isFinite(net) ? round2(net) : round2(income - expense),
    count: Number.isFinite(count) ? count : 0,
  }
}

/**
 * Итоги по УЖЕ ЗАГРУЖЕННЫМ строкам.
 *
 * Отдельная функция от `totals` сервера, и подписывается в интерфейсе
 * иначе: это сумма видимого, а не выборки. Нужна там, где выборка целиком и
 * есть видимое — список операций одного проекта на карточке.
 */
export function sumBddsOperations(rows: BddsOperationRow[]): BddsOperationTotals {
  let income = 0
  let expense = 0

  for (const row of rows) {
    if (row.type === 'income') {
      income += row.amount
    } else if (row.type === 'expense') {
      expense += row.amount
    }
  }

  return {
    income: round2(income),
    expense: round2(expense),
    net: round2(income - expense),
    count: rows.length,
  }
}

// ---------------------------------------------------------------------------
// Фильтры реестра
// ---------------------------------------------------------------------------

export type BddsOperationFilterState = {
  /** project_item_id, а НЕ project_id: операции связаны с элементом СП. */
  projectItemId: string
  dateFrom: string
  dateTo: string
  type: BddsOperationType | 'all'
}

export const DEFAULT_BDDS_OPERATION_FILTERS: BddsOperationFilterState = {
  projectItemId: '',
  dateFrom: '',
  dateTo: '',
  type: 'all',
}

/** Сколько фильтров стоит — для кнопки «Сбросить (N)». */
export function countActiveBddsOperationFilters(filters: BddsOperationFilterState): number {
  let count = 0
  if (filters.projectItemId) {
    count += 1
  }
  if (filters.dateFrom) {
    count += 1
  }
  if (filters.dateTo) {
    count += 1
  }
  if (filters.type !== 'all') {
    count += 1
  }
  return count
}

/**
 * Параметры запроса к серверу.
 *
 * Период проверяем ЗДЕСЬ: сервер принимает только ISO (ГГГГ-ММ-ДД) и всё
 * прочее отбрасывает молча. Отправить «01.08.2026» значит показать выборку
 * без периода как выборку с периодом.
 *
 * totals запрашиваем только когда итоги реально нужны (реестр): на сервере
 * это полный проход по смарт-процессу, и карточке проекта он незачем — там
 * итоги считает бюджет.
 */
export function buildBddsOperationsQuery(options: {
  filters: BddsOperationFilterState
  offset?: number
  limit?: number
  withTotals?: boolean
}): Record<string, string> {
  const { filters } = options
  const query: Record<string, string> = {
    limit: String(options.limit && options.limit > 0 ? options.limit : BDDS_OPERATIONS_PAGE_SIZE),
    offset: String(options.offset && options.offset > 0 ? options.offset : 0),
  }

  if (filters.projectItemId) {
    query.project_item_id = filters.projectItemId
  }
  if (isIsoDate(filters.dateFrom)) {
    query.date_from = filters.dateFrom
  }
  if (isIsoDate(filters.dateTo)) {
    query.date_to = filters.dateTo
  }
  if (filters.type !== 'all') {
    query.operation_type = filters.type
  }
  if (options.withTotals) {
    query.totals = '1'
  }

  return query
}

/** Период задан наоборот: «с» позже «по». Сервер вернёт пусто и будет прав. */
export function describeBddsOperationPeriodError(filters: BddsOperationFilterState): string {
  if (!isIsoDate(filters.dateFrom) || !isIsoDate(filters.dateTo)) {
    return ''
  }
  if (filters.dateFrom <= filters.dateTo) {
    return ''
  }
  return 'Начало периода позже его конца — в такой период не попадает ничего. Поменяйте даты местами.'
}

// ---------------------------------------------------------------------------
// Форма добавления операции
// ---------------------------------------------------------------------------

export type BddsOperationForm = {
  type: BddsOperationType
  /** Строкой: в поле ввода человек пишет «15 000,50», а не число. */
  amount: string
  date: string
  purpose: string
  comment: string
}

export function defaultBddsOperationForm(today?: Date): BddsOperationForm {
  return {
    type: 'expense',
    amount: '',
    date: toIsoDate(today || new Date()),
    purpose: '',
    comment: '',
  }
}

export type BddsOperationFormErrors = Partial<Record<keyof BddsOperationForm, string>>

export type BddsOperationFormValidation = {
  valid: boolean
  errors: BddsOperationFormErrors
  /** Готовое тело POST /api/finance-operations/create либо null. */
  payload: BddsOperationCreatePayload | null
}

/** Предел суммы. Выше — почти наверняка опечатка в разрядах, а не платёж. */
export const BDDS_OPERATION_AMOUNT_LIMIT = 1_000_000_000

/**
 * Разбор суммы из поля ввода.
 *
 * Запятая как разделитель дробной части и пробелы-разделители разрядов —
 * обычный русский ввод, и требовать от человека «15000.5» незачем. Всё
 * остальное — не число: Number('15 000 руб') даёт NaN, и это правильно.
 */
export function parseBddsOperationAmount(raw: string): number | null {
  const text = String(raw ?? '')
    .replace(/\u00a0/g, '')
    .replace(/\s+/g, '')
    .replace(',', '.')
    .trim()

  if (!text) {
    return null
  }

  const value = Number(text)
  if (!Number.isFinite(value)) {
    return null
  }

  return Math.round(value * 100) / 100
}

/**
 * Проверка формы перед отправкой.
 *
 * Те же правила, что у сервера (_normalize_create_payload: сумма больше
 * нуля, тип и дата обязательны), проверенные до запроса. Это НЕ замена
 * серверной проверки: она остаётся единственной настоящей, здесь — чтобы
 * человек узнал об ошибке до того, как отправит деньги в портал.
 *
 * Назначение обязательно, хотя сервер его не требует: без него портал
 * подставит автозаголовок, и в CRM операция окажется без объяснения, за что
 * платили. Это тот случай, когда интерфейс строже сервера намеренно.
 */
export function validateBddsOperationForm(options: {
  form: BddsOperationForm
  projectItemId: string | null | undefined
}): BddsOperationFormValidation {
  const { form } = options
  const errors: BddsOperationFormErrors = {}

  const projectItemId = String(options.projectItemId ?? '').trim()
  const amount = parseBddsOperationAmount(form.amount)

  if (amount === null) {
    errors.amount = 'Укажите сумму.'
  } else if (amount <= 0) {
    errors.amount = 'Сумма должна быть больше нуля.'
  } else if (amount > BDDS_OPERATION_AMOUNT_LIMIT) {
    errors.amount = 'Сумма больше миллиарда — проверьте разряды.'
  }

  if (!isIsoDate(form.date)) {
    errors.date = 'Укажите дату операции.'
  }

  if (!String(form.purpose ?? '').trim()) {
    errors.purpose = 'Укажите назначение: по нему операцию узнают в CRM.'
  }

  if (!readBddsOperationType(form.type)) {
    errors.type = 'Выберите тип операции.'
  }

  const valid = Object.keys(errors).length === 0 && Boolean(projectItemId)

  return {
    valid,
    errors,
    payload: valid
      ? {
          project_item_id: projectItemId,
          operation_type: form.type,
          amount: amount as number,
          operation_date: form.date,
          title: String(form.purpose).trim(),
          comment: String(form.comment ?? '').trim() || null,
          source: BDDS_OPERATION_MANUAL_SOURCE,
        }
      : null,
  }
}

/**
 * Почему форма недоступна, хотя экран открыт.
 *
 * Два разных запрета, и путать их нельзя: у проекта нет элемента
 * смарт-процесса (операцию не к чему привязать — карточка не
 * синхронизирована) и у человека нет прав. Пустая строка — можно заводить.
 */
export function describeBddsOperationFormBlock(options: {
  projectItemId: string | null | undefined
  canCreate: boolean
  /** Текст отказа по правам: с ролевой моделью он называет роли (appRoles.ts). */
  noRightsText?: string
}): string {
  if (!String(options.projectItemId ?? '').trim()) {
    return 'У проекта нет элемента в смарт-процессе проектов, и привязать операцию не к чему.'
      + ' Откройте «Проекты» и обновите доску: карточка синхронизируется с портала.'
  }
  if (!options.canCreate) {
    return options.noRightsText || BDDS_OPERATION_NO_RIGHTS_TEXT
  }
  return ''
}

/** Кто заводит операции без ролевой модели — те же люди, что выставляют счета. */
export const BDDS_OPERATION_NO_RIGHTS_TEXT = 'Заводить операции может администратор портала'
  + ' или сотрудник с ролью «Бухгалтерия» (Настройки → Роли и права) — как и выставлять счета.'
  + ' Смотреть операции может любой, у кого открыт раздел.'

// ---------------------------------------------------------------------------
// Состояния экрана
// ---------------------------------------------------------------------------

/**
 * Смарт-процесс операций не настроен.
 *
 * Это НЕ «операций нет»: приложение работает, не заполнена настройка, и
 * человека надо вести на шаг «Доходы-расходы» экрана «Сопоставление полей»,
 * а не в поддержку. Тот же смысл, что у серверного кода
 * finance_spa_not_configured, и то же название места, что в bddsErrors.ts —
 * текст один, чтобы человек не получил два разных объяснения одной причины.
 */
export const BDDS_OPERATIONS_NOT_CONFIGURED_TITLE = 'Смарт-процесс «Доходы-расходы» не настроен'

export const BDDS_OPERATIONS_NOT_CONFIGURED_TEXT = 'Поступления и списания по проектам ведутся'
  + ' в смарт-процессе портала, а сопоставление его полей задаётся в настройках приложения —'
  + ' на шаге «Доходы-расходы» экрана «Сопоставление полей».'
  + ' Пока оно не задано, операций не видно и заводить их некуда — план и факт по часам'
  + ' при этом считаются как обычно.'

/**
 * Куда ведёт кнопка из отказа «не настроен».
 *
 * Прямо на шаг «Доходы-расходы», а не на экран целиком. До 12.09.2026 ссылка
 * была голым /settings/mapping, где такого шага не было вовсе, — человек
 * попадал в тупик: настроить процесс было негде.
 */
export const BDDS_OPERATIONS_SETTINGS_PATH = buildMappingStepLink('finance')

export const BDDS_OPERATIONS_SETTINGS_LABEL = 'Настроить «Доходы-расходы»'

/** Кто может сохранить настройку: без этого человек дойдёт до экрана и получит отказ. */
export const BDDS_OPERATIONS_SETTINGS_WHO = 'Сохранить настройку может администратор портала.'

/** Операций нет — с учётом того, стоят ли фильтры. */
export function describeBddsOperationsEmpty(options: {
  filtersActive: number
  scope?: 'project' | 'registry'
}): string {
  if (options.filtersActive > 0) {
    return 'Под фильтры не попала ни одна операция. Снимите период или тип — возможно, операции есть за другой месяц.'
  }
  if (options.scope === 'project') {
    return 'По этому проекту операций пока нет. Поступления и списания мимо часов заводятся кнопкой «Добавить операцию»'
      + ' и попадают в смарт-процесс «Доходы-расходы» на портале.'
  }
  return 'Операций пока нет ни по одному проекту. Они заводятся на карточке проекта в БДДС'
    + ' и живут в смарт-процессе «Доходы-расходы» на портале.'
}

/** Показано не всё: сервер остановился на пределе одного прохода. */
export const BDDS_OPERATIONS_TRUNCATED_TEXT = 'Операций больше, чем сервер читает за один запрос.'
  + ' Показаны самые свежие; итоги посчитаны по прочитанной части, а не по всей истории.'
  + ' Сузьте период или выберите проект.'

/** Ответ сервера «это повтор». Объясняем, почему повтором считается это. */
export function describeBddsOperationDuplicate(row: BddsOperationRow | null): string {
  const base = 'Такая операция уже есть — вторую не создаём.'
  const detail = row
    ? ` Совпадает с операцией от ${formatBddsOperationDate(row.date)} на ${formatBddsOperationAmount(row.amount)}.`
    : ''

  return `${base}${detail} Повтор считается по проекту, типу, сумме, дате и комментарию;`
    + ' назначение в проверку не входит. Если это разные платежи, различите их комментарием.'
}

// ---------------------------------------------------------------------------
// Влияние на бюджет
// ---------------------------------------------------------------------------

export type BddsBudgetImpactRow = {
  id: string
  label: string
  before: number | null
  after: number | null
  /** Разница. null — сравнивать нечего (значения нет ни до, ни после). */
  delta: number | null
  changed: boolean
}

export type BddsBudgetImpact = {
  rows: BddsBudgetImpactRow[]
  /** Что из этого объяснить словами: остаток от операции не двигается. */
  note: string
}

/**
 * Как добавление операции сказалось на бюджете проекта.
 *
 * Считается сравнением ДВУХ ОТВЕТОВ сервера — снимка карточки до записи и
 * после, — а не арифметикой на клиенте. Причина: бюджет считает
 * project_budget_service (кэш сумм операций, ставки из снимков списаний,
 * пороги статуса), и любая своя формула здесь — второй ответ на тот же
 * вопрос, который однажды разойдётся с первым.
 *
 * Про «остаток не изменился». На этапе 1 остаток бюджета — это план минус
 * стоимость списанных часов; списания и поступления в него не входят, они
 * идут в финансовый результат. Это не ошибка расчёта, а принятая модель
 * (записка к макету, раздел 3.3), и интерфейс обязан её назвать: человек,
 * добавивший расход на 300 000 ₽ и увидевший прежний остаток, иначе пойдёт
 * искать поломку.
 */
export function describeBddsBudgetImpact(
  before: BddsProjectRecord | null | undefined,
  after: BddsProjectRecord | null | undefined
): BddsBudgetImpact | null {
  if (!before || !after) {
    return null
  }

  const rows: BddsBudgetImpactRow[] = [
    impactRow('income', 'Поступления', before.actual_income_amount, after.actual_income_amount),
    impactRow('expense', 'Внешние списания', before.actual_expense_amount, after.actual_expense_amount),
    impactRow('cost', 'Факт затрат по часам', before.actual_cost_amount, after.actual_cost_amount),
    impactRow('remaining', 'Остаток бюджета', before.budget_remaining, after.budget_remaining),
    impactRow('result', 'Финрезультат', before.actual_financial_result, after.actual_financial_result),
  ]

  const remaining = rows.find(row => row.id === 'remaining')
  const note = remaining && !remaining.changed
    ? 'Остаток бюджета и факт затрат считаются по списанным часам — операции в них не входят,'
      + ' они меняют финансовый результат проекта. Так устроен бюджет на этом этапе: часы'
      + ' контролируются планом, деньги мимо часов — финрезультатом.'
    : ''

  return { rows, note }
}

function impactRow(
  id: string,
  label: string,
  before: number | null | undefined,
  after: number | null | undefined
): BddsBudgetImpactRow {
  const beforeValue = toFiniteOrNull(before)
  const afterValue = toFiniteOrNull(after)
  const delta = beforeValue === null || afterValue === null ? null : round2(afterValue - beforeValue)

  return {
    id,
    label,
    before: beforeValue,
    after: afterValue,
    delta,
    changed: delta !== null && Math.abs(delta) >= 0.01,
  }
}

// ---------------------------------------------------------------------------
// Форматирование
// ---------------------------------------------------------------------------

/**
 * Сумма операции.
 *
 * Своя, а не formatProjectCurrency из projectBoard.ts: там суммы бюджета
 * округляются до рублей, а операция — документ, и 12 000,50 ₽ обязаны
 * остаться 12 000,50 ₽. Округлять первичку до целого значит показывать
 * сумму, которой в CRM нет.
 */
export function formatBddsOperationAmount(value: number | null | undefined): string {
  const amount = toFiniteOrNull(value)
  if (amount === null) {
    return '—'
  }

  const fractionDigits = Math.abs(amount % 1) >= 0.005 ? 2 : 0
  return `${new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(amount)} ₽`
}

/** Сумма со знаком: поступление +, списание −. */
export function formatBddsOperationSignedAmount(row: BddsOperationRow): string {
  if (!row.type) {
    return formatBddsOperationAmount(row.amount)
  }

  const sign = row.type === 'income' ? '+' : '−'
  return `${sign}${formatBddsOperationAmount(row.amount)}`
}

/** Разница «до → после» со знаком. Ноль — «не изменилось». */
export function formatBddsOperationDelta(delta: number | null): string {
  if (delta === null) {
    return '—'
  }
  if (Math.abs(delta) < 0.01) {
    return 'без изменений'
  }

  const sign = delta > 0 ? '+' : '−'
  return `${sign}${formatBddsOperationAmount(Math.abs(delta))}`
}

/** Дата операции. ISO из ответа сервера — в ДД.ММ.ГГГГ. */
export function formatBddsOperationDate(value: string | null | undefined): string {
  const text = String(value ?? '').trim()
  if (!text) {
    return '—'
  }

  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text)
  if (!match) {
    return text
  }

  return `${match[3]}.${match[2]}.${match[1]}`
}

/** Источник операции человеческим словом. Неизвестный — как пришёл. */
export function formatBddsOperationSource(value: string): string {
  const text = String(value ?? '').trim()
  if (!text) {
    return '—'
  }
  if (text === BDDS_OPERATION_MANUAL_SOURCE) {
    return 'вручную'
  }
  if (text === 'deal_embed') {
    return 'из сделки'
  }
  return text
}

/**
 * Автор операции.
 *
 * Имя берётся из справочника сотрудников, а НЕ выдумывается из id. Если
 * сотрудника в справочнике нет (уволен, не синхронизирован), показываем
 * id — это меньшее зло, чем пустая ячейка: по id человека находят в портале.
 */
export function formatBddsOperationAuthor(
  authorId: string,
  names: Record<string, string> | null | undefined
): string {
  const id = String(authorId ?? '').trim()
  if (!id) {
    return '—'
  }

  const name = String(names?.[id] ?? '').trim()
  return name || `сотрудник #${id}`
}

/** Подпись под итогами: чем именно посчитано. */
export function describeBddsOperationTotals(page: BddsOperationsPage): string {
  if (page.totals) {
    const scope = page.truncated ? 'по прочитанной части выборки' : 'по всей выборке'
    return `Итоги ${scope}: ${page.totals.count} оп.`
  }

  return `Итоги по загруженным операциям: ${page.rows.length} оп.`
    + ' Итог по всей выборке сервер не считал.'
}

// ---------------------------------------------------------------------------
// Мелочи
// ---------------------------------------------------------------------------

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function toFiniteOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null
  }

  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Дата в форме ГГГГ-ММ-ДД и при этом существующая (не 2026-02-31). */
export function isIsoDate(value: string | null | undefined): boolean {
  const text = String(value ?? '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return false
  }

  const parsed = new Date(`${text}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) {
    return false
  }

  return parsed.toISOString().slice(0, 10) === text
}

export function toIsoDate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Первое число месяца, в котором лежит дата. Пресет периода «этот месяц». */
export function firstDayOfMonth(value: Date): string {
  return toIsoDate(new Date(value.getFullYear(), value.getMonth(), 1))
}
