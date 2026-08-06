import { getCurrentMonthRange } from '~/utils/reportDateRange'
import { applyProjectPresetToFilters } from '~/utils/reportFilters'
import type { FilterMode, FilterValue, ReportFilterOptions } from '~/types/report'

const PERIOD_KEY = 'ms-report-period-v1'
const FILTERS_KEY_PREFIX = 'ms-report-filters-v1'

function readLocal<T>(key: string): T | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch { return null }
}
function writeLocal(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.setItem(key, JSON.stringify(value)) } catch { /* quota/private mode */ }
}
function readSession<T>(key: string): T | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch { return null }
}
function writeSession(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  try { window.sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* ignore */ }
}

export function useReportFilters(reportKey = 'default') {
  const apiStore = useApiStore()

  const dateFrom = ref('')
  const dateTo = ref('')
  const filterOptions = ref<ReportFilterOptions>({
    employees: [],
    projects: []
  })

  const selectedEmployees = ref<Array<string | number>>([])
  const selectedProjects = ref<Array<string | number>>([])
  const employeeFilterMode = ref<FilterMode>('include')
  const projectFilterMode = ref<FilterMode>('include')

  const filtersKey = `${FILTERS_KEY_PREFIX}:${reportKey}`

  // --- Восстановление сохранённого состояния (только на клиенте) ---
  const savedPeriod = readLocal<{ dateFrom: string; dateTo: string }>(PERIOD_KEY)
  if (savedPeriod && savedPeriod.dateFrom && savedPeriod.dateTo) {
    dateFrom.value = savedPeriod.dateFrom
    dateTo.value = savedPeriod.dateTo
  }
  const savedFilters = readSession<{
    employees: Array<string | number>
    projects: Array<string | number>
    employeeMode: FilterMode
    projectMode: FilterMode
  }>(filtersKey)
  if (savedFilters) {
    selectedEmployees.value = Array.isArray(savedFilters.employees) ? savedFilters.employees : []
    selectedProjects.value = Array.isArray(savedFilters.projects) ? savedFilters.projects : []
    if (savedFilters.employeeMode) employeeFilterMode.value = savedFilters.employeeMode
    if (savedFilters.projectMode) projectFilterMode.value = savedFilters.projectMode
  }

  // --- Персистентность при изменении ---
  watch([dateFrom, dateTo], ([from, to]) => {
    if (from && to) writeLocal(PERIOD_KEY, { dateFrom: from, dateTo: to })
  })
  watch(
    [selectedEmployees, selectedProjects, employeeFilterMode, projectFilterMode],
    ([emps, projs, eMode, pMode]) => {
      writeSession(filtersKey, {
        employees: emps,
        projects: projs,
        employeeMode: eMode,
        projectMode: pMode,
      })
    },
    { deep: true }
  )

  const employeeFilter = computed<FilterValue>(() => ({
    ids: selectedEmployees.value,
    mode: employeeFilterMode.value
  }))

  const projectFilter = computed<FilterValue>(() => ({
    ids: selectedProjects.value,
    mode: projectFilterMode.value
  }))

  /**
   * forceRefresh=true обходит браузерный кэш опций (localStorage, 20 минут —
   * browserCacheTtl.filters в stores/api.ts). Нужен на кнопке «Обновить»:
   * она синхронизирует read-model, и вместе с ней могли приехать проекты и
   * сотрудники, которых на момент прогрева кэша не существовало. Без этого
   * только что созданный проект не появлялся бы в фильтре до истечения TTL,
   * и обновить список было бы нечем — кнопка перестраивала только отчёт.
   */
  async function loadFilterOptions(forceRefresh = false) {
    const [employeesResult, projectsResult] = await Promise.allSettled([
      apiStore.getFilterEmployees(forceRefresh),
      apiStore.getFilterProjects(forceRefresh)
    ])

    filterOptions.value = {
      employees: employeesResult.status === 'fulfilled' ? employeesResult.value : [],
      projects: projectsResult.status === 'fulfilled' ? projectsResult.value : [],
    }
  }

  function initCurrentMonthRange() {
    // Не перетираем сохранённый период автоматически: ставим текущий месяц,
    // только если период ещё пуст (нет сохранённого).
    if (dateFrom.value && dateTo.value) return
    const range = getCurrentMonthRange()
    dateFrom.value = range.dateFrom
    dateTo.value = range.dateTo
  }

  function applyRouteProjectPreset(routeQuery: Record<string, unknown>) {
    return applyProjectPresetToFilters(
      routeQuery,
      filterOptions.value.projects,
      (nextIds) => {
        selectedProjects.value = nextIds
      },
      (mode) => {
        projectFilterMode.value = mode
      },
      (nextOptions) => {
        filterOptions.value = {
          ...filterOptions.value,
          projects: nextOptions
        }
      }
    )
  }

  return {
    dateFrom,
    dateTo,
    filterOptions,
    selectedEmployees,
    selectedProjects,
    employeeFilterMode,
    projectFilterMode,
    employeeFilter,
    projectFilter,
    loadFilterOptions,
    initCurrentMonthRange,
    applyRouteProjectPreset
  }
}
