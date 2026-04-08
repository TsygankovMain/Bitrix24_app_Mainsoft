export interface TaskWorkspaceUser {
  ID: string | number
  NAME?: string
  LAST_NAME?: string
  [key: string]: unknown
}

export interface TaskWorkspaceItem {
  id: string
  title?: string
  createdTime?: string
  hours: number
  isConsidered: boolean
  description: string
  employeeId: string | number
  employeeName: string
  date?: string
}

export interface TaskWorkspaceNode {
  taskId: string
  taskTitle: string
  parentId: string | null
  children: TaskWorkspaceNode[]
  items: TaskWorkspaceItem[]
  totalConsidered: number
  totalUnconsidered: number
  cumulativeConsidered: number
  cumulativeUnconsidered: number
}

export interface TaskWorkspaceFilters {
  employeeId?: string
  dateFrom?: string
  dateTo?: string
}

export interface TaskHierarchy {
  idPath: string[]
  titlePath: string[]
  projectId: string | null
  projectTitle: string
  ourInn: string
  clientInn: string
}
