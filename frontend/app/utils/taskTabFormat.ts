/**
 * Строки и итоги вкладки задачи (`pages/embedded.vue`).
 *
 * Вынесено из компонента по той же причине, что и раскладка: node:test не
 * резолвит .vue, а «сколько часов показать в шапке задачи» и «как выглядит
 * дата записи» — ровно то, что ломается незаметно.
 *
 * Формат даты считается вручную, а не через `toLocaleDateString('ru-RU')`:
 * результат Intl зависит от ICU в сборке Node и от локали среды, поэтому в
 * тесте он был бы недетерминирован. Битрикс24 отдаёт дату записи либо как
 * `YYYY-MM-DD`, либо как ISO с временем, либо не отдаёт вовсе — все три
 * случая обрабатываются здесь, а не в разметке.
 */

import type { TaskWorkspaceItem, TaskWorkspaceNode } from '~/types/task-workspace'

export type TaskTotalsTone = 'success' | 'danger' | 'muted'

export interface TaskTotalsSegment {
  key: string
  label: string
  value: string
  tone: TaskTotalsTone
}

export interface TaskTreeSummary {
  /** Задач и подзадач в дереве. */
  tasks: number
  /** Записей времени во всём дереве. */
  entries: number
  consideredHours: number
  unconsideredHours: number
}

/** Часы всегда с двумя знаками: 1 ч и 1.25 ч должны быть видимо разными. */
export function formatTaskHours(value: number): string {
  const normalized = Number.isFinite(value) ? value : 0
  return `${normalized.toFixed(2)} ч`
}

/**
 * Дата записи в виде ДД.ММ.ГГГГ.
 *
 * Пустое значение и мусор дают прочерк, а не «Invalid Date» и не сегодняшнее
 * число: у старых записей поле даты бывает пустым, и подставлять туда текущий
 * день нельзя — это ложь о том, когда списали часы.
 */
export function formatEntryDate(value?: string | null): string {
  const raw = String(value || '').trim()
  if (!raw) {
    return '—'
  }

  const isoMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (isoMatch) {
    return `${isoMatch[3]}.${isoMatch[2]}.${isoMatch[1]}`
  }

  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) {
    return '—'
  }

  const day = String(parsed.getDate()).padStart(2, '0')
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  return `${day}.${month}.${parsed.getFullYear()}`
}

/** «Иванов · 05.04.2026» — мета записи одной строкой. */
export function formatEntryMeta(item: Pick<TaskWorkspaceItem, 'employeeName' | 'date' | 'createdTime'>): string {
  const employee = String(item.employeeName || '').trim()
  const date = formatEntryDate(item.date || item.createdTime)
  return employee ? `${employee} · ${date}` : date
}

/**
 * Итоги задачи одной строкой.
 *
 * «Учтено» и «Не учтено» — накопительные, то есть вместе с подзадачами: именно
 * эта цифра идёт в отчётность. Собственные часы задачи показываются третьим
 * сегментом и только когда у задачи есть подзадачи и есть что показывать —
 * иначе строка дублирует сама себя.
 */
export function buildTaskTotalsSegments(node: TaskWorkspaceNode): TaskTotalsSegment[] {
  const segments: TaskTotalsSegment[] = [
    {
      key: 'considered',
      label: 'Учтено',
      value: formatTaskHours(node.cumulativeConsidered),
      tone: 'success'
    },
    {
      key: 'unconsidered',
      label: 'Не учтено',
      value: formatTaskHours(node.cumulativeUnconsidered),
      tone: 'danger'
    }
  ]

  const hasChildren = (node.children?.length || 0) > 0
  const ownHours = (node.totalConsidered || 0) + (node.totalUnconsidered || 0)
  if (hasChildren && ownHours > 0) {
    segments.push({
      key: 'own',
      label: 'в т.ч. своих',
      value: formatTaskHours(ownHours),
      tone: 'muted'
    })
  }

  return segments
}

/** Та же строка текстом — для `title` и для тестов. */
export function formatTotalsText(segments: TaskTotalsSegment[]): string {
  return segments.map(segment => `${segment.label} ${segment.value}`).join(' · ')
}

/** Итоги по всему дереву: шапка вкладки показывает их одной строкой. */
export function summarizeTaskTree(tree: TaskWorkspaceNode[]): TaskTreeSummary {
  const summary: TaskTreeSummary = {
    tasks: 0,
    entries: 0,
    consideredHours: 0,
    unconsideredHours: 0
  }

  // Накопительные итоги берутся только у корней: у детей они уже входят в
  // родительские, и повторный обход дал бы двойной счёт.
  for (const root of tree) {
    summary.consideredHours += root.cumulativeConsidered || 0
    summary.unconsideredHours += root.cumulativeUnconsidered || 0
  }

  const walk = (nodes: TaskWorkspaceNode[]) => {
    for (const node of nodes) {
      summary.tasks += 1
      summary.entries += node.items?.length || 0
      if (node.children?.length) {
        walk(node.children)
      }
    }
  }
  walk(tree)

  return summary
}

/** «Учтено 4.50 ч · Не учтено 1.00 ч · 3 записи» — шапка вкладки. */
export function formatTreeSummaryLine(summary: TaskTreeSummary): string {
  return [
    `Учтено ${formatTaskHours(summary.consideredHours)}`,
    `Не учтено ${formatTaskHours(summary.unconsideredHours)}`,
    `${summary.entries} ${pluralizeEntries(summary.entries)}`
  ].join(' · ')
}

/** 1 запись / 2 записи / 5 записей. */
export function pluralizeEntries(count: number): string {
  const normalized = Math.abs(Math.trunc(Number.isFinite(count) ? count : 0))
  const tail = normalized % 100
  if (tail >= 11 && tail <= 14) {
    return 'записей'
  }

  switch (normalized % 10) {
    case 1:
      return 'запись'
    case 2:
    case 3:
    case 4:
      return 'записи'
    default:
      return 'записей'
  }
}
