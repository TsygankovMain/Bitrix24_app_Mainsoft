/**
 * Возраст локальной read-model таймшитов — текст индикатора «данные на ЧЧ:ММ».
 *
 * Логика живёт здесь, а не внутри `.vue`: тестовый прогон не резолвит `.vue`-файлы,
 * поэтому всё, что записано прямо в шаблоне, остаётся непокрытым (см. записанное
 * слепое пятно проекта). В компоненте должен оставаться только рендер.
 */

/** Текст, когда маркер синхронизации отсутствует или нечитаем. */
export const NEVER_SYNCED_TEXT = 'данные не синхронизировались'

function isSameCalendarDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

/**
 * Разбирает маркер `last_synced_at`. Возвращает `null`, если значения нет
 * или оно не парсится в дату.
 */
export function parseSyncedAt(lastSyncedAt?: string | null): Date | null {
  const raw = typeof lastSyncedAt === 'string' ? lastSyncedAt.trim() : ''
  if (!raw) {
    return null
  }

  const parsed = new Date(raw)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/**
 * Текст возраста данных для шапки отчёта.
 *
 * - маркера нет → «данные не синхронизировались»
 * - синк был сегодня → «данные на ЧЧ:ММ»
 * - синк был раньше → «данные на ДД.ММ.ГГГГ ЧЧ:ММ»
 *
 * `now` параметризован, чтобы тест не зависел от системных часов.
 */
export function formatDataFreshness(lastSyncedAt?: string | null, now: Date = new Date()): string {
  const syncedAt = parseSyncedAt(lastSyncedAt)
  if (!syncedAt) {
    return NEVER_SYNCED_TEXT
  }

  const time = syncedAt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (isSameCalendarDay(syncedAt, now)) {
    return `данные на ${time}`
  }

  const date = syncedAt.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
  return `данные на ${date} ${time}`
}
