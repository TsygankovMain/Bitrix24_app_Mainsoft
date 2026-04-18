import type { TaskWorkspaceFilters, TaskWorkspaceItem, TaskWorkspaceNode } from '~/types/task-workspace'

export function createTaskNode(task: { id: string | number; title: string; parentId?: string | number | null }): TaskWorkspaceNode {
  return {
    taskId: String(task.id),
    taskTitle: task.title,
    parentId: task.parentId ? String(task.parentId) : null,
    children: [],
    items: [],
    totalConsidered: 0,
    totalUnconsidered: 0,
    cumulativeConsidered: 0,
    cumulativeUnconsidered: 0
  }
}

export function calculateTaskNodeTotals(node: TaskWorkspaceNode) {
  let childConsidered = 0
  let childUnconsidered = 0

  for (const child of node.children) {
    const totals = calculateTaskNodeTotals(child)
    childConsidered += totals.cons
    childUnconsidered += totals.uncons
  }

  node.cumulativeConsidered = node.totalConsidered + childConsidered
  node.cumulativeUnconsidered = node.totalUnconsidered + childUnconsidered

  return {
    cons: node.cumulativeConsidered,
    uncons: node.cumulativeUnconsidered
  }
}

export function buildTaskTree(rootTaskId: string, tasks: Array<{ id: string | number; title: string; parentId?: string | number | null }>) {
  const nodesMap: Record<string, TaskWorkspaceNode> = {}

  for (const task of tasks) {
    nodesMap[String(task.id)] = createTaskNode(task)
  }

  const roots: TaskWorkspaceNode[] = []

  for (const node of Object.values(nodesMap)) {
    const parentNode = node.parentId ? nodesMap[node.parentId] : undefined
    if (parentNode) {
      parentNode.children.push(node)
    } else if (node.taskId === String(rootTaskId)) {
      roots.push(node)
    }
  }

  for (const root of roots) {
    calculateTaskNodeTotals(root)
  }

  return {
    roots,
    nodesMap
  }
}

export function attachItemsToTaskNodes(
  nodesMap: Record<string, TaskWorkspaceNode>,
  taskItems: Array<{ taskId: string | number; item: TaskWorkspaceItem }>
) {
  for (const entry of taskItems) {
    const taskId = String(entry.taskId)
    const node = nodesMap[taskId]

    if (!node) {
      continue
    }

    node.items.push(entry.item)
    if (entry.item.isConsidered) {
      node.totalConsidered += entry.item.hours
    } else {
      node.totalUnconsidered += entry.item.hours
    }
  }
}

export function filterTaskNode(node: TaskWorkspaceNode, filters: TaskWorkspaceFilters): TaskWorkspaceNode {
  const filteredItems = node.items.filter((item) => {
    if (filters.employeeId && String(item.employeeId) !== String(filters.employeeId)) {
      return false
    }

    if (filters.dateFrom || filters.dateTo) {
      const sourceDate = String(item.date || item.createdTime || '')
      const normalizedDate = sourceDate.split('T')[0] || ''
      if (filters.dateFrom && normalizedDate < filters.dateFrom) {
        return false
      }
      if (filters.dateTo && normalizedDate > filters.dateTo) {
        return false
      }
    }

    return true
  })

  const filteredChildren = node.children.map(child => filterTaskNode(child, filters))

  const totalConsidered = filteredItems
    .filter(item => item.isConsidered)
    .reduce((sum, item) => sum + item.hours, 0)

  const totalUnconsidered = filteredItems
    .filter(item => !item.isConsidered)
    .reduce((sum, item) => sum + item.hours, 0)

  const childConsidered = filteredChildren.reduce((sum, child) => sum + child.cumulativeConsidered, 0)
  const childUnconsidered = filteredChildren.reduce((sum, child) => sum + child.cumulativeUnconsidered, 0)

  return {
    ...node,
    items: filteredItems,
    children: filteredChildren,
    totalConsidered,
    totalUnconsidered,
    cumulativeConsidered: totalConsidered + childConsidered,
    cumulativeUnconsidered: totalUnconsidered + childUnconsidered
  }
}

export function filterTaskTree(nodes: TaskWorkspaceNode[], filters: TaskWorkspaceFilters) {
  const isFilterActive = Boolean(filters.employeeId || filters.dateFrom || filters.dateTo)
  if (!isFilterActive) {
    return nodes
  }

  return nodes.map(node => filterTaskNode(node, filters))
}

export function flattenTaskItems(nodes: TaskWorkspaceNode[]): TaskWorkspaceItem[] {
  const result: TaskWorkspaceItem[] = []

  for (const node of nodes) {
    result.push(...node.items)
    result.push(...flattenTaskItems(node.children))
  }

  return result
}

export function findTaskNodeById(taskId: string | null | undefined, nodes: TaskWorkspaceNode[]): TaskWorkspaceNode | null {
  const normalizedTaskId = String(taskId || '').trim()
  if (!normalizedTaskId) {
    return null
  }

  for (const node of nodes) {
    if (node.taskId === normalizedTaskId) {
      return node
    }

    const childNode = findTaskNodeById(normalizedTaskId, node.children)
    if (childNode) {
      return childNode
    }
  }

  return null
}

export function findTaskIdForItem(itemId: string, nodes: TaskWorkspaceNode[]): string | null {
  for (const node of nodes) {
    if (node.items.some(item => item.id === itemId)) {
      return node.taskId
    }

    const childResult = findTaskIdForItem(itemId, node.children)
    if (childResult) {
      return childResult
    }
  }

  return null
}
