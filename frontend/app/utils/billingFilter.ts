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

/**
 * Варианты группировки строк документа — подписи для селекта.
 *
 * Первой идёт группировка ПО ЗАДАЧАМ, и она же значение по умолчанию: строка
 * счёта обязана описывать работы, а название задачи — единственное описание,
 * которое в приложении есть. Группировка по проектам брала имя карточки
 * проекта, и у клиента НУОЛАБ карточка названа по клиенту — наименованием
 * работ в счёте оказалось «НУОЛАБ».
 *
 * Подробное объяснение каждого варианта (что попадёт в наименование работ)
 * живёт в describeBillingGrouping — оно нужно и селекту, и предпросмотру.
 */
export const BILLING_GROUPING_OPTIONS: Array<{ id: BillingGrouping, label: string, hint: string }> = [
  { id: 'task', label: 'По задачам', hint: 'Одна строка на задачу — в наименовании работ название задачи' },
  { id: 'project', label: 'По проектам', hint: 'Одна строка на проект — в наименовании работ название карточки проекта' },
  { id: 'employee', label: 'По сотрудникам', hint: 'Одна строка на человека' },
  { id: 'single', label: 'Одной строкой', hint: 'Весь период одной строкой «Услуги по договору»' },
]

const GROUPING_IDS = BILLING_GROUPING_OPTIONS.map(option => option.id)

/**
 * Группировка из формы или из ответа сервера.
 *
 * Чужое значение читается как «по задачам» — то же значение по умолчанию, что
 * и на сервере (billing_service.DEFAULT_GROUPING).
 */
export function normalizeBillingGrouping(raw: unknown): BillingGrouping {
  const value = String(raw ?? '').trim() as BillingGrouping

  return GROUPING_IDS.includes(value) ? value : 'task'
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
 *
 * Группировка по умолчанию — ПО ЗАДАЧАМ, как и на сервере: в наименовании
 * работ должно стоять название задачи, а не имя карточки проекта.
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
    grouping: 'task',
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

/** Текст, который объясняет, почему клиент обязателен. */
export const BILLING_COMPANY_REQUIRED_ERROR
  = 'Выберите клиента: счёт выставляется одному клиенту, и без него предпросмотр не соберёт документ.'

/**
 * Что мешает даже посмотреть предпросмотр.
 *
 * Клиент ОБЯЗАТЕЛЕН. Раньше его не требовали, рассчитывая, что отбор без
 * клиента полезен сам по себе: предупреждение mixed_companies покажет, чей это
 * час. На стенде получилось наоборот — отбор по умолчанию собирал часы всех
 * клиентов сразу, предпросмотр честно рисовал 33 строки, а кнопка «Выставить»
 * гасла блокером, и выхода из этого экрана не было видно. Показать данные и
 * погасить кнопку хуже, чем не пустить: документ всё равно выставляется на
 * одного клиента (контракт, правило 4), и выбрать его придётся.
 *
 * Проверка дат идёт первой и с ранним возвратом: при пустом периоде остальные
 * претензии избыточны.
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

  if (!String(form.companyId || '').trim()) {
    errors.push(BILLING_COMPANY_REQUIRED_ERROR)
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
