import type { B24Frame } from '@bitrix24/b24jssdk'
import { withoutTrailingSlash } from 'ufo'
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
import type { ProjectBoardMetaPayload, ProjectBoardResponse } from '~/types/project-board'
import type { InnScanResult, InnApplyItem, InnApplyResult, InnProjectItemsResult, ProjectsHealthResult } from '~/types/inn'

type SaveConfigurationResponse = {
  status?: string
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
}

type FinanceOperationCreatePayload = {
  project_item_id: string
  deal_id?: string | null
  operation_type: 'income' | 'expense' | string
  amount: number
  currency?: string | null
  operation_date: string
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

    const isInitTokenJWT = computed(() => {
      return tokenJWT.value.length > 2
    })

    const $api = $fetch.create({
      baseURL: apiUrl,
      headers: {
        'Content-Type': 'application/json'
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

    // Health check
    const checkHealth = async (): Promise<{
      status: string
      backend: string
      timestamp: number
    }> => {
      try {
        return await $api('/api/health', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      } catch {
        throw new Error('Backend health check failed')
      }
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

    const postInstall = async (data: Record<string, any>): Promise<Record<string, any>> => {
      return await $api('/api/install', {
        method: 'POST',
        body: data,
      })
    }

    const getToken = async (data: Record<string, any>): Promise<{ token: string }> => {
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

    const syncTimesheets = async (dateFrom?: string, dateTo?: string): Promise<{ status: string; count: number }> => {
      const result = await $api<{ status: string, count: number }>('/api/sync-timesheets', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        ...(dateFrom && dateTo ? { body: { date_from: dateFrom, date_to: dateTo } } : {})
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result
    }

    const getTimesheetsList = async (page: number = 1, limit: number = 50, createdFrom?: string, createdTo?: string): Promise<any> => {
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

    const getProjectBoard = async (forceRefresh = false): Promise<ProjectBoardResponse> => {
      return await withBrowserCache('project-board', browserCacheTtl.board, async () => {
        return await $api('/api/project-board', {
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

      const value = await $api<ProjectBoardMetaPayload>('/api/project-board/meta', {
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

    // --- Финансовый функционал (в планах) изолирован ---
    // Бэкенд-endpoint `/api/finance-operations` отключён (см. backends/python/api/main/urls.py).
    // Заглушка не выполняет сетевой вызов, чтобы не было битых запросов.
    // Для восстановления: удалить throw и раскомментировать оригинальное тело ниже.
    const getFinanceOperations = async (_params: {
      project_item_id?: string | null
      deal_id?: string | null
      limit?: number
    }): Promise<FinanceOperationsResponse> => {
      throw new Error('Финансовый функционал в разработке (в планах): endpoint /api/finance-operations отключён.')
      /*
      const search = new URLSearchParams()
      if (_params.project_item_id) {
        search.set('project_item_id', String(_params.project_item_id))
      }
      if (_params.deal_id) {
        search.set('deal_id', String(_params.deal_id))
      }
      if (_params.limit && Number(_params.limit) > 0) {
        search.set('limit', String(_params.limit))
      }

      const query = search.toString()
      return await $api<FinanceOperationsResponse>(`/api/finance-operations${query ? `?${query}` : ''}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
      */
    }

    // --- Финансовый функционал (в планах) изолирован ---
    // Бэкенд-endpoint `/api/finance-operations/create` отключён (см. backends/python/api/main/urls.py).
    // Для восстановления: удалить throw и раскомментировать оригинальное тело ниже.
    const createFinanceOperation = async (_payload: FinanceOperationCreatePayload): Promise<{
      status: string
      operation?: FinanceOperationRecord
      idempotency_key?: string
    }> => {
      throw new Error('Финансовый функционал в разработке (в планах): endpoint /api/finance-operations/create отключён.')
      /*
      const result = await $api('/api/finance-operations/create', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        },
        body: JSON.stringify(_payload)
      })
      clearCache('project-board', 'homepage-portfolio', 'filter-projects')
      return result as {
        status: string
        operation?: FinanceOperationRecord
        idempotency_key?: string
      }
      */
    }

    const getHomepagePortfolio = async (forceRefresh = false): Promise<any> => {
      return await withBrowserCache('homepage-portfolio', browserCacheTtl.homepage, async () => {
        return await $api('/api/homepage/portfolio', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const getSupportStatus = async (forceRefresh = false): Promise<any> => {
      return await withBrowserCache('support-status', browserCacheTtl.support, async () => {
        return await $api('/api/support/status', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const connectSupportLine = async (): Promise<any> => {
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

    const syncProjectCards = async (incrementalSinceMinutes?: number): Promise<any> => {
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

    const updateProjectCard = async (payload: Record<string, any>): Promise<any> => {
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

    const updateProjectStage = async (projectId: string, stage: string): Promise<any> => {
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

    const archiveProject = async (projectId: string, isArchived: boolean): Promise<any> => {
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

    const runProjectBoardDailyCheck = async (): Promise<any> => {
      const result = await $api('/api/project-board/run-daily-check', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
      clearCache('project-board', 'homepage-portfolio')
      return result
    }

    // --- Финансовый функционал (в планах) изолирован ---
    // Бэкенд-endpoint `/api/project-budget/notify` отключён (см. backends/python/api/main/urls.py).
    // В фронте больше не вызывается; заглушка оставлена для лёгкого восстановления.
    const runProjectBudgetNotifier = async (_payload?: {
      project_ids?: string[]
      project_item_ids?: string[]
    }): Promise<any> => {
      throw new Error('Финансовый функционал в разработке (в планах): endpoint /api/project-budget/notify отключён.')
      /*
      return await $api('/api/project-budget/notify', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(_payload || {})
      })
      */
    }

    const runProjectSpaBackfill = async (): Promise<any> => {
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

    const getBitrixInternalLists = async (iblockTypeId: string = 'lists', forceRefresh = false): Promise<any[]> => {
      return await withBrowserCache(`bitrix-lists:${iblockTypeId}`, browserCacheTtl.lists, async () => {
        const response = await $api<{ lists?: any[] }>(`/api/bitrix/internal-lists?iblockTypeId=${encodeURIComponent(iblockTypeId)}`, {
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
      await reinitToken()
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
    }

    // Configuration
    const getConfiguration = async (forceRefresh = false): Promise<AppConfigurationPayload> => {
      return await withBrowserCache('app-configuration', browserCacheTtl.config, async () => {
        return await $api('/api/configuration', {
          headers: { Authorization: `Bearer ${tokenJWT.value}` }
        })
      }, forceRefresh)
    }

    const saveConfiguration = async (config: AppConfigurationPayload): Promise<SaveConfigurationResponse> => {
      const result = await $api<SaveConfigurationResponse>('/api/configuration/save', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify({ config })
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

    // --- Финансовый функционал (в планах) изолирован ---
    // Бэкенд-endpoint `/api/finance-spa/validation` отключён (см. backends/python/api/main/urls.py).
    // В фронте больше не вызывается; заглушка оставлена для лёгкого восстановления.
    const getFinanceSpaValidation = async (): Promise<FinanceSpaValidationPayload> => {
      throw new Error('Финансовый функционал в разработке (в планах): endpoint /api/finance-spa/validation отключён.')
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

    const getRequestLogs = async (page: number = 1, limit: number = 50): Promise<any> => {
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
    ): Promise<any> => {
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

    return {
      checkHealth,
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
      syncTimesheets,
      getTimesheetsList,
      getProjectBoard,
      getProjectBoardMeta,
      getProjectBoardCard,
      getFinanceOperations,
      createFinanceOperation,
      getHomepagePortfolio,
      getSupportStatus,
      connectSupportLine,
      syncProjectCards,
      updateProjectCard,
      updateProjectStage,
      archiveProject,
      runProjectBoardDailyCheck,
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
      createMappedField
    }
  }
)
