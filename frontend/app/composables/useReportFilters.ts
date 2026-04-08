import { getCurrentMonthRange } from '~/utils/reportDateRange'
import { applyProjectPresetToFilters } from '~/utils/reportFilters'
import type { FilterMode, FilterValue, ReportFilterOptions } from '~/types/report'

export function useReportFilters() {
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

  const employeeFilter = computed<FilterValue>(() => ({
    ids: selectedEmployees.value,
    mode: employeeFilterMode.value
  }))

  const projectFilter = computed<FilterValue>(() => ({
    ids: selectedProjects.value,
    mode: projectFilterMode.value
  }))

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
