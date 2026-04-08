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
}

export function useReportGenerator(options: UseReportGeneratorOptions = {}) {
  const apiStore = useApiStore()

  const hasGenerated = ref(false)
  const syncWarning = ref('')

  async function generateReport<T>(config: GenerateReportOptions<T>) {
    options.setLoading?.(true)
    syncWarning.value = ''

    try {
      if (config.syncTimesheets !== false) {
        try {
          await apiStore.syncTimesheets()
        } catch (error) {
          if (!config.allowSyncFallback) {
            throw error
          }

          syncWarning.value = config.syncWarningMessage || 'Не удалось обновить данные из Битрикс24. Показаны последние сохраненные данные.'
        }
      }

      const payload = await config.loader()
      hasGenerated.value = true
      return config.normalize ? config.normalize(payload) : payload
    } catch (error) {
      options.onError?.(error)
      return null
    } finally {
      options.setLoading?.(false)
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
