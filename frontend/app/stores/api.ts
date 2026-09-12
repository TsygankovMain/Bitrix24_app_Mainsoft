import type { B24Frame } from '@bitrix24/b24jssdk'
import { withoutTrailingSlash } from 'ufo'
import { withRefreshParam } from '~/utils/apiCache'
import { isJwtFresh, readJwtExpiryMs } from '~/utils/jwt'
import { buildReportSearchParams } from '~/utils/reportFilters'
import type {
  DailyWorkloadReport,
  FilterOption,
  FilterValue,
  FocusAnalysisReport,
  HierarchicalReportNode,
  ProjectTaskReportNode,
  ReportFilterOptions,
  RevenueLeakageReport,
  TimeEntryDisciplineReport,
} from '~/types/report'
import type {
  AppConfigurationPayload,
  FinanceSpaValidationPayload,
  ProjectSpaValidationPayload,
  SmartProcessFieldOption,
  SmartProcessOption,
} from '~/types/config'
import type { CompanySearchResult, MyCompaniesResult, ProjectBoardMetaPayload, ProjectBoardResponse } from '~/types/project-board'
import type {
  BddsNotifierRunResult,
  BddsProjectResponse,
  BddsProjectsResponse,
} from '~/types/bdds'
import type { InnScanResult, InnApplyItem, InnApplyResult, InnProjectItemsResult, ProjectsHealthResult } from '~/types/inn'
import type { ProjectCreationForm, ProjectCreationResult } from '~/types/project-creation'
import type { PeriodBulkPlan, PeriodCheckResult, PeriodEntryRow, PeriodFixResult, PeriodRow } from '~/types/period'
import type {
  BillingDocumentDetail,
  BillingDocumentsResponse,
  BillingFilterBody,
  BillingLinePayload,
  BillingPreviewResponse,
  BillingTemplatesResponse,
  PortalFeaturesPayload,
} from '~/types/billing'

type SaveConfigurationResponse = {
  status?: string
  /** Сервер сохранил по отдельной ветке (сейчас только 'finance'). */
  scope?: string
  config?: AppConfigurationPayload
  project_sync?: Record<string, unknown>
  timesheet_backfill?: Record<string, unknown>
  validation?: ProjectSpaValidationPayload
  finance_validation?: FinanceSpaValidationPayload
  error?: string
}

type SmartProcessCreateResponse = {
  status: string
  config: AppConfigurationPayload
  created_fields_count?: number
  field_warnings?: string[]
}

type MappedFieldCreateResponse = {
  status: string
  config: AppConfigurationPayload
  field_key: string
  field_id: string
  field_warnings?: string[]
}

type MappingType = 'timesheet' | 'project' | 'finance'

export type FinanceOperationRecord = {
  id?: string | null
  title?: string | null
  project_item_id?: string | null
  deal_id?: string | null
  operation_type?: string | null
  amount?: number
  currency?: string | null
  operation_date?: string | null
  source?: string | null
  comment?: string | null
  responsible_user_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

type FinanceOperationsResponse = {
  operations: FinanceOperationRecord[]
  count: number
  entity_type_id?: number
  offset?: number
  limit?: number
  /** null — сервер не считал: он видел окно страницы, а не всю выборку. */
  total?: number | null
  has_more?: boolean
  truncated?: boolean
  totals?: { income: number, expense: number, net: number, count: number } | null
}

/** Что можно спросить у GET /api/finance-operations. */
type FinanceOperationsQuery = {
  project_item_id?: string | null
  deal_id?: string | null
  limit?: number
  offset?: number
  /** Границы периода — ТОЛЬКО ISO (ГГГГ-ММ-ДД): прочее сервер отбросит. */
  date_from?: string | null
  date_to?: string | null
  operation_type?: string | null
  /**
   * Итоги по всей выборке.
   *
   * Просить только там, где они нужны: на сервере это полный проход по
   * смарт-процессу. Карточке проекта незачем — там итоги считает бюджет.
   */
  totals?: boolean
}

type FinanceOperationCreatePayload = {
  project_item_id: string
  deal_id?: string | null
  operation_type: 'income' | 'expense' | string
  amount: number
  currency?: string | null
  operation_date: string
  /** Назначение платежа — заголовок элемента смарт-процесса. */
  title?: string | null
  source?: string | null
  comment?: string | null
  responsible_user_id?: string | null
}

export const useApiStore = defineStore(
  'api',
  () => {
    const normalizeApiBaseUrl = (rawValue: unknown): string => {
      const raw = String(rawValue || '').trim()
      if (!raw) {
        return ''
      }

      if (raw.startsWith('/')) {
        return withoutTrailingSlash(raw)
      }

      if (/^https?:\/\//i.test(raw)) {
        return withoutTrailingSlash(raw)
      }

      if (raw.startsWith('//')) {
        return withoutTrailingSlash(`https:${raw}`)
      }

      // Production safety net: Bitrix app settings are often entered as host without scheme.
      // Treat such value as https host to keep API requests absolute and avoid SPA HTML fallback.
      return withoutTrailingSlash(`https://${raw}`)
    }

    let $b24: null | B24Frame = null
    const config = useRuntimeConfig()
    const apiUrl = normalizeApiBaseUrl(config.public.apiUrl)

    const tokenJWT = ref('')

    // Срок годности выданного JWT (мс epoch) и промис запроса «в полёте».
    //
    // initApp() стоит в onMounted буквально каждой страницы, а api.init() раньше
    // безусловно звал reinitToken() -> POST /api/getToken. На открытии вкладки
    // задачи это давало ДВА токена подряд: монтируется index.client.vue (токен №1),
    // тот определяет placement и делает router.push('/task'), монтируется task.vue
    // (токен №2). Каждый getToken на бэкенде синхронно ходит в Bitrix REST
    // (user.admin) и занимает слот gunicorn — то есть цена лишняя и блокирующая.
    //
    // Просто «получить один раз» нельзя: обработчика 401 в приложении нет, и
    // повторный getToken на каждой навигации де-факто и был механизмом обновления
    // токена. Поэтому гард смотрит на exp самого JWT и обновляет его заранее, за
    // TOKEN_REFRESH_MARGIN_MS до истечения. Токен живёт 60 минут
    // (models.Bitrix24Account.create_jwt_token).
    let tokenExpiresAtMs = 0
    let tokenRequest: Promise<void> | null = null

    const isTokenFresh = (): boolean => {
      return Boolean(tokenJWT.value) && isJwtFresh(tokenExpiresAtMs, Date.now())
    }

    // Сообщение для серверного отказа по правам (admin-only эндпоинты).
    const FORBIDDEN_MESSAGE = 'Недостаточно прав'

    const $api = $fetch.create({
      baseURL: apiUrl,
      headers: {
        'Content-Type': 'application/json'
      },
      onResponseError(ctx) {
        // Бэкенд закрывает админские операции и денежные отчёты декоратором
        // @admin_required и отвечает 403 {"error": "Недостаточно прав"}.
        // Приводим ошибку к понятному сообщению, чтобы общий обработчик
        // (useAppInit.processErrorGlobal) показал его пользователю как обычную ошибку.
        if (ctx.response?.status === 403) {
          const data = ctx.response._data as { error?: string } | undefined
          ctx.error = new Error(data?.error || FORBIDDEN_MESSAGE)
        }

        // HTTP 429 (лимитеры — backends/python/api/main/utils/decorators/rate_limit.py)
        // сознательно НЕ обрабатывается здесь, хотя это тот же обработчик,
        // что закрывает 403 выше, и первое, за что цеплялся взгляд при
        // централизации. Две причины:
        //  1. Бласт-радиус: этот $api — общий клиент, им же пользуется
        //     searchCompanies (см. frontend/app/utils/companySearch.ts),
        //     у которого уже есть своя протестированная, отдельная от
        //     общего пути классификация 429 (свой текст уведомления,
        //     осознанно отличается от RATE_LIMIT_NOTICE_TEXT — см.
        //     apiErrors.ts). Правка здесь звучит безопасно (просто заменить
        //     .message, как для 403), но приём 403 выше подменяет ctx.error
        //     на голый `new Error(...)` без .status/.response — сделать так
        //     же для 429 незаметно сломало бы isRateLimitError на подменённой
        //     ошибке везде, где её сегодня проверяют, если не перенести
        //     статус на новый объект вручную. Решаемо, но лишняя связанность
        //     между независимыми фичами ради нулевой выгоды (см. п.2).
        //  2. Явного выигрыша нет: этот клиент всё равно не может сам решить
        //     «фатальный экран или лёгкое уведомление» — здесь нет доступа
        //     ни к состоянию страницы, ни к решению "это get_token, тут
        //     фатально можно". Настоящая точка, где это решение принимается
        //     (звать showError({fatal:true}) или нет), — processErrorGlobal
        //     в frontend/app/composables/useAppInit.ts: единственное место
        //     всего приложения, которое вызывает showError. Централизация
        //     сделана там (shouldTreatAsFatalError/markRateLimitFatal в
        //     frontend/app/utils/apiErrors.ts) — она закрывает тот же класс
        //     мест (весь код, который зовёт processErrorGlobal(e) в catch),
        //     не трогая этот файл и не рискуя поиском компаний.

        // HTTP 409 app_version_mismatch — вкладка исполняет код, которого на
        // сервере уже нет. Ловим ЗДЕСЬ, а не на экранах: отказ может прийти
        // на любую пишущую ручку, и заводить обработчик в каждой было бы
        // ровно тем дублированием, ради устранения которого этот перехватчик
        // и существует. Ошибку не подменяем — экран всё так же покажет
        // серверный текст, — только взводим флаг для баннера с кнопкой
        // перезагрузки.
        if (ctx.response?.status === 409) {
          const data = ctx.response._data as { code?: string } | undefined
          if (data?.code === 'app_version_mismatch') {
            useAppOutdated().markOutdated()
          }
        }
      }
    })

    const cacheNamespace = `mainsoft-cache:v3:${apiUrl}`

    const browserCacheTtl = {
      filters: 1000 * 60 * 20,
      board: 1000 * 60 * 2,
      meta: 1000 * 60 * 15,
      homepage: 1000 * 60 * 2,
      support: 1000 * 60 * 2,
      config: 1000 * 60 * 5,
      lists: 1000 * 60 * 15,
    }

    const canUseBrowserCache = () => import.meta.client && typeof window !== 'undefined'

    const makeCacheKey = (scope: string) => `${cacheNamespace}:${scope}`

    const readCache = <T>(scope: string): T | null => {
      if (!canUseBrowserCache()) {
        return null
      }

      try {
        const raw = window.localStorage.getItem(makeCacheKey(scope))
        if (!raw) {
          return null
        }

        const parsed = JSON.parse(raw) as { expiresAt?: number, value?: T }
        if (!parsed?.expiresAt || parsed.expiresAt < Date.now()) {
          window.localStorage.removeItem(makeCacheKey(scope))
          return null
        }

        return parsed.value ?? null
      } catch {
        return null
      }
    }

    const writeCache = <T>(scope: string, value: T, ttlMs: number) => {
      if (!canUseBrowserCache()) {
        return
      }

      try {
        window.localStorage.setItem(
          makeCacheKey(scope),
          JSON.stringify({
            expiresAt: Date.now() + ttlMs,
            value
          })
        )
      } catch {
        // Ignore storage quota and serialization errors.
      }
    }

    const clearCache = (...scopes: string[]) => {
      if (!canUseBrowserCache()) {
        return
      }

      for (const scope of scopes) {
        window.localStorage.removeItem(makeCacheKey(scope))
      }
    }

    const hasItems = (value: unknown): value is Array<unknown> => Array.isArray(value) && value.length > 0

    const hasProjectBoardMetaPayload = (value: ProjectBoardMetaPayload | null | undefined): value is ProjectBoardMetaPayload => {
      if (!value || typeof value !== 'object') {
        return false
      }

      if (!value.filters || typeof value.filters !== 'object') {
        return false
      }

      if (!value.directories || typeof value.directories !== 'object') {
        return false
      }

      const directories = value.directories

      return hasItems(directories.employees) || hasItems(directories.companies)
    }

    const withBrowserCache = async <T>(
      scope: string,
      ttlMs: number,
      loader: () => Promise<T>,
      forceRefresh = false
    ): Promise<T> => {
      if (!forceRefresh) {
        const cached = readCache<T>(scope)
        if (cached !== null) {
          return cached
        }
      }

      const value = await loader()
      writeCache(scope, value, ttlMs)
      return value
    }

    // API
    const getEnum = async (): Promise<string[]> => {
      return await $api('/api/enum', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getList = async (): Promise<string[]> => {
      return await $api('/api/list', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const postInstall = async (data: Record<string, unknown>): Promise<Record<string, unknown>> => {
      return await $api('/api/install', {
        method: 'POST',
        body: data,
      })
    }

    const getToken = async (data: Record<string, unknown>): Promise<{ token: string }> => {
      return await $api('/api/getToken', {
        method: 'POST',
        body: data,
      })
    }

    const getFilterOptions = async (): Promise<ReportFilterOptions> => {
      const [employees, projects] = await Promise.all([
        getFilterEmployees(),
        getFilterProjects()
      ])

      return {
        employees,
        projects
      }
    }

    const getFilterEmployees = async (forceRefresh = false): Promise<FilterOption[]> => {
      const scope = 'filter-employees-v3'

      if (!forceRefresh) {
        const cached = readCache<FilterOption[]>(scope)
        if (Array.isArray(cached) && cached.length > 0) {
          return cached
        }
        if (cached !== null) {
          clearCache(scope)
        }
      }

      const response = await $api<{ employees?: FilterOption[] }>('/api/get-filter-employees', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })

      const employees = (response.employees || []) as FilterOption[]
      if (employees.length > 0) {
        writeCache(scope, employees, browserCacheTtl.filters)
      } else {
        clearCache(scope)
      }

      return employees
    }

    const getFilterProjects = async (forceRefresh = false): Promise<FilterOption[]> => {
      return await withBrowserCache('filter-projects', browserCacheTtl.filters, async () => {
        const response = await $api<{ projects?: FilterOption[] }>('/api/get-filter-projects', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })

        return (response.projects || []) as FilterOption[]
      }, forceRefresh)
    }

    const runReportRequest = async <T>(
      path: string,
      dateFrom?: string,
      dateTo?: string,
      employeeFilter?: FilterValue | string[],
      projectFilter?: FilterValue | string[]
    ): Promise<T> => {
      const params = buildReportSearchParams(dateFrom, dateTo, employeeFilter, projectFilter)

      return await $api(`${path}?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportEmployeeProject = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<HierarchicalReportNode[]> => {
      return await runReportRequest<HierarchicalReportNode[]>('/api/report-employee-project', dateFrom, dateTo, empIds, projIds)
    }

    const getReportProjectEmployee = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<HierarchicalReportNode[]> => {
      return await runReportRequest<HierarchicalReportNode[]>('/api/report-project-employee', dateFrom, dateTo, empIds, projIds)
    }

    const getReportDailyWorkload = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<DailyWorkloadReport> => {
      return await runReportRequest<DailyWorkloadReport>('/api/report-daily-workload', dateFrom, dateTo, empIds, projIds)
    }

    const getReportProjectTaskEmployee = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<ProjectTaskReportNode[]> => {
      return await runReportRequest<ProjectTaskReportNode[]>('/api/report-project-task-employee', dateFrom, dateTo, empIds, projIds)
    }

    const exportReportProjectTaskEmployee = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-project-task-employee-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportEmployeeProject = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-employee-project-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportProjectEmployee = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-project-employee-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportDailyWorkload = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-daily-workload-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportRevenueLeakage = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-revenue-leakage-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportTimeEntryDiscipline = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-time-entry-discipline-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const exportReportFocusAnalysis = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<Blob> => {
      const params = buildReportSearchParams(dateFrom, dateTo, empIds, projIds)
      return await $api(`/api/report-focus-analysis-export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        responseType: 'blob'
      })
    }

    const scanInnBackfill = async (
      dateFrom?: string,
      dateTo?: string,
      projectIds?: string[]
    ): Promise<InnScanResult> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      for (const id of projectIds || []) {
        params.append('project_ids[]', String(id))
      }
      return await $api<InnScanResult>(`/api/inn-backfill/scan?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const applyInnBackfill = async (items: InnApplyItem[]): Promise<InnApplyResult> => {
      return await $api<InnApplyResult>('/api/inn-backfill/apply', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify({ items })
      })
    }

    const resolveInnProjectItems = async (
      projectId: string, dateFrom: string, dateTo: string,
      ourInn: string, clientInn: string, overwrite: boolean
    ): Promise<InnProjectItemsResult> => {
      return await $api<InnProjectItemsResult>('/api/inn-backfill/project-items', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify({ project_id: projectId, date_from: dateFrom, date_to: dateTo, our_inn: ourInn, client_inn: clientInn, overwrite })
      })
    }

    const getProjectsHealth = async (): Promise<ProjectsHealthResult> => {
      return await $api<ProjectsHealthResult>('/api/projects-health', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getReportRevenueLeakage = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<RevenueLeakageReport> => {
      return await runReportRequest<RevenueLeakageReport>('/api/report-revenue-leakage', dateFrom, dateTo, empIds, projIds)
    }

    const getReportTimeEntryDiscipline = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<TimeEntryDisciplineReport> => {
      return await runReportRequest<TimeEntryDisciplineReport>('/api/report-time-entry-discipline', dateFrom, dateTo, empIds, projIds)
    }

    const getReportFocusAnalysis = async (
      dateFrom?: string,
      dateTo?: string,
      empIds?: FilterValue | string[],
      projIds?: FilterValue | string[]
    ): Promise<FocusAnalysisReport> => {
      return await runReportRequest<FocusAnalysisReport>('/api/report-focus-analysis', dateFrom, dateTo, empIds, projIds)
    }

    const syncTimesheets = async (dateFrom?: string, dateTo?: string): Promise<{ status: string; count: number; last_synced_at?: string | null }> => {
      const result = await $api<{ status: string, count: number, last_synced_at?: string | null }>('/api/sync-timesheets', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        ...(dateFrom && dateTo ? { body: { date_from: dateFrom, date_to: dateTo } } : {})
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    /**
     * Версия сборки, на которой работает ЭТА вкладка.
     *
     * Смысл в том, что вкладка запоминает версию того кода, который сейчас
     * исполняет: она загрузилась из этой сборки. После передеплоя сервер
     * начнёт отдавать другую версию, а вкладка продолжит слать запомненную —
     * сервер увидит расхождение и запись отклонит.
     *
     * Зачем: приложение живёт в айфрейме, и жёсткая перезагрузка страницы
     * Битрикса содержимое фрейма не обновляет — вкладка может неделями
     * работать на старом коде (инцидент 31.08.2026). Без этой проверки такая
     * вкладка обошла бы запрет на списание в закрытый месяц.
     *
     * ВЕРСИЯ СПРАШИВАЕТСЯ НА СТАРТЕ, А НЕ ПРИ ПЕРВОЙ ЗАПИСИ, и это
     * принципиально. В первой версии (31.08.2026) запрос был ленивым, и
     * защита из-за этого не работала в самом частом случае: вкладка, открытая
     * ДО передеплоя и ничего не писавшая, при первой же записи спрашивала
     * версию у УЖЕ ОБНОВЛЁННОГО сервера, получала новую и успешно проходила
     * проверку — исполняя при этом старый код. Ловились только вкладки,
     * успевшие что-то записать до выкатки. Спрашивая на старте, мы получаем
     * версию сервера на момент загрузки страницы, то есть версию собственного
     * кода.
     */
    const appVersion = ref<string | null>(null)

    /**
     * Единственный запрос версии за жизнь вкладки.
     *
     * Промис запоминается, а не только результат: writeHeaders может успеть
     * дважды до ответа, и без этого получилось бы два параллельных запроса.
     */
    let versionCapture: Promise<void> | null = null

    const captureAppVersion = (): Promise<void> => {
      if (!versionCapture) {
        versionCapture = $api<{ version: string }>('/api/app-version')
          .then((res) => {
            appVersion.value = res?.version || null
          })
          .catch(() => {
            // Версия не критична: сервер трактует её отсутствие как
            // «проверять нечем» и пропускает запись. Ронять списание из-за
            // сбоя вспомогательной ручки нельзя.
          })
      }
      return versionCapture
    }

    // Старт вкладки. Ответ не ждём — он нужен только к первой записи, а
    // блокировать инициализацию стора сетевым запросом незачем.
    if (import.meta.client) {
      void captureAppVersion()
    }

    /**
     * Превращает отказ сервера в понятный пользователю текст.
     *
     * ofetch кладёт в message строку вида `[POST] "/api/…": 409 Conflict`, и
     * экраны показывают в тосте именно её — то есть человек видит код вместо
     * объяснения. Разбор ошибки здесь, а не на каждом экране: сообщение у
     * бэкенда уже человеческое, его достаточно достать.
     */
    const rethrowWithServerMessage = (error: unknown): never => {
      const data = (error as { data?: { error?: string, code?: string } })?.data
      if (data?.error) {
        const friendly = new Error(data.error)
        if (data.code) {
          ;(friendly as Error & { code?: string }).code = data.code
        }
        throw friendly
      }
      throw error
    }

    /**
     * Заголовки пишущего запроса: токен и версия сборки.
     *
     * Ставятся на ВСЕ операции, меняющие данные, а не только на списание
     * часов: закрытие и переоткрытие месяца необратимы, и выполнить их из
     * вкладки со старым кодом — ровно тот случай, ради которого проверка
     * версии заводилась.
     */
    const writeHeaders = async (): Promise<Record<string, string>> => {
      const headers: Record<string, string> = { Authorization: `Bearer ${tokenJWT.value}` }
      await captureAppVersion()
      if (appVersion.value) {
        headers['X-App-Version'] = appVersion.value
      }
      return headers
    }

    /**
     * Создание карточки списания через наш бэкенд.
     *
     * Раньше экраны звали $b24.callMethod('crm.item.add', …) напрямую из
     * браузера, минуя Django. Серверного правила на такую запись наложить было
     * негде — в частности запрет списания в закрытый месяц жил бы только в JS.
     *
     * entityTypeId сюда НЕ передаётся: смарт-процесс выбирает сервер из своей
     * конфигурации. Автор записи не меняется — бэкенд ходит в Битрикс токеном
     * того же сотрудника (см. TimesheetWriteService).
     */
    const createTimesheetEntry = async (fields: Record<string, unknown>): Promise<{ status: string; id: number | null }> => {
      const result = await $api<{ status: string, id: number | null }>('/api/timesheet/create', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { fields }
      }).catch(rethrowWithServerMessage)
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    /** Правка карточки списания. Условия те же, что у createTimesheetEntry. */
    const updateTimesheetEntry = async (id: string | number, fields: Record<string, unknown>): Promise<{ status: string; id: number | null }> => {
      const result = await $api<{ status: string, id: number | null }>('/api/timesheet/update', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { id, fields }
      }).catch(rethrowWithServerMessage)
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    // --- Закрытие месяца ---
    // Спека: docs/architecture/period-closing-spec.md
    const getPeriods = async (): Promise<{ periods: PeriodRow[] }> => {
      return await $api('/api/periods', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const checkPeriod = async (year: number, month: number): Promise<PeriodCheckResult> => {
      return await $api(`/api/periods/check?year=${year}&month=${month}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getPeriodCheckDetails = async (year: number, month: number, code: string): Promise<{ items: PeriodEntryRow[] }> => {
      return await $api(`/api/periods/check?year=${year}&month=${month}&code=${encodeURIComponent(code)}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    /**
     * Исправление находки проверки одним нажатием.
     *
     * В ответе всегда лежит СВЕЖАЯ проверка — экран перерисовывается по факту,
     * а не по прогнозу: часть карточек Битрикс может отвергнуть, часть задач
     * окажется без рабочей группы.
     *
     * 409 здесь штатный: «эту находку машина не чинит» или «период закрыт,
     * сначала переоткройте». Текст берём из ответа сервера.
     */
    const fixPeriodFinding = async (
      year: number, month: number, code: string,
    ): Promise<PeriodFixResult> => {
      const result = await $api<PeriodFixResult>('/api/periods/fix', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { year, month, code }
      }).catch(rethrowWithServerMessage)
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    /**
     * Закрытие периода. Сервер повторно проверяет блокеры и отвечает 409, даже
     * если экран считал, что всё чисто — кнопку можно обойти, а закрытие
     * необратимо. Текст ошибки достаём из ответа (см. rethrowWithServerMessage).
     */
    const closePeriod = async (year: number, month: number): Promise<{ status: string }> => {
      const result = await $api<{ status: string }>('/api/periods/close', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { year, month }
      }).catch(rethrowWithServerMessage)
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const reopenPeriod = async (year: number, month: number, reason: string): Promise<{ status: string }> => {
      const result = await $api<{ status: string }>('/api/periods/reopen', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { year, month, reason }
      }).catch(rethrowWithServerMessage)
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    /**
     * Закрыть все открытые периоды до указанного включительно.
     *
     * Без acknowledge сервер НИЧЕГО не закрывает, а отвечает 409 с разбором:
     * какие периоды затронуты и что в каждом сломано. Это не ошибка, а
     * запрос подтверждения — экран показывает разбор и просит согласия.
     */
    const closePeriodsBulk = async (
      untilYear: number, untilMonth: number, acknowledge = false,
    ): Promise<PeriodBulkPlan> => {
      const result = await $api<PeriodBulkPlan>('/api/periods/close-bulk', {
        method: 'POST',
        headers: await writeHeaders(),
        body: { until_year: untilYear, until_month: untilMonth, acknowledge }
      }).catch((error: unknown) => {
        // 409 здесь — штатный ответ «подтвердите», а не сбой.
        const data = (error as { data?: PeriodBulkPlan })?.data
        if (data?.code === 'acknowledge_required') return data
        return rethrowWithServerMessage(error)
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const getLateArrivals = async (year: number, month: number): Promise<{ items: PeriodEntryRow[] }> => {
      return await $api(`/api/periods/late?year=${year}&month=${month}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getTimesheetSyncStatus = async (): Promise<{ last_synced_at: string | null; count: number }> => {
      return await $api<{ last_synced_at: string | null, count: number }>('/api/timesheet-sync-status', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getTimesheetsList = async (page: number = 1, limit: number = 50, createdFrom?: string, createdTo?: string): Promise<{ items: unknown[], total: number, page: number, pages: number }> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      if (createdFrom) params.append('created_from', createdFrom)
      if (createdTo) params.append('created_to', createdTo)

      return await $api(`/api/timesheets?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getUsers = async (
      page: number = 1,
      limit: number = 50,
      activeOnly: boolean = false,
      search: string = ''
    ): Promise<{ items: Array<{ id: string, name: string, last_name: string, active: boolean, updated_at: string }>, total: number, page: number, pages: number, has_next: boolean, has_previous: boolean }> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      if (activeOnly) params.append('active_only', '1')
      // Поиск по имени и фамилии — экран ролей (backend: get_users, ?search=).
      if (search.trim()) params.append('search', search.trim())

      return await $api(`/api/users?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getProjectBoard = async (forceRefresh = false): Promise<ProjectBoardResponse> => {
      return await withBrowserCache('project-board', browserCacheTtl.board, async () => {
        // forceRefresh раньше управлял только этим браузерным кэшем — сам
        // запрос уходил без параметров, и бэкенд отдавал свой серверный кэш
        // независимо от кнопки «Обновить». withRefreshParam (см.
        // frontend/app/utils/apiCache.ts, тот же приём, что и у
        // getProjectBoardMeta) сообщает бэкенду, что нужно обойти именно его,
        // серверный, кэш — иначе он per-процессный и не видит сброс, который
        // сделал другой процесс бэкенда (Блокер 2 финального ревью).
        return await $api(withRefreshParam('/api/project-board', forceRefresh), {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const getProjectBoardMeta = async (forceRefresh = false): Promise<ProjectBoardMetaPayload> => {
      const scope = 'project-board-meta'

      if (!forceRefresh) {
        const cached = readCache<ProjectBoardMetaPayload>(scope)
        if (hasProjectBoardMetaPayload(cached)) {
          return cached
        }
        clearCache(scope)
      }

      // forceRefresh раньше управлял только этим браузерным кэшем — сам
      // запрос уходил без параметров, и бэкенд отдавал свой серверный кэш
      // (6 часов) независимо от кнопки «Обновить справочники». withRefreshParam
      // (frontend/app/utils/apiCache.ts) сообщает бэкенду, что нужно
      // принудительно перечитать источники — тот же ?refresh=1, что и раньше,
      // теперь общий с getProjectBoard/getHomepagePortfolio.
      const url = withRefreshParam('/api/project-board/meta', forceRefresh)
      const value = await $api<ProjectBoardMetaPayload>(url, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })

      if (hasProjectBoardMetaPayload(value)) {
        writeCache(scope, value, browserCacheTtl.meta)
      } else {
        clearCache(scope)
      }

      return value
    }

    const getProjectBoardCard = async (projectId: string): Promise<ProjectBoardResponse['cards'][number] | null> => {
      const normalizedProjectId = String(projectId || '').trim()
      if (!normalizedProjectId) {
        return null
      }

      const response = await $api<{ card?: ProjectBoardResponse['cards'][number] | null }>(`/api/project-board/card?project_id=${encodeURIComponent(normalizedProjectId)}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })

      return response.card || null
    }

    // Поиск компаний по мере ввода (CompanySearchService на бэкенде, живой
    // серверный фильтр в Битриксе — не локальный обход). НЕ кэшируем на
    // клиенте: кэш по строке запроса уже живёт на бэкенде (5 минут), а тут
    // запрос меняется на каждый ввод — локальный кэш только раздувал бы
    // память браузера записями, которые почти никогда не переиспользуются.
    // Эндпоинт лимитирован (@rate_limit("company_search", 60, 60) —
    // 60 запросов/минуту на сотрудника): при превышении бросает обычную
    // ofetch-ошибку HTTP 429, а не эту форму ответа — вызывающий код
    // (SearchableSelect) обязан ловить её отдельно от success-ответа с
    // failed=true, см. frontend/app/utils/companySearch.ts.
    const searchCompanies = async (query: string, limit = 50): Promise<CompanySearchResult> => {
      const params = new URLSearchParams({ q: query, limit: String(limit) })
      return await $api<CompanySearchResult>(`/api/project-board/companies/search?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    // Свои юрлица — маленький список (серверный фильтр IS_MY_COMPANY),
    // кэшируется на бэкенде на 6 часов. Намеренно НЕ берём его из
    // getProjectBoardMeta(): там общий справочник компаний доски (уже не
    // полный справочник портала, но другого назначения — компании-клиенты,
    // встречавшиеся в карточках проектов), а не список собственных юрлиц.
    const getMyCompanies = async (): Promise<MyCompaniesResult> => {
      return await $api<MyCompaniesResult>('/api/project-board/my-companies', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    // region БДДС по проектам ////
    //
    // Ручки включены (этап 1). Все закрыты подпиской портала на сервере —
    // @feature_required('bdds'), в том числе на чтении: при выключенной
    // подписке они отвечают 403 с кодом feature_disabled, и экран показывает
    // ту же заглушку с замком, что и до появления функции.
    //
    // Кэша у этих ручек нет намеренно, как и у «Счёта и акта»: БДДС — про
    // деньги, и показать вчерашний остаток бюджета из localStorage хуже, чем
    // подождать запрос.

    /**
     * Операции «поступление/списание» смарт-процесса портала, страницей.
     *
     * Постраничность серверная (offset), а не «загрузить всё и нарезать на
     * клиенте»: операций у портала могут быть тысячи, и тянуть их целиком в
     * браузер ради двадцати видимых строк незачем.
     */
    const getFinanceOperations = async (
      params: FinanceOperationsQuery
    ): Promise<FinanceOperationsResponse> => {
      const search = new URLSearchParams()
      if (params.project_item_id) {
        search.set('project_item_id', String(params.project_item_id))
      }
      if (params.deal_id) {
        search.set('deal_id', String(params.deal_id))
      }
      if (params.limit && Number(params.limit) > 0) {
        search.set('limit', String(params.limit))
      }
      if (params.offset && Number(params.offset) > 0) {
        search.set('offset', String(params.offset))
      }
      if (params.date_from) {
        search.set('date_from', String(params.date_from))
      }
      if (params.date_to) {
        search.set('date_to', String(params.date_to))
      }
      if (params.operation_type) {
        search.set('operation_type', String(params.operation_type))
      }
      if (params.totals) {
        search.set('totals', '1')
      }

      const query = search.toString()
      return await $api<FinanceOperationsResponse>(`/api/finance-operations${query ? `?${query}` : ''}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    /**
     * Создание операции. Идемпотентность — на сервере (SHA-256 от полей),
     * повтор возвращает status=duplicate, а не вторую операцию.
     *
     * Сбрасываем кэш доски и главной: финансовый результат проекта считается
     * из этих же операций, и оставить там прежнее число значило бы показать
     * две разные цифры на двух экранах одного приложения.
     */
    const createFinanceOperation = async (payload: FinanceOperationCreatePayload): Promise<{
      status: string
      operation?: FinanceOperationRecord
      idempotency_key?: string
    }> => {
      const result = await $api('/api/finance-operations/create', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify(payload)
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result as {
        status: string
        operation?: FinanceOperationRecord
        idempotency_key?: string
      }
    }

    /** Реестр проектов с бюджетами: строки, итог по портфелю, пороги. */
    const getBddsProjects = async (includeArchived = false): Promise<BddsProjectsResponse> => {
      const query = includeArchived ? '?archived=1' : ''
      return await $api<BddsProjectsResponse>(`/api/bdds/projects${query}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    /** Бюджет одного проекта: показатели, прогноз, последние операции. */
    const getBddsProject = async (projectId: string): Promise<BddsProjectResponse> => {
      return await $api<BddsProjectResponse>(`/api/bdds/projects/${encodeURIComponent(projectId)}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getHomepagePortfolio = async (forceRefresh = false): Promise<unknown> => {
      return await withBrowserCache('homepage-portfolio', browserCacheTtl.homepage, async () => {
        // См. комментарий в getProjectBoard — тот же приём и та же причина
        // (Блокер 2 финального ревью): без параметра форсится только браузерный
        // кэш, серверный (per-процессный) остаётся стухшим до TTL.
        return await $api(withRefreshParam('/api/homepage/portfolio', forceRefresh), {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const getSupportStatus = async (forceRefresh = false): Promise<unknown> => {
      return await withBrowserCache('support-status', browserCacheTtl.support, async () => {
        return await $api('/api/support/status', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const connectSupportLine = async (): Promise<unknown> => {
      const result = await $api('/api/support/connect', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
      clearCache('support-status')
      writeCache('support-status', result, browserCacheTtl.support)
      return result
    }

    const syncProjectCards = async (incrementalSinceMinutes?: number): Promise<unknown> => {
      const query = incrementalSinceMinutes && incrementalSinceMinutes > 0
        ? `?incremental_since_minutes=${encodeURIComponent(String(incrementalSinceMinutes))}`
        : ''
      const result = await $api(`/api/project-board/sync${query}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
      clearCache('project-board', 'project-board-meta', 'homepage-portfolio', 'filter-projects')
      return result
    }

    // Кнопка «Создать проект»: компания -> группа в Задачах -> карточка
    // смарт-процесса (project_creation_service.ProjectCreationService.create).
    // Идемпотентно: повторный вызов с теми же данными достраивает только
    // недостающие шаги (ProjectCreationResult.done=false не значит ошибку
    // сети — см. типы в ~/types/project-creation). Бэкенд сам ловит свои
    // исключения и всегда отвечает 200 с частичным результатом, поэтому
    // здесь нет отдельной обработки ошибок шагов — только транспорт.
    const createProject = async (form: ProjectCreationForm): Promise<ProjectCreationResult> => {
      const result = await $api<ProjectCreationResult>('/api/project-board/create', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: form
      })
      clearCache('project-board', 'project-board-meta', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const updateProjectCard = async (payload: Record<string, unknown>): Promise<unknown> => {
      const result = await $api('/api/project-board/update', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify(payload)
      })
      clearCache('project-board', 'project-board-meta', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const updateProjectStage = async (projectId: string, stage: string): Promise<unknown> => {
      const result = await $api('/api/project-board/update-stage', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify({
          project_id: projectId,
          stage
        })
      })
      clearCache('project-board', 'homepage-portfolio')
      return result
    }

    const archiveProject = async (projectId: string, isArchived: boolean): Promise<unknown> => {
      const result = await $api('/api/project-board/archive', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify({
          project_id: projectId,
          is_archived: isArchived
        })
      })
      clearCache('project-board', 'project-board-meta', 'homepage-portfolio', 'filter-projects')
      return result
    }

    /*
      Транспорта для /api/project-board/run-daily-check тут больше нет.

      Ручка на бэкенде осталась (views.run_project_board_daily_check), но
      фронт её не зовёт: ту же проверку статусов простоя синк делает сам в
      конце своей работы — ProjectSyncService.sync вызывает
      ProjectStageAutomationService.run_daily_check и отдаёт её счётчики в
      составе своего ответа, а доска показывает их в сообщении о синке.
      Отдельная кнопка «Проверить статусы» в шапке доски предлагала нажать
      вручную уже сделанное, поэтому убрана вместе с этим методом.
    */

    /**
     * Прогон уведомлений о риске и перерасходе бюджета.
     *
     * Ручка ПИШУЩАЯ: рассылает уведомления в портал. Без параметров — по
     * всему портфелю; project_ids сужают прогон до нужных проектов.
     * Выключатель — настройка портала «Уведомления о бюджете»: при ней
     * ответ приходит со status=disabled и ничего не отправляется.
     */
    const runProjectBudgetNotifier = async (payload?: {
      project_ids?: string[]
      project_item_ids?: string[]
    }): Promise<BddsNotifierRunResult> => {
      return await $api<BddsNotifierRunResult>('/api/project-budget/notify', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload || {})
      })
    }

    const runProjectSpaBackfill = async (): Promise<unknown> => {
      const result = await $api('/api/project-spa/backfill-timesheet', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const getCompaniesForProjectBinding = async (forceRefresh = false): Promise<FilterOption[]> => {
      const meta = await getProjectBoardMeta(forceRefresh)
      const companies = meta.directories?.companies || meta.companies || []
      return companies.map(company => ({
        id: company.id,
        name: String(company.name ?? ''),
        inn: company.inn ?? null,
        search_text: company.search_text ?? null,
      }))
    }

    const getBitrixInternalLists = async (iblockTypeId: string = 'lists', forceRefresh = false): Promise<unknown[]> => {
      return await withBrowserCache(`bitrix-lists:${iblockTypeId}`, browserCacheTtl.lists, async () => {
        const response = await $api<{ lists?: unknown[] }>(`/api/bitrix/internal-lists?iblockTypeId=${encodeURIComponent(iblockTypeId)}`, {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
        return response.lists || []
      }, forceRefresh)
    }

    const exportRawData = async (dateFrom: string, dateTo: string, dateType: string, fields: string[]): Promise<Blob> => {
      return await $api('/api/export-raw-data', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: {
            date_from: dateFrom,
            date_to: dateTo,
            date_type: dateType,
            fields: fields
        },
        responseType: 'blob'
      })
    }

    const init = async (b24: B24Frame) => {
      $b24 = b24

      // Токен ещё живой — второй getToken на том же открытии не нужен.
      if (isTokenFresh()) {
        return
      }

      // Дедупликация: index.client.vue и task.vue монтируются подряд, их initApp
      // могут перекрыться по времени. Без общего промиса это снова два запроса.
      if (tokenRequest) {
        await tokenRequest
        return
      }

      tokenRequest = reinitToken().finally(() => {
        tokenRequest = null
      })
      await tokenRequest
    }

    const reinitToken = async () => {
      if ($b24 === null) {
        console.error('B24 non init. Use api.init()')
        return
      }

      const authData = $b24.auth.getAuthData()

      if (authData === false) {
        throw new Error('Some problem with auth. See App logic')
      }

      const user = useUserStore()
      const appSettings = useAppSettingsStore()

      const response = await getToken({
        DOMAIN: withoutTrailingSlash(authData.domain).replace('https://', '').replace('http://', ''),
        PROTOCOL: authData.domain.includes('https://') ? 1 : 0,
        LANG: $b24.getLang(),
        APP_SID: $b24.getAppSid(),
        AUTH_ID: authData.access_token,
        AUTH_EXPIRES: authData.expires_in,
        REFRESH_ID: authData.refresh_token,
        REFRESH_TOKEN: authData.refresh_token,
        member_id: authData.member_id,
        user_id: user.id,
        status: appSettings.status
      })

      tokenJWT.value = response.token
      tokenExpiresAtMs = readJwtExpiryMs(response.token)
    }

    // Configuration
    const getConfiguration = async (forceRefresh = false): Promise<AppConfigurationPayload> => {
      return await withBrowserCache('app-configuration', browserCacheTtl.config, async () => {
        return await $api('/api/configuration', {
          headers: { Authorization: `Bearer ${tokenJWT.value}` }
        })
      }, forceRefresh)
    }

    /**
     * Сохранение конфигурации. Тело — ВСЯ конфигурация под ключом `config`:
     * сервер пишет её в app.option одной строкой, и частичный объект затёр
     * бы остальные настройки.
     *
     * `scope: 'finance'` — отдельное сохранение «Доходов-расходов» с экрана
     * сопоставления: сервер не запускает для него проверку и синхронизацию
     * проектов, если проектная часть не менялась (см.
     * FINANCE_CONFIG_SAVE_SCOPE в utils/fieldMapping.ts).
     */
    const saveConfiguration = async (
      config: AppConfigurationPayload,
      options: { scope?: 'finance' } = {}
    ): Promise<SaveConfigurationResponse> => {
      const result = await $api<SaveConfigurationResponse>('/api/configuration/save', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify(options.scope ? { config, scope: options.scope } : { config })
      })
      clearCache('app-configuration', 'project-board-meta', 'homepage-portfolio', 'bitrix-lists:lists', 'bitrix-lists:lists_socnet')
      return result
    }

    const getSmartProcesses = async (): Promise<{ types: SmartProcessOption[] }> => {
      return await $api('/api/smart-processes', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getSpFields = async (entityTypeId: number): Promise<{ fields: SmartProcessFieldOption[] }> => {
      return await $api(`/api/smart-processes/fields?entityTypeId=${entityTypeId}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getProjectSpaValidation = async (): Promise<ProjectSpaValidationPayload> => {
      return await $api('/api/project-spa/validation', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    // Валидация смарт-процесса «Доходы-расходы (App)» остаётся выключенной, и
    // это не забытая заглушка: её смысл появится на ЭТАПЕ 2, когда у операции
    // добавится десятое поле «статья ДДС» и проверять станет что. Сегодня
    // операции читаются и пишутся (getFinanceOperations выше), а неполное
    // сопоставление полей приходит кодом finance_spa_not_configured прямо
    // оттуда. Из интерфейса эта функция не вызывается.
    const getFinanceSpaValidation = async (): Promise<FinanceSpaValidationPayload> => {
      throw new Error('Валидация смарт-процесса «Доходы-расходы» появится на этапе 2 (статьи ДДС): endpoint /api/finance-spa/validation выключен.')
      /*
      return await $api('/api/finance-spa/validation', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
      */
    }

    const createSmartProcess = async (mappingType: MappingType = 'timesheet'): Promise<SmartProcessCreateResponse> => {
      const result = await $api('/api/smart-processes/create', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ mappingType })
      })
      clearCache('app-configuration')
      return result as SmartProcessCreateResponse
    }

    const createFields = async (
      entityTypeId: number,
      mappingType: MappingType = 'timesheet'
    ): Promise<SmartProcessCreateResponse> => {
      const result = await $api('/api/smart-processes/create-fields', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ entityTypeId, mappingType })
      })
      clearCache('app-configuration')
      return result as SmartProcessCreateResponse
    }

    const createMappedField = async (
      entityTypeId: number,
      fieldKey: string,
      mappingType: MappingType
    ): Promise<MappedFieldCreateResponse> => {
      const result = await $api('/api/smart-processes/create-field', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          entityTypeId,
          fieldKey,
          mappingType
        })
      })
      clearCache('app-configuration')
      return result as MappedFieldCreateResponse
    }

    const getRequestLogs = async (page: number = 1, limit: number = 50): Promise<unknown> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      return await $api(`/api/logs/requests?${params.toString()}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getSystemLogs = async (
      page: number = 1,
      limit: number = 50,
      options?: {
        module?: string
        level?: string
      }
    ): Promise<unknown> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      if (options?.module) {
        params.append('module', options.module)
      }
      if (options?.level) {
        params.append('level', options.level)
      }
      return await $api(`/api/logs/system?${params.toString()}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }


    // region Счёт и акт ////
    // Контракт: docs/superpowers/specs/2026-09-12-billing-mvp-contract.md.
    // Ни одной ручки сверх контракта здесь нет и быть не должно: бэкенд пишется
    // по тому же документу, и «удобный» лишний адрес с фронта просто получит 404.
    //
    // Кэша у этих ручек нет намеренно (кроме /api/features, см. ниже): реестр и
    // карточка документа — про деньги, и показать вчерашнюю сумму из
    // localStorage хуже, чем подождать запрос.

    /**
     * Состояния платных функций портала.
     *
     * Единственная ручка «Счёта и акта», которую зовёт бутстрап приложения
     * (useBillingFeature -> initApp), поэтому запрос кэшируется в браузере на
     * несколько минут: подписка меняется management-командой, а не по ходу
     * работы, и дёргать её на каждой навигации незачем.
     */
    const getFeatures = async (forceRefresh = false): Promise<PortalFeaturesPayload> => {
      return await withBrowserCache('portal-features', browserCacheTtl.config, async () => {
        return await $api<PortalFeaturesPayload>('/api/features', {
          headers: { Authorization: `Bearer ${tokenJWT.value}` }
        })
      }, forceRefresh)
    }

    /**
     * Роли и права (main/roles.py). Кэша нет ни у одной ручки: права
     * меняются назначением на соседнем экране, и вчерашняя роль из
     * localStorage показала бы кнопку, которую сервер уже не пропустит.
     */
    const getRolesMe = async (): Promise<unknown> => {
      return await $api('/api/roles/me', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getRoles = async (): Promise<Record<string, unknown>> => {
      return await $api('/api/roles', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const assignRole = async (userId: string, role: string): Promise<Record<string, unknown>> => {
      return await $api('/api/roles/assign', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: { user_id: userId, role },
      })
    }

    /** Собрать строки и предупреждения по фильтру. Ничего не пишет. */
    const previewBillingDocument = async (filter: BillingFilterBody): Promise<BillingPreviewResponse> => {
      return await $api('/api/billing/preview', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: filter,
      })
    }

    /**
     * Выставить: смарт-счёт в CRM и документ у нас.
     *
     * lines[] отправляются рядом с фильтром — это строки, которые человек
     * утвердил в предпросмотре (исключённые убраны, цены и текст могли быть
     * поправлены). Без них правки предпросмотра до сервера не доедут.
     *
     * 409 здесь ШТАТНЫЙ ответ (контракт, правило 8): повторный запрос с тем же
     * набором списаний упирается в частичный уникальный индекс и возвращает
     * ссылку на существующий документ. Ошибку не глотаем — её разбирает
     * describeBillingError и показывает ссылкой, а не «ошибкой сервера».
     */
    const createBillingDocument = async (
      filter: BillingFilterBody,
      lines: BillingLinePayload[]
    ): Promise<BillingDocumentDetail> => {
      return await $api('/api/billing/documents', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: { ...filter, lines },
      })
    }

    /** Реестр документов: фильтр по клиенту, периоду и статусу. */
    const getBillingDocuments = async (params: URLSearchParams): Promise<BillingDocumentsResponse> => {
      const query = params.toString()

      return await $api(`/api/billing/documents${query ? `?${query}` : ''}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    /** Карточка: документ, строки, потреблённые списания и расхождения. */
    const getBillingDocument = async (id: string | number): Promise<BillingDocumentDetail> => {
      return await $api(`/api/billing/documents/${encodeURIComponent(String(id))}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    /** Отменить документ и освободить списания. Причина обязательна. */
    const cancelBillingDocument = async (
      id: string | number,
      reason: string
    ): Promise<BillingDocumentDetail> => {
      return await $api(`/api/billing/documents/${encodeURIComponent(String(id))}/cancel`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: { reason },
      })
    }

    /** Напечатать акт по счёту (номер и дата акта равны номеру и дате счёта). */
    const printBillingAct = async (id: string | number): Promise<BillingDocumentDetail> => {
      return await $api(`/api/billing/documents/${encodeURIComponent(String(id))}/act`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
      })
    }

    /**
     * Напечатать печатную форму САМОГО счёта (не акт).
     *
     * Отдельная ручка, а не параметр у печати акта: шаблоны разные, отказы
     * разные, и отказ одного не должен отменять уже напечатанное другое.
     * Шаблон берётся из настроек приложения; не выбран — сервер отвечает
     * кодом invoice_template_missing, и это разбирает describeBillingError.
     */
    const printBillingInvoiceForm = async (id: string | number): Promise<BillingDocumentDetail> => {
      return await $api(`/api/billing/documents/${encodeURIComponent(String(id))}/invoice-print`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
      })
    }

    /**
     * Шаблоны генератора документов портала — для выбора в настройках.
     *
     * НЕ кэшируется в браузере, в отличие от /api/features: список открывают
     * ровно тогда, когда собираются менять настройку, и показать при этом
     * шаблон, удалённый на портале десять минут назад, — значит дать
     * сохранить мёртвый идентификатор.
     */
    const getBillingTemplates = async (): Promise<BillingTemplatesResponse> => {
      return await $api('/api/billing/templates', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    /** XLSX-детализация к акту. */
    const exportBillingDetail = async (id: string | number): Promise<Blob> => {
      return await $api(`/api/billing/documents/${encodeURIComponent(String(id))}/detail.xlsx`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        responseType: 'blob',
      })
    }
    // endregion ////

    return {
      /**
       * Есть ли рабочий токен.
       *
       * Нужен компонентам, которые живут в ЛЕЙАУТЕ и рисуются раньше
       * бутстрапа (предупреждение о ненастроенном сопоставлении полей,
       * components/common/MappingHealthBanner.vue): свой запрос оттуда ушёл
       * бы без авторизации, а тащить в лейаут вызов initApp нельзя — он
       * принадлежит странице. Такой компонент ждёт этот флаг и только потом
       * спрашивает своё.
       */
      hasToken: computed(() => Boolean(tokenJWT.value)),
      init,
      getEnum,
      getList,
      postInstall,
      getReportEmployeeProject,
      getReportProjectEmployee,
      getReportProjectTaskEmployee,
      exportReportProjectTaskEmployee,
      exportReportEmployeeProject,
      exportReportProjectEmployee,
      exportReportDailyWorkload,
      exportReportRevenueLeakage,
      exportReportTimeEntryDiscipline,
      exportReportFocusAnalysis,
      scanInnBackfill,
      applyInnBackfill,
      resolveInnProjectItems,
      getProjectsHealth,
      getReportDailyWorkload,
      getReportRevenueLeakage,
      getReportTimeEntryDiscipline,
      getReportFocusAnalysis,
      getPeriods,
      checkPeriod,
      getPeriodCheckDetails,
      fixPeriodFinding,
      closePeriod,
      closePeriodsBulk,
      reopenPeriod,
      getLateArrivals,
      syncTimesheets,
      createTimesheetEntry,
      updateTimesheetEntry,
      getTimesheetSyncStatus,
      getTimesheetsList,
      getUsers,
      getRolesMe,
      getRoles,
      assignRole,
      getProjectBoard,
      getProjectBoardMeta,
      getProjectBoardCard,
      searchCompanies,
      getMyCompanies,
      createProject,
      getFinanceOperations,
      createFinanceOperation,
      getBddsProjects,
      getBddsProject,
      getHomepagePortfolio,
      getSupportStatus,
      connectSupportLine,
      syncProjectCards,
      updateProjectCard,
      updateProjectStage,
      archiveProject,
      runProjectBudgetNotifier,
      runProjectSpaBackfill,
      getCompaniesForProjectBinding,
      getBitrixInternalLists,
      getFilterOptions,
      getFilterEmployees,
      getFilterProjects,
      exportRawData,

      getConfiguration,
      saveConfiguration,
      getSmartProcesses,
      getSpFields,
      getProjectSpaValidation,
      getFinanceSpaValidation,
      getRequestLogs,
      getSystemLogs,
      createSmartProcess,
      createFields,
      createMappedField,

      getFeatures,
      previewBillingDocument,
      createBillingDocument,
      getBillingDocuments,
      getBillingDocument,
      cancelBillingDocument,
      printBillingAct,
      printBillingInvoiceForm,
      getBillingTemplates,
      exportBillingDetail
    }
  }
)
