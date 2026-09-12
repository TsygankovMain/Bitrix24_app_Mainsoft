/**
 * Фильтр мастера «Выставить»: состояние формы, тело запроса, проверки.
 *
 * Тело собирается ровно по контракту (раздел «Фильтр (тело preview и
 * documents)»): date_from, date_to, company_id, our_company_id, project_ids[],
 * task_ids[], employee_ids[], billable_only, only_closed_periods,
 * exclude_invoiced, grouping. Ни одного поля сверх — сервер пишется по тому
 * же контракту вторым агентом, и «полезная добавка» от фронта там будет
 * молча выброшена или уронит валидацию.
 *
 * Пустые списки и пустые строки в тело НЕ попадают: пустой company_id — это
 * «клиент не выбран», а не «клиент с пустым id», и отличать одно от другого
 * должен фронт, а не сервер.
 */

import { getMonthRange } from './reportDateRange'
import type { BillingFilterBody, BillingFilterForm, BillingGrouping, BillingRegistryFilter } from '~/types/billing'

/** Варианты группировки строк документа — подписи для селекта. */
export const BILLING_GROUPING_OPTIONS: Array<{ id: BillingGrouping, label: string, hint: string }> = [
  { id: 'project', label: 'По проектам', hint: 'Одна строка на проект — так счёт читают чаще всего' },
  { id: 'task', label: 'По задачам', hint: 'Одна строка на задачу: подробнее, но длиннее' },
  { id: 'employee', label: 'По сотрудникам', hint: 'Одна строка на человека' },
  { id: 'single', label: 'Одной строкой', hint: 'Весь период одной строкой «Услуги за период»' },
]

const GROUPING_IDS = BILLING_GROUPING_OPTIONS.map(option => option.id)

export function normalizeBillingGrouping(raw: unknown): BillingGrouping {
  const value = String(raw ?? '').trim() as BillingGrouping

  return GROUPING_IDS.includes(value) ? value : 'project'
}

/**
 * Пустая форма фильтра.
 *
 * Период по умолчанию — ПРОШЛЫЙ месяц: счёт выставляют за закрытый период, а
 * не за текущий, в котором часы ещё дописывают.
 *
 * «Только закрытые месяцы» по умолчанию включено — это фронтовое отражение
 * правила 3 контракта («по умолчанию выставлять можно только за закрытые
 * месяцы»). Галочку можно снять, но тогда preview вернёт предупреждение
 * period_open, а сервер откажет, если настройка портала
 * billing_allow_open_period выключена.
 *
 * «Только оплачиваемые» и «исключить уже выставленное» включены по контракту
 * (billable_only и exclude_invoiced по умолчанию true).
 */
export function createBillingFilterForm(now: Date = new Date()): BillingFilterForm {
  const range = getMonthRange(-1, now)

  return {
    dateFrom: range.dateFrom,
    dateTo: range.dateTo,
    companyId: '',
    ourCompanyId: '',
    projectIds: [],
    taskIds: [],
    employeeIds: [],
    billableOnly: true,
    onlyClosedPeriods: true,
    excludeInvoiced: true,
    grouping: 'project',
  }
}

function normalizeIdList(values: Array<string | number> | null | undefined): string[] {
  if (!Array.isArray(values)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []

  for (const value of values) {
    const id = String(value ?? '').trim()
    if (!id || seen.has(id)) {
      continue
    }

    seen.add(id)
    result.push(id)
  }

  return result
}

/**
 * Строка с идентификаторами задач -> список.
 *
 * Справочника задач в приложении нет (задачи приходят тысячами и живут в
 * Битриксе), поэтому поле текстовое: человек вставляет id из ссылок на
 * задачи. Принимаем любые разделители — запятую, пробел, перенос строки,
 * точку с запятой, — потому что вставляют ровно как скопировали.
 */
export function parseTaskIdsInput(raw: string | null | undefined): string[] {
  return normalizeIdList(String(raw || '').split(/[^0-9]+/))
}

/** Тело POST /api/billing/preview и POST /api/billing/documents. */
export function buildBillingFilterBody(form: BillingFilterForm): BillingFilterBody {
  const body: BillingFilterBody = {
    date_from: String(form.dateFrom || '').trim(),
    date_to: String(form.dateTo || '').trim(),
    billable_only: Boolean(form.billableOnly),
    only_closed_periods: Boolean(form.onlyClosedPeriods),
    exclude_invoiced: Boolean(form.excludeInvoiced),
    grouping: normalizeBillingGrouping(form.grouping),
  }

  const companyId = String(form.companyId || '').trim()
  if (companyId) {
    body.company_id = companyId
  }

  const ourCompanyId = String(form.ourCompanyId || '').trim()
  if (ourCompanyId) {
    body.our_company_id = ourCompanyId
  }

  const projectIds = normalizeIdList(form.projectIds)
  if (projectIds.length) {
    body.project_ids = projectIds
  }

  const taskIds = normalizeIdList(form.taskIds)
  if (taskIds.length) {
    body.task_ids = taskIds
  }

  const employeeIds = normalizeIdList(form.employeeIds)
  if (employeeIds.length) {
    body.employee_ids = employeeIds
  }

  return body
}

/**
 * Что мешает даже посмотреть предпросмотр.
 *
 * Клиента здесь НЕ требуем: смысл предпросмотра в том числе в том, чтобы
 * увидеть предупреждение mixed_companies и понять, что отбор захватил
 * нескольких клиентов. Требование «один клиент на документ» проверяется
 * перед выставлением, а не перед просмотром.
 */
export function validateBillingFilter(form: BillingFilterForm): string[] {
  const errors: string[] = []
  const from = String(form.dateFrom || '').trim()
  const to = String(form.dateTo || '').trim()

  if (!from || !to) {
    errors.push('Укажите период: обе даты обязательны.')
    return errors
  }

  if (from > to) {
    errors.push('Начало периода позже его конца — поменяйте даты местами.')
  }

  return errors
}

/** Пустой фильтр реестра: все клиенты, все статусы, без ограничения по дате. */
export function createBillingRegistryFilter(): BillingRegistryFilter {
  return {
    companyId: '',
    dateFrom: '',
    dateTo: '',
    status: '',
  }
}

/**
 * Query-строка GET /api/billing/documents.
 *
 * Имена параметров — те же, что в теле фильтра (date_from, date_to,
 * company_id), плюс status. Пустые значения не отправляем: «status=» сервер
 * имеет право прочитать как «статус равен пустой строке» и вернуть ноль строк.
 */
export function buildBillingRegistryQuery(filter: BillingRegistryFilter): URLSearchParams {
  const params = new URLSearchParams()
  const companyId = String(filter.companyId || '').trim()
  const dateFrom = String(filter.dateFrom || '').trim()
  const dateTo = String(filter.dateTo || '').trim()
  const status = String(filter.status || '').trim()

  if (companyId) {
    params.append('company_id', companyId)
  }

  if (dateFrom) {
    params.append('date_from', dateFrom)
  }

  if (dateTo) {
    params.append('date_to', dateTo)
  }

  if (status) {
    params.append('status', status)
  }

  return params
}
