/**
 * Две выгрузки вкладки задачи: файл CSV и перенос часов в штатный отчёт
 * Битрикс24 (`task.elapseditem.add`).
 *
 * Обе раньше жили в `pages/task.vue` — экране, на который в проде ничего не
 * вело. При переезде на рабочий экран (`pages/embedded.vue`) построение строк
 * и построение батча вынесены сюда: это чистые функции, их можно проверить
 * тестом, а компоненту остаётся скачать файл и отправить батч.
 *
 * Что изменилось по сравнению с версией из task.vue:
 *  - из CSV убраны колонки «ставка» и «сумма». Суммы во вкладке задачи не
 *    показываются (их видят руководители в отчётах), и через файл они утекать
 *    тоже не должны;
 *  - разделитель `;` и десятичная запятая вместо `,` и точки — иначе русский
 *    Excel кладёт всю строку в одну ячейку, а «1.50» считает текстом;
 *  - заголовки по-русски, к содержимому добавляется BOM (см. CSV_BOM) — без
 *    него Excel читает кириллицу как мусор.
 */

import type { TaskWorkspaceItem, TaskWorkspaceNode } from '~/types/task-workspace'
import { formatEntryDate } from './taskTabFormat'

/** Метка порядка байтов: без неё Excel открывает UTF-8 как cp1251. */
export const CSV_BOM = '﻿'

const CSV_SEPARATOR = ';'
const CSV_EOL = '\r\n'

const CSV_HEADER = [
  'Тип',
  'Задача / Запись',
  'Сотрудник',
  'Дата',
  'Часы всего',
  'Часы учтено',
  'Комментарий'
]

function csvCell(value: unknown): string {
  const raw = value === null || value === undefined ? '' : String(value)
  if (!/[";\r\n]/.test(raw)) {
    return raw
  }

  return `"${raw.replace(/"/g, '""')}"`
}

/** Число для русского Excel: две цифры после запятой, разделитель — запятая. */
export function csvNumber(value: number): string {
  const normalized = Number.isFinite(value) ? value : 0
  return normalized.toFixed(2).replace('.', ',')
}

/**
 * Плоская таблица по дереву задач.
 *
 * Вложенность передаётся отступом в названии, а не отдельной колонкой уровня:
 * так выгрузку можно читать глазами сразу после открытия, без сводных таблиц.
 */
export function buildTaskTreeCsv(tree: TaskWorkspaceNode[]): string {
  const rows: string[][] = [CSV_HEADER]

  const walk = (nodes: TaskWorkspaceNode[], depth: number) => {
    for (const node of nodes) {
      const indent = '   '.repeat(depth)
      rows.push([
        'Задача',
        `${indent}${node.taskTitle || `ID ${node.taskId}`}`,
        '',
        '',
        csvNumber((node.cumulativeConsidered || 0) + (node.cumulativeUnconsidered || 0)),
        csvNumber(node.cumulativeConsidered || 0),
        ''
      ])

      for (const item of node.items || []) {
        rows.push([
          'Запись',
          `${indent} — ${item.description || item.title || 'Без описания'}`,
          item.employeeName || '',
          formatEntryDate(item.date || item.createdTime),
          csvNumber(item.hours),
          csvNumber(item.isConsidered ? item.hours : 0),
          item.description || ''
        ])
      }

      if (node.children?.length) {
        walk(node.children, depth + 1)
      }
    }
  }

  walk(tree, 0)

  return rows.map(row => row.map(csvCell).join(CSV_SEPARATOR)).join(CSV_EOL)
}

/** Имя файла выгрузки: без ID задачи файлы разных задач неразличимы в «Загрузках». */
export function buildCsvFileName(taskId: string | null | undefined): string {
  const normalized = String(taskId || '').trim()
  return normalized ? `timesheet_task_${normalized}.csv` : 'timesheet_task.csv'
}

export interface ElapsedItemBatchCall {
  method: 'task.elapseditem.add'
  params: {
    TASKID: string
    FIELDS: {
      SECONDS: number
      COMMENT_TEXT: string
      USER_ID: string | number
    }
  }
}

export interface ElapsedItemBatch {
  batch: Record<string, ElapsedItemBatchCall>
  count: number
}

/**
 * Батч переноса часов в штатный отчёт Битрикс24.
 *
 * Переносятся только записи с признаком «учитывать» и ненулевыми часами —
 * неучтённые часы это внутренняя кухня приложения, в отчёте задачи им не место.
 * Часы задачи берутся не накопительные: `task.elapseditem.add` пишет время на
 * конкретную задачу, и накопительный итог родителя продублировал бы часы детей.
 */
export function buildElapsedItemBatch(tree: TaskWorkspaceNode[]): ElapsedItemBatch {
  const batch: Record<string, ElapsedItemBatchCall> = {}
  let count = 0

  const walk = (nodes: TaskWorkspaceNode[]) => {
    for (const node of nodes) {
      for (const item of node.items || []) {
        if (!item.isConsidered || !(item.hours > 0)) {
          continue
        }

        batch[`report_${item.id}`] = {
          method: 'task.elapseditem.add',
          params: {
            TASKID: String(node.taskId),
            FIELDS: {
              SECONDS: Math.round(item.hours * 3600),
              COMMENT_TEXT: buildElapsedComment(item),
              USER_ID: item.employeeId
            }
          }
        }
        count += 1
      }

      if (node.children?.length) {
        walk(node.children)
      }
    }
  }

  walk(tree)

  return { batch, count }
}

function buildElapsedComment(item: TaskWorkspaceItem): string {
  const description = String(item.description || '').trim()
  if (description) {
    return description
  }

  const title = String(item.title || '').trim()
  return title ? `Отражение часов: ${title}` : 'Отражение часов'
}
