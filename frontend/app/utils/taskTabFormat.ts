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

export type TaskTotalsTone = 'success' | 'muted'

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

/**
 * Часы числом по-русски: «1», «3,5», «1,25».
 *
 * Хвостовые нули срезаются, разделитель — запятая. Так написано в макете
 * варианта A («15 ч», «3,5 ч»), и так же час выглядит в самом портале.
 * Прежний `toFixed(2)` давал «1.00 ч» — точка в русском тексте и три лишних
 * символа в каждой строке дерева, где место и так спорное.
 *
 * Округление до сотых — это шаг ввода: в форме `step="0.25"`, мельче четверти
 * часа никто не списывает, а `0.1 + 0.2` в double даёт «0,30000000000000004».
 */
export function formatHoursNumber(value: number): string {
  const normalized = Number.isFinite(value) ? value : 0
  const fixed = (Math.round(normalized * 100) / 100).toFixed(2)
  return fixed.replace(/\.?0+$/, '').replace('.', ',')
}

/** «3,5 ч» — часы с единицей измерения. */
export function formatTaskHours(value: number): string {
  return `${formatHoursNumber(value)} ч`
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
 * Сколько строк дерева реально видно на экране.
 *
 * Считаются шапки задач (они видны всегда) и записи только раскрытых задач —
 * свёрнутая задача с полусотней записей занимает одну строку, а не полсотни.
 * По этой цифре решается, дублировать ли выгрузки наверх
 * (`shouldMirrorFooterActions`), поэтому считать надо именно видимое.
 */
export function countVisibleRows(tree: TaskWorkspaceNode[], expandedTasks: Set<string>): number {
  let rows = 0

  for (const node of tree) {
    rows += 1

    if (!expandedTasks.has(node.taskId)) {
      continue
    }

    rows += node.items?.length || 0
    rows += countVisibleRows(node.children || [], expandedTasks)
  }

  return rows
}

/** Записей времени во всей ветке задачи, включая подзадачи. */
export function countTreeEntries(node: TaskWorkspaceNode): number {
  let total = node.items?.length || 0

  for (const child of node.children || []) {
    total += countTreeEntries(child)
  }

  return total
}

/**
 * Итоги задачи одной строкой — то, что в макете варианта A стоит справа от
 * названия задачи: сколько часов на самой задаче, сколько с подзадачами и
 * сколько за этим записей.
 *
 * «Учтено» и «Не учтено» — накопительные, то есть вместе с подзадачами: именно
 * эта цифра идёт в отчётность. Собственные часы задачи показываются отдельным
 * сегментом и только когда у задачи есть подзадачи и есть что показывать —
 * иначе строка дублирует сама себя. Число записей — тоже по всей ветке: оно
 * отвечает на вопрос «раскрывать ли эту задачу», а он про ветку целиком.
 *
 * Сумм в рублях здесь нет и не будет: экран сотрудника их не показывает,
 * стоимость видят руководители в отчётах.
 *
 * «Не учтено» подано приглушённо, а не красным: неучтённые часы — это штатный
 * режим работы (внутренние задачи, переделки), а не ошибка. Красный во вкладке
 * остаётся за отказами и удалением.
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
      tone: 'muted'
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

  const entries = countTreeEntries(node)
  segments.push({
    key: 'entries',
    label: '',
    value: `${entries} ${pluralizeEntries(entries)}`,
    tone: 'muted'
  })

  return segments
}

/** Та же строка текстом — для `title` и для тестов. */
export function formatTotalsText(segments: TaskTotalsSegment[]): string {
  return segments
    .map(segment => (segment.label ? `${segment.label} ${segment.value}` : segment.value))
    .join(' · ')
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

/**
 * «Всего 5,5 ч · учтено 4,5 ч · не учтено 1 ч · 3 записи» — шапка вкладки.
 *
 * Порядок и регистр — из макета варианта A: сначала общий объём, потом
 * разбивка. Сумма идёт первой потому, что на вопрос «сколько всего ушло на эту
 * задачу» отвечают чаще, чем на вопрос про признак учёта.
 */
export function formatTreeSummaryLine(summary: TaskTreeSummary): string {
  const total = (summary.consideredHours || 0) + (summary.unconsideredHours || 0)

  return [
    `Всего ${formatTaskHours(total)}`,
    `учтено ${formatTaskHours(summary.consideredHours)}`,
    `не учтено ${formatTaskHours(summary.unconsideredHours)}`,
    `${summary.entries} ${pluralizeEntries(summary.entries)}`
  ].join(' · ')
}

/**
 * Подпись кнопки периода в строке инструментов.
 *
 * Пустой фильтр — «Весь период», как в макете. Половинчатый период («только
 * с» или «только по») тоже должен читаться: иначе человек видит «Весь период»
 * при включённом ограничении и не понимает, почему часть записей пропала.
 */
export function formatPeriodLabel(dateFrom?: string | null, dateTo?: string | null): string {
  const from = formatEntryDate(dateFrom)
  const to = formatEntryDate(dateTo)
  const hasFrom = from !== '—'
  const hasTo = to !== '—'

  if (hasFrom && hasTo) {
    return `${from} — ${to}`
  }

  if (hasFrom) {
    return `с ${from}`
  }

  if (hasTo) {
    return `по ${to}`
  }

  return 'Весь период'
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
