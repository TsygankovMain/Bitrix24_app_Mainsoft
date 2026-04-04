export interface ExportXlsxOptions {
  rows: Record<string, unknown>[]
  sheetName: string
  fileName: string
  columnWidths?: number[]
}

export async function exportRowsToXlsx(options: ExportXlsxOptions) {
  const XLSX = await import('xlsx')
  const worksheet = XLSX.utils.json_to_sheet(options.rows)

  if (options.columnWidths?.length) {
    worksheet['!cols'] = options.columnWidths.map((width) => ({ wch: width }))
  }

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, options.sheetName)
  XLSX.writeFile(workbook, options.fileName)
}
