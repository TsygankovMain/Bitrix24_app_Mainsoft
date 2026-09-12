/**
 * Типы функции «Счёт и акт».
 *
 * Источник правды — docs/superpowers/specs/2026-09-12-billing-mvp-contract.md.
 * Ничего сверх контракта здесь не выдумано: поля названы так же, как в теле
 * запроса и в ответе сервера (snake_case), а внутренние формы экранов —
 * отдельными типами с camelCase, чтобы было видно, где данные сервера, а где
 * состояние интерфейса.
 *
 * Поля ответов помечены необязательными намеренно. Бэкенд пишется параллельно
 * по тому же контракту, и первая версия ответа может не содержать какого-то
 * поля; интерфейс обязан пережить это молча, а не белым экраном.
 */

/** Состояние платной функции портала (PortalFeature.state). */
export type BillingFeatureState = 'on' | 'trial' | 'off'

/** Группировка строк документа (поле grouping фильтра). */
export type BillingGrouping = 'project' | 'task' | 'employee' | 'single'

/** Статус выставленного документа (BillingDocument.status). */
export type BillingDocumentStatus = 'issued' | 'cancelled'

/** Коды предупреждений preview из контракта. Чужой код интерфейс тоже переживёт. */
export type BillingWarningCode =
  | 'period_open'
  | 'already_invoiced'
  | 'no_rate'
  | 'mixed_companies'

/** Ответ GET /api/features: по одной записи на код функции. */
export interface PortalFeaturePayload {
  state?: string | null
  trial_until?: string | null
}

export type PortalFeaturesPayload = Record<string, PortalFeaturePayload | null | undefined>

/** Состояние экрана-фильтра мастера «Выставить». */
export interface BillingFilterForm {
  dateFrom: string
  dateTo: string
  companyId: string
  ourCompanyId: string
  projectIds: string[]
  taskIds: string[]
  employeeIds: string[]
  billableOnly: boolean
  onlyClosedPeriods: boolean
  excludeInvoiced: boolean
  grouping: BillingGrouping
}

/** Тело POST /api/billing/preview и POST /api/billing/documents. */
export interface BillingFilterBody {
  date_from: string
  date_to: string
  company_id?: string
  our_company_id?: string
  project_ids?: string[]
  task_ids?: string[]
  employee_ids?: string[]
  billable_only: boolean
  only_closed_periods: boolean
  exclude_invoiced: boolean
  grouping: BillingGrouping
}

/** Строка документа в ответе preview и в карточке. */
export interface BillingLinePayload {
  id?: number | string | null
  project_id?: string | number | null
  project_name?: string | null
  title?: string | null
  hours?: number | string | null
  rate?: number | string | null
  amount?: number | string | null
  sort?: number | null
}

/** Клиент отбора: пара «идентификатор — название». */
export interface BillingCompanyRef {
  id?: string | number | null
  name?: string | null
}

/** Предупреждение preview. Код обязателен, остальное — по желанию сервера. */
export interface BillingWarningPayload {
  code?: string | null
  message?: string | null
  count?: number | null
  details?: string[] | null
  /** Сервер сам сказал, блокирует ли предупреждение выставление. */
  blocking?: boolean | null
  /** Документы, в которых уже лежат эти списания (already_invoiced). */
  document_ids?: Array<string | number> | null
  /**
   * Клиенты отбора (mixed_companies).
   *
   * Сервер кладёт сюда пары id/name, причём name равен идентификатору, когда в
   * карточке проекта названия нет. Из этого списка мастер делает кнопки выбора
   * клиента — иначе блокирующее предупреждение оставляет человека без выхода.
   */
  companies?: BillingCompanyRef[] | null
  /** Незакрытые месяцы «2026-09» (period_open). */
  periods?: string[] | null
}

/** Ответ POST /api/billing/preview. */
export interface BillingPreviewResponse {
  lines?: BillingLinePayload[] | null
  entries_count?: number | null
  total_hours?: number | string | null
  total_amount?: number | string | null
  warnings?: BillingWarningPayload[] | null
  /**
   * Все клиенты отбора. В нормальном случае их ровно один, и тогда интерфейсу
   * удобнее скаляр company_id/company_name; список нужен, чтобы показать
   * mixed_companies списком кнопок.
   */
  companies?: BillingCompanyRef[] | null
  /**
   * Юрлица КАРТОЧЕК проектов отбора. При заданной настройке «наше юрлицо по
   * умолчанию» счёт уйдёт не от них — список остаётся, чтобы показать
   * расхождение (см. utils/billingOurCompany.ts).
   */
  our_companies?: BillingCompanyRef[] | null
  company_id?: string | number | null
  company_name?: string | null
  our_company_id?: string | number | null
  our_company_name?: string | null
  /**
   * Откуда взято наше юрлицо: 'settings' (настройка приложения) либо
   * 'project_card'. Пусто — юрлицо не определено ни там, ни там.
   */
  our_company_source?: string | null
  currency?: string | null
}

/** Документ реестра и шапка карточки. */
export interface BillingDocumentPayload {
  id?: number | string | null
  status?: string | null
  period_from?: string | null
  period_to?: string | null
  company_id?: string | number | null
  company_name?: string | null
  our_company_id?: string | number | null
  our_company_name?: string | null
  currency?: string | null
  vat_mode?: string | null
  vat_rate?: number | string | null
  total_hours?: number | string | null
  total_amount?: number | string | null
  crm_entity_id?: number | string | null
  crm_account_number?: string | null
  act_document_id?: number | string | null
  act_number?: string | null
  /** Ссылки на напечатанный акт, если генератор документов их отдал. */
  act_download_url?: string | null
  act_public_url?: string | null
  act_pdf_url?: string | null
  act_error?: string | null
  created_by_id?: number | string | null
  created_at?: string | null
  cancelled_at?: string | null
  cancel_reason?: string | null
}

/** Потреблённое списание (снимок BillingEntry). */
export interface BillingEntryPayload {
  id?: number | string | null
  timesheet_bitrix_id?: number | string | null
  employee_id?: string | number | null
  employee_name?: string | null
  date_reflection?: string | null
  hours?: number | string | null
  rate_snapshot?: number | string | null
  amount?: number | string | null
  project_id?: string | number | null
  project_name?: string | null
  task_id?: string | number | null
  description?: string | null
}

/** Расхождение снимка с текущими данными (drift[] карточки). */
export interface BillingDriftPayload {
  kind?: string | null
  timesheet_bitrix_id?: number | string | null
  employee_name?: string | null
  date_reflection?: string | null
  hours?: number | string | null
  current_hours?: number | string | null
  rate_snapshot?: number | string | null
  current_rate?: number | string | null
  description?: string | null
}

/** Ответ GET /api/billing/documents/<id>. */
export interface BillingDocumentDetail {
  document?: BillingDocumentPayload | null
  lines?: BillingLinePayload[] | null
  entries?: BillingEntryPayload[] | null
  drift?: BillingDriftPayload[] | null
}

/** Ответ GET /api/billing/documents. */
export interface BillingDocumentsResponse {
  documents?: BillingDocumentPayload[] | null
  items?: BillingDocumentPayload[] | null
  total?: number | null
}

/** Параметры реестра (query-строка GET /api/billing/documents). */
export interface BillingRegistryFilter {
  companyId: string
  dateFrom: string
  dateTo: string
  status: BillingDocumentStatus | ''
}
