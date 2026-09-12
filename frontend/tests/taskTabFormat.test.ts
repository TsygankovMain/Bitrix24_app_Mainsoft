import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildTaskTotalsSegments,
  countTreeEntries,
  countVisibleRows,
  formatEntryDate,
  formatEntryMeta,
  formatHoursNumber,
  formatPeriodLabel,
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

test('formatHoursNumber: по-русски, без хвостовых нулей', () => {
  assert.equal(formatHoursNumber(1), '1')
  assert.equal(formatHoursNumber(0.5), '0,5')
  assert.equal(formatHoursNumber(1.25), '1,25')
  assert.equal(formatHoursNumber(3.5), '3,5')
  assert.equal(formatHoursNumber(0), '0')
  assert.equal(formatHoursNumber(100), '100')
  assert.equal(formatHoursNumber(Number.NaN), '0')
})

test('formatHoursNumber: копеечные хвосты double не вылезают в интерфейс', () => {
  assert.equal(formatHoursNumber(0.1 + 0.2), '0,3')
})

test('formatTaskHours: часы с единицей измерения', () => {
  assert.equal(formatTaskHours(1), '1 ч')
  assert.equal(formatTaskHours(1.25), '1,25 ч')
  assert.equal(formatTaskHours(Number.NaN), '0 ч')
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

  assert.equal(segments[0]!.value, '1,5 ч')
  assert.equal(segments[1]!.value, '2 ч')
})

test('buildTaskTotalsSegments: «Не учтено» подано приглушённо, а не красным', () => {
  const segments = buildTaskTotalsSegments(tree[0]!)

  assert.equal(segments[0]!.tone, 'success')
  assert.equal(segments[1]!.tone, 'muted')
})

test('buildTaskTotalsSegments: свои часы показываются только при наличии подзадач', () => {
  const withChildren = buildTaskTotalsSegments(tree[0]!)
  assert.equal(withChildren.length, 4)
  assert.equal(withChildren[2]!.label, 'в т.ч. своих')
  assert.equal(withChildren[2]!.value, '1,5 ч')

  const leaf = buildTaskTotalsSegments(tree[0]!.children[0]!)
  assert.equal(leaf.length, 3, 'у листа сегмент своих часов дублировал бы первые два')
})

test('buildTaskTotalsSegments: последним идёт число записей по всей ветке', () => {
  const segments = buildTaskTotalsSegments(tree[0]!)
  const entries = segments[segments.length - 1]!

  assert.equal(entries.key, 'entries')
  assert.equal(entries.label, '', 'у счётчика записей подписи нет — она в самом значении')
  assert.equal(entries.value, '2 записи')
})

test('countTreeEntries: записи считаются вместе с подзадачами', () => {
  assert.equal(countTreeEntries(tree[0]!), 2)
  assert.equal(countTreeEntries(tree[0]!.children[0]!), 1)
})

test('formatTotalsText: итоги задачи одной строкой', () => {
  assert.equal(
    formatTotalsText(buildTaskTotalsSegments(tree[0]!)),
    'Учтено 1,5 ч · Не учтено 2 ч · в т.ч. своих 1,5 ч · 2 записи'
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
    'Всего 3,5 ч · учтено 1,5 ч · не учтено 2 ч · 2 записи'
  )
})

test('formatTreeSummaryLine: пустое дерево не даёт NaN', () => {
  assert.equal(
    formatTreeSummaryLine(summarizeTaskTree([])),
    'Всего 0 ч · учтено 0 ч · не учтено 0 ч · 0 записей'
  )
})

test('formatPeriodLabel: пустой период читается как «Весь период»', () => {
  assert.equal(formatPeriodLabel('', ''), 'Весь период')
  assert.equal(formatPeriodLabel(null, null), 'Весь период')
})

test('formatPeriodLabel: половинчатый период всё равно виден', () => {
  assert.equal(formatPeriodLabel('2026-09-01', ''), 'с 01.09.2026')
  assert.equal(formatPeriodLabel('', '2026-09-30'), 'по 30.09.2026')
})

test('formatPeriodLabel: обе границы', () => {
  assert.equal(formatPeriodLabel('2026-09-01', '2026-09-30'), '01.09.2026 — 30.09.2026')
})

test('pluralizeEntries: склонение по-русски', () => {
  assert.equal(pluralizeEntries(0), 'записей')
  assert.equal(pluralizeEntries(1), 'запись')
  assert.equal(pluralizeEntries(3), 'записи')
  assert.equal(pluralizeEntries(11), 'записей')
  assert.equal(pluralizeEntries(21), 'запись')
  assert.equal(pluralizeEntries(114), 'записей')
})

test('countVisibleRows: свёрнутая задача — одна строка, а не все её записи', () => {
  assert.equal(countVisibleRows(tree, new Set()), 1, 'виден только корень')
  assert.equal(countVisibleRows(tree, new Set(['1'])), 3, 'корень, его запись и шапка подзадачи')
  assert.equal(countVisibleRows(tree, new Set(['1', '2'])), 4, 'плюс запись подзадачи')
})

test('countVisibleRows: пустое дерево — ноль строк', () => {
  assert.equal(countVisibleRows([], new Set(['1'])), 0)
})
