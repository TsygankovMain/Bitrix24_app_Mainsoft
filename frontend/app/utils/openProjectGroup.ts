export function openProjectGroup(projectId?: string | number | null) {
  const normalizedProjectId = String(projectId || '').trim()
  if (!normalizedProjectId) {
    return
  }

  const path = `/workgroups/group/${normalizedProjectId}/`
  const bx24 = (window as Window & { BX24?: { openPath?: (path: string) => void } })?.BX24

  if (typeof bx24?.openPath === 'function') {
    bx24.openPath(path)
    return
  }

  window.open(path, '_blank')
}
