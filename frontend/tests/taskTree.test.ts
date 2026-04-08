import test from 'node:test'
import assert from 'node:assert/strict'

import { filterTaskTree, findTaskIdForItem } from '../app/utils/taskTree'
import type { TaskWorkspaceNode } from '../app/types/task-workspace'

const tree: TaskWorkspaceNode[] = [
  {
    taskId: '1',
    taskTitle: 'Корень',
    parentId: null,
    children: [
      {
        taskId: '2',
        taskTitle: 'Подзадача',
        parentId: '1',
        children: [],
        items: [{
          id: 'item-2',
          hours: 2,
          isConsidered: false,
          description: 'late',
          employeeId: '8',
          employeeName: 'Петров',
          createdTime: '2026-04-05T10:00:00',
          date: '2026-04-05'
        }],
        totalConsidered: 0,
        totalUnconsidered: 2,
        cumulativeConsidered: 0,
        cumulativeUnconsidered: 2
      }
    ],
    items: [{
      id: 'item-1',
      hours: 1.5,
      isConsidered: true,
      description: 'done',
      employeeId: '7',
      employeeName: 'Иванов',
      createdTime: '2026-04-03T10:00:00',
      date: '2026-04-03'
    }],
    totalConsidered: 1.5,
    totalUnconsidered: 0,
    cumulativeConsidered: 1.5,
    cumulativeUnconsidered: 2
  }
]

test('filterTaskTree keeps only matching employee and recomputes totals', () => {
  const filtered = filterTaskTree(tree, { employeeId: '7' })

  assert.equal(filtered[0].items.length, 1)
  assert.equal(filtered[0].children[0].items.length, 0)
  assert.equal(filtered[0].cumulativeConsidered, 1.5)
  assert.equal(filtered[0].cumulativeUnconsidered, 0)
})

test('findTaskIdForItem resolves nested task owner', () => {
  assert.equal(findTaskIdForItem('item-2', tree), '2')
  assert.equal(findTaskIdForItem('missing', tree), null)
})
