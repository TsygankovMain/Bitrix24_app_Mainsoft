/**
 * Форматирование чисел для отчётов (русская локаль, 1 знак после запятой).
 */

export function formatHours(val?: number | null): string {
  const n = typeof val === 'number' && Number.isFinite(val) ? val : 0
  return n.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

/**
 * Доля part от whole в процентах (строка с 1 знаком). Безопасно при whole = 0.
 */
export function formatPercent(part?: number | null, whole?: number | null): string {
  const p = typeof part === 'number' && Number.isFinite(part) ? part : 0
  const w = typeof whole === 'number' && Number.isFinite(whole) ? whole : 0
  const value = w > 0 ? (p / w) * 100 : 0
  return value.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

/** Дата метки времени в формате ДД.ММ.ГГГГ (или исходная строка, если не парсится). */
export function formatReportDate(value?: string | null): string {
  if (!value) return ''
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
