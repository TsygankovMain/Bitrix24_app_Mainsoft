import { useProgress } from '~/composables/useProgress'

interface UseReportGeneratorOptions {
  setLoading?: (value: boolean) => void
  onError?: (error: unknown) => void
}

interface GenerateReportOptions<T> {
  loader: () => Promise<T>
  normalize?: (payload: T) => T
  syncTimesheets?: boolean
  allowSyncFallback?: boolean
  syncWarningMessage?: string
  reportName?: string
}

function isPerfLoggingEnabled(): boolean {
  if (import.meta.dev) return true
  if (typeof window === 'undefined') return false
  try {
    return new URLSearchParams(window.location.search).has('perf')
  } catch {
    return false
  }
}

export function useReportGenerator(options: UseReportGeneratorOptions = {}) {
  const apiStore = useApiStore()
  const progress = useProgress()

  const hasGenerated = ref(false)
  const syncWarning = ref('')

  async function generateReport<T>(config: GenerateReportOptions<T>) {
    options.setLoading?.(true)
    syncWarning.value = ''

    const perfEnabled = isPerfLoggingEnabled()
    const startedAt = perfEnabled ? performance.now() : 0
    let syncMs = 0
    let fetchMs = 0

    try {
      progress.begin(
        config.reportName ? `Отчёт «${config.reportName}»: формирование…` : 'Формирование отчёта…',
        0,
        'Собираем данные из Bitrix24'
      )
      if (config.syncTimesheets !== false) {
        const syncStart = perfEnabled ? performance.now() : 0
        try {
          await apiStore.syncTimesheets()
        } catch (error) {
          if (!config.allowSyncFallback) {
            throw error
          }

          syncWarning.value = config.syncWarningMessage || 'Не удалось обновить данные из Битрикс24. Показаны последние сохраненные данные.'
        } finally {
          if (perfEnabled) {
            syncMs = performance.now() - syncStart
          }
        }
      }

      const fetchStart = perfEnabled ? performance.now() : 0
      const payload = await config.loader()
      if (perfEnabled) {
        fetchMs = performance.now() - fetchStart
      }
      hasGenerated.value = true
      return config.normalize ? config.normalize(payload) : payload
    } catch (error) {
      options.onError?.(error)
      return null
    } finally {
      if (perfEnabled) {
        const totalMs = performance.now() - startedAt
        // eslint-disable-next-line no-console
        console.info('[report-perf]', {
          report: config.reportName || 'unknown',
          sync_ms: Math.round(syncMs),
          fetch_ms: Math.round(fetchMs),
          total_ms: Math.round(totalMs),
        })
      }
      options.setLoading?.(false)
      progress.end()
    }
  }

  function resetGenerated() {
    hasGenerated.value = false
    syncWarning.value = ''
  }

  return {
    hasGenerated,
    syncWarning,
    generateReport,
    resetGenerated
  }
}
