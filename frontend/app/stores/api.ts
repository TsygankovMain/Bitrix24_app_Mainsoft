import type { B24Frame } from '@bitrix24/b24jssdk'
import { withoutTrailingSlash } from 'ufo'

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
      return await $api('/api/get-filter-options', {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportEmployeeProject = async (dateFrom?: string, dateTo?: string, empIds?: string[], projIds?: string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      if (empIds && empIds.length) empIds.forEach(id => params.append('employee_ids[]', id))
      if (projIds && projIds.length) projIds.forEach(id => params.append('project_ids[]', id))

      return await $api(`/api/report-employee-project?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportProjectEmployee = async (dateFrom?: string, dateTo?: string, empIds?: string[], projIds?: string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      if (empIds && empIds.length) empIds.forEach(id => params.append('employee_ids[]', id))
      if (projIds && projIds.length) projIds.forEach(id => params.append('project_ids[]', id))

      return await $api(`/api/report-project-employee?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportDailyWorkload = async (dateFrom?: string, dateTo?: string, empIds?: string[], projIds?: string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      if (empIds && empIds.length) empIds.forEach(id => params.append('employee_ids[]', id))
      if (projIds && projIds.length) projIds.forEach(id => params.append('project_ids[]', id))

      return await $api(`/api/report-daily-workload?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getReportProjectTaskEmployee = async (dateFrom?: string, dateTo?: string, empIds?: string[], projIds?: string[]): Promise<any> => {
      const params = new URLSearchParams()
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      if (empIds && empIds.length) empIds.forEach(id => params.append('employee_ids[]', id))
      if (projIds && projIds.length) projIds.forEach(id => params.append('project_ids[]', id))

      return await $api(`/api/report-project-task-employee?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const syncTimesheets = async (): Promise<{ status: string; count: number }> => {
      return await $api('/api/sync-timesheets', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
      })
    }

    const getTimesheetsList = async (page: number = 1, limit: number = 50): Promise<any> => {
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())

      return await $api(`/api/timesheets?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`
        }
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
    const getConfiguration = async (): Promise<any> => {
      return await $api('/api/configuration', {
        headers: { Authorization: `Bearer ${tokenJWT.value}` }
      })
    }

    const saveConfiguration = async (config: any): Promise<any> => {
      return await $api('/api/configuration/save', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokenJWT.value}` },
        body: JSON.stringify({ config })
      })
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
      return await $api('/api/smart-processes/create', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      })
    }

    const createFields = async (entityTypeId: number): Promise<{ status: string; config: any }> => {
      return await $api('/api/smart-processes/create-fields', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenJWT.value}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ entityTypeId })
      })
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
      syncTimesheets,
      getTimesheetsList,
      getFilterOptions,

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
