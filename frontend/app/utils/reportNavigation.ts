export type ReportRouteName =
  | 'employee'
  | 'project'
  | 'project-task'
  | 'daily'
  | 'revenue-leakage'
  | 'time-discipline'
  | 'focus-analysis'

export type ReportRoutePayload = {
  report: ReportRouteName
  projectId?: string | number | null
  projectName?: string | null
  autogenerate?: boolean
}

const REPORT_ROUTES: Record<ReportRouteName, string> = {
  employee: '/reports/employee',
  project: '/reports/project',
  'project-task': '/reports/project-task',
  daily: '/reports/daily',
  'revenue-leakage': '/reports/revenue-leakage',
  'time-discipline': '/reports/time-discipline',
  'focus-analysis': '/reports/focus-analysis',
}

export function buildReportRouteLocation(target: ReportRouteName | ReportRoutePayload) {
  const payload = typeof target === 'string'
    ? { report: target }
    : target

  const path = REPORT_ROUTES[payload.report] || '/'
  const query: Record<string, string> = {}
  const projectId = String(payload.projectId || '').trim()
  const projectName = String(payload.projectName || '').trim()

  if (projectId) {
    query.project_id = projectId
    query.project_mode = 'include'

    if (projectName) {
      query.project_name = projectName
    }

    if (payload.autogenerate === true) {
      query.autogenerate = '1'
    }
  }

  return Object.keys(query).length > 0
    ? { path, query }
    : { path }
}

export function readProjectReportPreset(query: Record<string, unknown>) {
  const projectIdValue = query.project_id
  const projectIdsValue = query.project_ids
  const projectNameValue = query.project_name
  const autogenerateValue = query.autogenerate

  const rawProjectIds = Array.isArray(projectIdValue)
    ? projectIdValue
    : Array.isArray(projectIdsValue)
      ? projectIdsValue
      : projectIdValue
        ? [projectIdValue]
        : projectIdsValue
          ? String(projectIdsValue).split(',')
          : []

  const projectIds = Array.from(
    new Set(
      rawProjectIds
        .map(value => String(value || '').trim())
        .filter(Boolean)
    )
  )

  const projectName = Array.isArray(projectNameValue)
    ? String(projectNameValue[0] || '').trim()
    : String(projectNameValue || '').trim()

  const autogenerate = Array.isArray(autogenerateValue)
    ? String(autogenerateValue[0] || '') === '1'
    : String(autogenerateValue || '') === '1'

  return {
    projectIds,
    projectName,
    autogenerate,
  }
}
