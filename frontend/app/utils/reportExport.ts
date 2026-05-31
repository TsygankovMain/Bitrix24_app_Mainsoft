import { exportRowsToXlsx } from '~/utils/exportXlsx'
import type {
  DailyWorkloadReport,
  HierarchicalReportNode,
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
