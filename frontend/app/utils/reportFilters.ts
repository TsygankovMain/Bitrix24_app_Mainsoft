import { readProjectReportPreset } from '~/utils/reportNavigation'
import type { FilterMode, FilterOption, FilterValue } from '~/types/report'

export function normalizeReportFilterValue(value?: FilterValue | string[]) {
  if (Array.isArray(value)) {
    return {
      ids: value.map(id => String(id)),
      mode: 'include' as FilterMode
    }
  }

  return {
    ids: (value?.ids || []).map(id => String(id)),
    mode: value?.mode === 'exclude' ? 'exclude' : 'include'
  }
}

export function buildReportSearchParams(
  dateFrom?: string,
  dateTo?: string,
  employeeFilter?: FilterValue | string[],
  projectFilter?: FilterValue | string[]
) {
  const params = new URLSearchParams()

  if (dateFrom) {
    params.append('date_from', dateFrom)
  }

  if (dateTo) {
    params.append('date_to', dateTo)
  }

  const normalizedEmployees = normalizeReportFilterValue(employeeFilter)
  const normalizedProjects = normalizeReportFilterValue(projectFilter)

  normalizedEmployees.ids.forEach(id => params.append('employee_ids[]', id))
  normalizedProjects.ids.forEach(id => params.append('project_ids[]', id))

  if (normalizedEmployees.mode === 'exclude') {
    params.append('employee_mode', 'exclude')
  }

  if (normalizedProjects.mode === 'exclude') {
    params.append('project_mode', 'exclude')
  }

  return params
}

export function injectReportOption(
  options: FilterOption[],
  option?: { id?: string | number | null; name?: string | null } | null
) {
  const optionId = String(option?.id || '').trim()
  if (!optionId) {
    return options
  }

  if (options.some(existing => String(existing.id) === optionId)) {
    return options
  }

  return [
    {
      id: optionId,
      name: String(option?.name || optionId),
    },
    ...options
  ]
}

export function applyProjectPresetToFilters(
  routeQuery: Record<string, unknown>,
  currentOptions: FilterOption[],
  updateProjects: (nextIds: string[]) => void,
  updateMode: (mode: FilterMode) => void,
  updateOptions: (nextOptions: FilterOption[]) => void
) {
  const preset = readProjectReportPreset(routeQuery)

  if (!preset.projectIds.length) {
    return false
  }

  updateProjects(preset.projectIds)
  updateMode('include')

  if (preset.projectName) {
    updateOptions(injectReportOption(currentOptions, {
      id: preset.projectIds[0],
      name: preset.projectName
    }))
  }

  return preset.autogenerate
}
