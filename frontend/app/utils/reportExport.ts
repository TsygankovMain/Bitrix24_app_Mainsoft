import { exportRowsToXlsx } from '~/utils/exportXlsx'
import type {
  DailyWorkloadReport,
  HierarchicalReportNode,
  ProjectTaskReportEmployee,
  ProjectTaskReportNode,
} from '~/types/report'

export function flattenHierarchyReport(nodes: HierarchicalReportNode[]) {
  const rows: Record<string, unknown>[] = []
  const rowLevels: number[] = []

  const processNode = (node: HierarchicalReportNode, level = 0) => {
    rows.push({
      'Название': `${'    '.repeat(level)}${node.name}`,
      'Всего часов': node.total_hours,
      'Учитываемые': node.billable_hours,
      'Не учитываемые': node.non_billable_hours
    })
    rowLevels.push(level)

    for (const child of node.children || []) {
      processNode(child, level + 1)
    }
  }

  for (const node of nodes) {
    processNode(node)
  }

  return { rows, rowLevels }
}

export async function exportHierarchyReportToXlsx(options: {
  rows: HierarchicalReportNode[]
  sheetName: string
  fileName: string
}) {
  const { rows } = flattenHierarchyReport(options.rows)

  await exportRowsToXlsx({
    rows,
    sheetName: options.sheetName,
    fileName: options.fileName,
    columnWidths: [50, 15, 15, 15]
  })
}

export function flattenDailyWorkloadReport(report: DailyWorkloadReport) {
  return report.rows.map(row => {
    const rowData: Record<string, unknown> = {
      'Сотрудник': row.employee.name
    }

    for (const day of report.header_days) {
      const cell = row.days?.[day.date]
      rowData[day.date] = cell?.total ? Number(cell.total) : ''
    }

    return rowData
  })
}

export async function exportDailyWorkloadToXlsx(options: {
  report: DailyWorkloadReport
  sheetName: string
  fileName: string
}) {
  await exportRowsToXlsx({
    rows: flattenDailyWorkloadReport(options.report),
    sheetName: options.sheetName,
    fileName: options.fileName,
    columnWidths: [30, ...options.report.header_days.map(() => 5)]
  })
}

function formatProjectTaskDate(dateStr?: string) {
  if (!dateStr) {
    return '—'
  }

  const parsed = new Date(dateStr)
  if (Number.isNaN(parsed.getTime())) {
    return dateStr
  }

  return parsed.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  })
}

function appendProjectTaskEmployeeRows(
  rows: Record<string, unknown>[],
  rowLevels: number[],
  employees: ProjectTaskReportEmployee[] | undefined,
  level: number
) {
  for (const employee of employees || []) {
    rows.push({
      'Название': `${'    '.repeat(level)}${employee.name}`,
      'Всего часов': employee.total_hours,
      'Учтено': employee.billable_hours,
      'Не учтено': employee.non_billable_hours
    })
    rowLevels.push(level)

    for (const item of employee.items || []) {
      rows.push({
        'Название': `${'    '.repeat(level + 1)}${item.nazvanie_zadachi || item.opisanie || '—'}`,
        'Дата': item.data ? formatProjectTaskDate(item.data) : '',
        'Всего часов': item.kolichestvo_chasov,
        'Учтено': item.uchitivaem ? item.kolichestvo_chasov : 0,
        'Не учтено': item.uchitivaem ? 0 : item.kolichestvo_chasov
      })
      rowLevels.push(level + 1)
    }
  }
}

function appendProjectTaskRows(
  rows: Record<string, unknown>[],
  rowLevels: number[],
  nodes: ProjectTaskReportNode[],
  level = 0
) {
  for (const node of nodes) {
    rows.push({
      'Название': `${'    '.repeat(level)}${node.name}`,
      'Всего часов': node.total_hours,
      'Учтено': node.billable_hours,
      'Не учтено': node.non_billable_hours
    })
    rowLevels.push(level)

    appendProjectTaskRows(rows, rowLevels, node.children || [], level + 1)
    appendProjectTaskEmployeeRows(rows, rowLevels, node.employees, level + 1)
  }
}

export function flattenProjectTaskReport(nodes: ProjectTaskReportNode[]) {
  const rows: Record<string, unknown>[] = []
  const rowLevels: number[] = []
  appendProjectTaskRows(rows, rowLevels, nodes)
  return { rows, rowLevels }
}

export async function exportProjectTaskReportToXlsx(options: {
  rows: ProjectTaskReportNode[]
  sheetName: string
  fileName: string
}) {
  const { rows } = flattenProjectTaskReport(options.rows)

  await exportRowsToXlsx({
    rows,
    sheetName: options.sheetName,
    fileName: options.fileName,
    columnWidths: [55, 15, 15, 15, 15]
  })
}
