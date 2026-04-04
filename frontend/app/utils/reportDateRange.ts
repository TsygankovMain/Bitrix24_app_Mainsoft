export function formatDateForInput(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')

  return `${year}-${month}-${day}`
}

export function getMonthRange(monthOffset = 0, baseDate = new Date()) {
  const start = new Date(baseDate.getFullYear(), baseDate.getMonth() + monthOffset, 1)
  const end = new Date(baseDate.getFullYear(), baseDate.getMonth() + monthOffset + 1, 0)

  return {
    dateFrom: formatDateForInput(start),
    dateTo: formatDateForInput(end)
  }
}

export function getCurrentMonthRange(baseDate = new Date()) {
  return getMonthRange(0, baseDate)
}

export function getWeekRange(weekOffset = 0, baseDate = new Date()) {
  const anchor = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate())
  const day = anchor.getDay() || 7
  const start = new Date(anchor)

  start.setDate(anchor.getDate() - day + 1 + (weekOffset * 7))

  const end = new Date(start)
  end.setDate(start.getDate() + 6)

  return {
    dateFrom: formatDateForInput(start),
    dateTo: formatDateForInput(end)
  }
}
