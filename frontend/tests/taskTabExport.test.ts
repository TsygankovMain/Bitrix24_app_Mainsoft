import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildCsvFileName,
  buildElapsedItemBatch,
  buildTaskTreeCsv,
  csvNumber
} from '../app/utils/taskTabExport'
import type { TaskWorkspaceNode } from '../app/types/task-workspace'

const tree: TaskWorkspaceNode[] = [
  {
    taskId: '100',
    taskTitle: 'Корневая; с точкой с запятой',
    parentId: null,
    items: [
      {
        id: '1',
        hours: 1.5,
        isConsidered: true,
        description: 'Разбор данных',
        employeeId: '7',
        employeeName: 'Иванов',
        date: '2026-04-03'
      },
      {
        id: '2',
        hours: 2,
        isConsidered: false,
        description: '',
        title: 'Без описания',
        employeeId: '8',
        employeeName: 'Петров',
        date: '2026-04-04'
      }
    ],
    children: [
      {
        taskId: '101',
        taskTitle: 'Подзадача',
        parentId: '100',
        items: [
          {
            id: '3',
            hours: 0.25,
            isConsidered: true,
            description: 'Созвон',
            employeeId: '7',
            employeeName: 'Иванов',
            date: '2026-04-05'
          }
        ],
        children: [],
        totalConsidered: 0.25,
        totalUnconsidered: 0,
        cumulativeConsidered: 0.25,
        cumulativeUnconsidered: 0
      }
    ],
    totalConsidered: 1.5,
    totalUnconsidered: 2,
    cumulativeConsidered: 1.75,
    cumulativeUnconsidered: 2
  }
]

test('csvNumber: десятичная запятая для русского Excel', () => {
  assert.equal(csvNumber(1.5), '1,50')
  assert.equal(csvNumber(0), '0,00')
})

test('buildTaskTreeCsv: заголовок без колонок со ставкой и суммой', () => {
  const header = buildTaskTreeCsv([]).split('\r\n')[0]

  assert.equal(header, 'Тип;Задача / Запись;Сотрудник;Дата;Часы всего;Часы учтено;Комментарий')
  assert.ok(!header!.includes('Сумма'), 'суммы во вкладке задачи не показываются и в выгрузку не идут')
})

test('buildTaskTreeCsv: задачи и записи идут в порядке дерева', () => {
  const rows = buildTaskTreeCsv(tree).split('\r\n')

  assert.equal(rows.length, 6, 'шапка + 2 задачи + 3 записи')
  assert.ok(rows[1]!.startsWith('Задача;'))
  assert.ok(rows[2]!.startsWith('Запись;'))
  assert.ok(rows[4]!.startsWith('Задача;'), 'подзадача идёт после записей своего родителя')
})

test('buildTaskTreeCsv: точка с запятой в названии не ломает колонки', () => {
  const taskRow = buildTaskTreeCsv(tree).split('\r\n')[1]!

  assert.ok(taskRow.includes('"Корневая; с точкой с запятой"'))
  assert.equal(taskRow.split(';').length, 8, 'экранированное поле само по себе содержит один разделитель')
})

test('buildTaskTreeCsv: неучтённая запись даёт ноль в колонке учтённых часов', () => {
  const rows = buildTaskTreeCsv(tree).split('\r\n')
  const unconsidered = rows[3]!.split(';')

  assert.equal(unconsidered[4], '2,00')
  assert.equal(unconsidered[5], '0,00')
})

test('buildCsvFileName: в имени файла есть ID задачи', () => {
  assert.equal(buildCsvFileName('6239'), 'timesheet_task_6239.csv')
  assert.equal(buildCsvFileName(null), 'timesheet_task.csv')
})

test('buildElapsedItemBatch: переносятся только учтённые часы', () => {
  const { batch, count } = buildElapsedItemBatch(tree)

  assert.equal(count, 2)
  assert.deepEqual(Object.keys(batch).sort(), ['report_1', 'report_3'])
})

test('buildElapsedItemBatch: часы записи пишутся на её собственную задачу', () => {
  const { batch } = buildElapsedItemBatch(tree)

  assert.equal(batch.report_1!.params.TASKID, '100')
  assert.equal(batch.report_3!.params.TASKID, '101')
  assert.equal(batch.report_3!.params.FIELDS.SECONDS, 900)
  assert.equal(batch.report_1!.params.FIELDS.USER_ID, '7')
})

test('buildElapsedItemBatch: запись без описания получает осмысленный комментарий', () => {
  const { batch } = buildElapsedItemBatch([
    {
      ...tree[0]!,
      children: [],
      items: [{
        id: '9',
        hours: 1,
        isConsidered: true,
        description: '',
        title: 'Планёрка',
        employeeId: '7',
        employeeName: 'Иванов'
      }]
    }
  ])

  assert.equal(batch.report_9!.params.FIELDS.COMMENT_TEXT, 'Отражение часов: Планёрка')
})

test('buildElapsedItemBatch: пустое дерево не даёт ни одного вызова', () => {
  assert.deepEqual(buildElapsedItemBatch([]), { batch: {}, count: 0 })
})
