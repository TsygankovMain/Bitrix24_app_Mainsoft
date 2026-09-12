import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildTaskTotalsSegments,
  formatEntryDate,
  formatEntryMeta,
  formatTaskHours,
  formatTotalsText,
  formatTreeSummaryLine,
  pluralizeEntries,
  summarizeTaskTree
} from '../app/utils/taskTabFormat'
import type { TaskWorkspaceNode } from '../app/types/task-workspace'

function makeNode(overrides: Partial<TaskWorkspaceNode> & { taskId: string }): TaskWorkspaceNode {
  return {
    taskTitle: `Задача ${overrides.taskId}`,
    parentId: null,
    children: [],
    items: [],
    totalConsidered: 0,
    totalUnconsidered: 0,
    cumulativeConsidered: 0,
    cumulativeUnconsidered: 0,
    ...overrides
  }
}

const tree: TaskWorkspaceNode[] = [
  makeNode({
    taskId: '1',
    items: [
      {
        id: 'a',
        hours: 1.5,
        isConsidered: true,
        description: 'Разбор',
        employeeId: '7',
        employeeName: 'Иванов',
        date: '2026-04-03'
      }
    ],
    children: [
      makeNode({
        taskId: '2',
        parentId: '1',
        items: [
          {
            id: 'b',
            hours: 2,
            isConsidered: false,
            description: 'Созвон',
            employeeId: '8',
            employeeName: 'Петров',
            date: '2026-04-05'
          }
        ],
        totalConsidered: 0,
        totalUnconsidered: 2,
        cumulativeConsidered: 0,
        cumulativeUnconsidered: 2
      })
    ],
    totalConsidered: 1.5,
    totalUnconsidered: 0,
    cumulativeConsidered: 1.5,
    cumulativeUnconsidered: 2
  })
]

test('formatTaskHours: всегда два знака после точки', () => {
  assert.equal(formatTaskHours(1), '1.00 ч')
  assert.equal(formatTaskHours(1.25), '1.25 ч')
  assert.equal(formatTaskHours(Number.NaN), '0.00 ч')
})

test('formatEntryDate: дата приходит и датой, и датой со временем', () => {
  assert.equal(formatEntryDate('2026-04-05'), '05.04.2026')
  assert.equal(formatEntryDate('2026-04-05T10:00:00+03:00'), '05.04.2026')
})

test('formatEntryDate: пустая дата даёт прочерк, а не сегодняшний день', () => {
  assert.equal(formatEntryDate(''), '—')
  assert.equal(formatEntryDate(null), '—')
  assert.equal(formatEntryDate('не дата'), '—')
})

test('formatEntryMeta: сотрудник и дата одной строкой', () => {
  assert.equal(
    formatEntryMeta({ employeeName: 'Иванов', date: '2026-04-05' }),
    'Иванов · 05.04.2026'
  )
  assert.equal(formatEntryMeta({ employeeName: '', date: '2026-04-05' }), '05.04.2026')
})

test('buildTaskTotalsSegments: учтено и не учтено — накопительные', () => {
  const segments = buildTaskTotalsSegments(tree[0]!)

  assert.equal(segments[0]!.value, '1.50 ч')
  assert.equal(segments[1]!.value, '2.00 ч')
})

test('buildTaskTotalsSegments: свои часы показываются только при наличии подзадач', () => {
  const withChildren = buildTaskTotalsSegments(tree[0]!)
  assert.equal(withChildren.length, 3)
  assert.equal(withChildren[2]!.label, 'в т.ч. своих')
  assert.equal(withChildren[2]!.value, '1.50 ч')

  const leaf = buildTaskTotalsSegments(tree[0]!.children[0]!)
  assert.equal(leaf.length, 2, 'у листа третий сегмент дублировал бы первые два')
})

test('formatTotalsText: итоги задачи одной строкой', () => {
  assert.equal(
    formatTotalsText(buildTaskTotalsSegments(tree[0]!)),
    'Учтено 1.50 ч · Не учтено 2.00 ч · в т.ч. своих 1.50 ч'
  )
})

test('summarizeTaskTree: часы берутся у корней, задачи и записи — по всему дереву', () => {
  const summary = summarizeTaskTree(tree)

  assert.equal(summary.consideredHours, 1.5)
  assert.equal(summary.unconsideredHours, 2)
  assert.equal(summary.tasks, 2)
  assert.equal(summary.entries, 2)
})

test('summarizeTaskTree: пустое дерево даёт нули, а не падение', () => {
  const summary = summarizeTaskTree([])

  assert.deepEqual(summary, { tasks: 0, entries: 0, consideredHours: 0, unconsideredHours: 0 })
})

test('formatTreeSummaryLine: итоги вкладки одной строкой', () => {
  assert.equal(
    formatTreeSummaryLine(summarizeTaskTree(tree)),
    'Учтено 1.50 ч · Не учтено 2.00 ч · 2 записи'
  )
})

test('pluralizeEntries: склонение по-русски', () => {
  assert.equal(pluralizeEntries(0), 'записей')
  assert.equal(pluralizeEntries(1), 'запись')
  assert.equal(pluralizeEntries(3), 'записи')
  assert.equal(pluralizeEntries(11), 'записей')
  assert.equal(pluralizeEntries(21), 'запись')
  assert.equal(pluralizeEntries(114), 'записей')
})
