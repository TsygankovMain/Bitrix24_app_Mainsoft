/**
 * Закрытие месяца. Спека: docs/architecture/period-closing-spec.md
 */

/** Находка проверки. code нужен, чтобы запросить список записей за ней. */
export interface PeriodFinding {
  code: string
  title: string
  why: string
  count: number
}

export interface PeriodStats {
  hours: number
  entries: number
  projects: number
  employees: number
}

/**
 * Результат проверки перед закрытием.
 *
 * can_close считает СЕРВЕР — экран его только показывает. Полагаться на
 * пустоту blockers на клиенте нельзя: сервер всё равно проверит повторно при
 * закрытии, потому что кнопку можно обойти.
 */
export interface PeriodCheckResult {
  period: { year: number, month: number, title: string }
  can_close: boolean
  blockers: PeriodFinding[]
  warnings: PeriodFinding[]
  stats: PeriodStats
}

export interface PeriodRow {
  year: number
  month: number
  title: string
  hours: number
  entries: number
  closed: boolean
  closed_at?: string
  closed_by_name?: string
  reopened_at?: string
  reopened_by_name?: string
  reopen_reason?: string
  /** Часы, пришедшие в Битриксе уже после закрытия периода. */
  late_arrivals?: number
}

export interface PeriodEntryRow {
  bitrix_id: number
  task_id: string
  employee_id: string
  hours: number
  project_title?: string
  date: string | null
  created_at?: string | null
}
