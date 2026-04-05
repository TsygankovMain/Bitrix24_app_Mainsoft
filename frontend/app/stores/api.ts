import type { B24Frame } from '@bitrix24/b24jssdk'
import { withoutTrailingSlash } from 'ufo'

type FilterMode = 'include' | 'exclude'
type FilterValue = {
  ids?: Array<string | number>
  mode?: FilterMode
}

export const useApiStore = defineStore(
  'api',
  () => {
    let $b24: null | B24Frame = null
    const config = useRuntimeConfig()
    const apiUrl = withoutTrailingSlash(config.public.apiUrl)

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

    const hasProjectBoardMetaPayload = (value: any) => {
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
        body: JSON.stringify(data),
      })
    }

    const getToken = async (data: Record<string, any>): Promise<{ token: string }> => {
      return await $api('/api/getToken', {
        method: 'POST',
        body: JSON.stringify(data),
      })
    }

    const getFilterOptions = async (): Promise<{ employees: any[], projects: any[] }> => {
      const [employees, projects] = await Promise.all([
        getFilterEmployees(),
        getFilterProjects()
      ])

      return {
        employees,
        projects
      }
    }

    const getFilterEmployees = async (forceRefresh = false): Promise<any[]> => {
      return await withBrowserCache('filter-employees', browserCacheTtl.filters, async () => {
        const response = await $api('/api/get-filter-employees', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })

        return response.employees || []
      }, forceRefresh)
    }

    const getFilterProjects = async (forceRefresh = false): Promise<any[]> => {
      return await withBrowserCache('filter-projects', browserCacheTtl.filters, async () => {
        const response = await $api('/api/get-filter-projects', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })

        return response.projects || []
      }, forceRefresh)
    }

    const normalizeFilterValue = (value?: FilterValue | string[]): { ids: string[], mode: FilterMode } => {
      if (Array.isArray(value)) {
        return {
          ids: value.map(id => String(id)),
          mode: 'include'
        }
      }

      return {
        ids: (value?.ids || []).map(id => String(id)),
        mode: value?.mode === 'exclude' ? 'exclude' : 'include'
      }
    }

    const appendReportFilters = (
      params: URLSearchParams,
      employeeFilter?: FilterValue | string[],
      projectFilter?: FilterValue | string[]
    ) => {
      const normalizedEmployees = normalizeFilterValue(employeeFilter)
      const normalizedProjects = normalizeFilterValue(projectFilter)

      if (normalizedEmployees.ids.length) {
        normalizedEmployees.ids.forEach(id => params.append('employee_ids[]', id))
      }
      if (normalizedEmployees.mode === 'exclude') {
        params.append('employee_mode', 'exclude')
      }

      if (normalizedProjects.ids.length) {
        normalizedProjects.ids.forEach(id => params.append('project_ids[]', id))
      }
      if (normalizedProjects.mode === 'exclude') {
        params.append('project_mode', 'exclude')
      }
    }

    const getReportEmployeeProject = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-employee-project?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportProjectEmployee = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-project-employee?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportDailyWorkload = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-daily-workload?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportProjectTaskEmployee = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-project-task-employee?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportRevenueLeakage = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-revenue-leakage?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportTimeEntryDiscipline = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-time-entry-discipline?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportFocusAnalysis = async (dateFrom?: string, dateTo?: string, empIds?: FilterValue | string[], projIds?: FilterValue | string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      appendReportFilters(params, empIds, projIds)

      return await $api(`/api/report-focus-analysis?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const syncTimesheets = async (): Promise<{ status: string; count: number }> => {
      const result = await $api('/api/sync-timesheets', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
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

    const getProjectBoard = async (forceRefresh = false): Promise<any> => {
      return await withBrowserCache('project-board', browserCacheTtl.board, async () => {
        return await $api('/api/project-board', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const getProjectBoardMeta = async (forceRefresh = false): Promise<any> => {
      const scope = 'project-board-meta'

      if (!forceRefresh) {
        const cached = readCache<any>(scope)
        if (hasProjectBoardMetaPayload(cached)) {
          return cached
        }
        clearCache(scope)
      }

      const value = await $api('/api/project-board/meta', {
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

    const getHomepagePortfolio = async (forceRefresh = false): Promise<any> => {
      return await withBrowserCache('homepage-portfolio', browserCacheTtl.homepage, async () => {
        return await $api('/api/homepage/portfolio', {
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`
          }
        })
      }, forceRefresh)
    }

    const syncProjectCards = async (): Promise<any> => {
      const result = await $api('/api/project-board/sync', {
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

    const getCompaniesForProjectBinding = async (forceRefresh = false): Promise<any[]> => {
      const meta = await getProjectBoardMeta(forceRefresh)
      return meta.directories?.companies || meta.companies || []
    }

    const getBitrixInternalLists = async (iblockTypeId: string = 'lists', forceRefresh = false): Promise<any[]> => {
      return await withBrowserCache(`bitrix-lists:${iblockTypeId}`, browserCacheTtl.lists, async () => {
        const response = await $api(`/api/bitrix/internal-lists?iblockTypeId=${encodeURIComponent(iblockTypeId)}`, {
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
    const getConfiguration = async (forceRefresh = false): Promise<any> => {
      return await withBrowserCache('app-configuration', browserCacheTtl.config, async () => {
        return await $api('/api/configuration', {
          headers: { Authorization: `Bearer ${tokenJWT.value}` }
        })
      }, forceRefresh)
    }

    const saveConfiguration = async (config: any): Promise<any> => {
      const result = await $api('/api/configuration/save', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify({ config })
      })
      clearCache('app-configuration', 'project-board-meta', 'homepage-portfolio', 'bitrix-lists:lists', 'bitrix-lists:lists_socnet')
      return result
    }

    const getSmartProcesses = async (): Promise<{ types: any[] }> => {
      return await $api('/api/smart-processes', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getSpFields = async (entityTypeId: number): Promise<{ fields: any[] }> => {
      return await $api(`/api/smart-processes/fields?entityTypeId=${entityTypeId}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const createSmartProcess = async (): Promise<{ status: string; config: any }> => {
      console.log('📡 [API] createSmartProcess: calling POST /api/smart-processes/create')
      console.log('📡 [API] Token present:', !!tokenJWT.value, 'Token length:', tokenJWT.value?.length)
      try {
        const result = await $api('/api/smart-processes/create', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({})
        })
        console.log('📡 [API] createSmartProcess result:', result)
        return result as { status: string; config: any }
      } catch (err: any) {
        console.error('📡 [API] createSmartProcess FAILED:', err)
        console.error('📡 [API] err.data:', err?.data)
        console.error('📡 [API] err.status:', err?.status, err?.statusCode)
        throw err
      }
    }

    const createFields = async (entityTypeId: number): Promise<{ status: string; config: any }> => {
      console.log('📡 [API] createFields: calling POST /api/smart-processes/create-fields')
      console.log('📡 [API] entityTypeId:', entityTypeId)
      console.log('📡 [API] Token present:', !!tokenJWT.value, 'Token length:', tokenJWT.value?.length)
      console.log('📡 [API] Request body:', JSON.stringify({ entityTypeId }))
      try {
        const result = await $api('/api/smart-processes/create-fields', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${tokenJWT.value}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ entityTypeId })
        })
        console.log('📡 [API] createFields result:', result)
        return result as { status: string; config: any }
      } catch (err: any) {
        console.error('📡 [API] createFields FAILED:', err)
        console.error('📡 [API] err.data:', err?.data)
        console.error('📡 [API] err.status:', err?.status, err?.statusCode)
        throw err
      }
    }

    const getRequestLogs = async (page: number = 1, limit: number = 50): Promise<any> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      return await $api(`/api/logs/requests?${params.toString()}`, {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const getSystemLogs = async (page: number = 1, limit: number = 50): Promise<any> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
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
      getReportDailyWorkload,
      getReportRevenueLeakage,
      getReportTimeEntryDiscipline,
      getReportFocusAnalysis,
      syncTimesheets,
      getTimesheetsList,
      getProjectBoard,
      getProjectBoardMeta,
      getHomepagePortfolio,
      syncProjectCards,
      updateProjectCard,
      updateProjectStage,
      archiveProject,
      runProjectBoardDailyCheck,
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
      getRequestLogs,
      getSystemLogs,
      createSmartProcess,
      createFields
    }
  }
)
