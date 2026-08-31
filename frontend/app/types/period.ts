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

/**
 * План массового закрытия.
 *
 * status = "confirmation_required" приходит с кодом 409 и означает «ничего не
 * закрыто, подтвердите». Это штатный ответ, а не сбой: сервер сначала
 * показывает, что именно предлагается принять.
 */
export interface PeriodBulkPlan {
  status: 'confirmation_required' | 'closed' | 'nothing_to_close'
  code?: string
  periods?: Array<{
    year: number
    month: number
    title: string
    stats: PeriodStats
    blockers: PeriodFinding[]
  }>
  total?: {
    periods: number
    hours: number
    entries: number
    /** Сколько периодов замораживается со сломанными данными. */
    with_blockers: number
  }
  closed?: Array<{ year: number, month: number, title: string }>
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

/**
 * Ответ на исправление находки.
 *
 * check — свежая проверка ПОСЛЕ правки. Именно она показывает, что реально
 * поправилось: часть карточек Битрикс может отвергнуть, а часть задач
 * окажется без рабочей группы (unfixable_tasks) — для них верного проекта
 * попросту не существует, и это не сбой.
 */
export interface PeriodFixResult {
  status: 'done' | 'not_fixable' | 'period_closed'
  code: string
  error?: string
  attempted_tasks?: number
  unfixable_tasks?: number
  check?: PeriodCheckResult
}

/**
 * Находки, у которых на экране есть кнопка «Исправить».
 *
 * Список дублирует FIXABLE_CODES бэкенда (period_fix_service) осознанно:
 * экран должен знать, рисовать ли кнопку, ДО запроса. Сервер всё равно
 * проверяет код сам и отвечает 409 на всё остальное — здесь это лишь подсказка
 * интерфейсу, а не правило.
 */
export const FIXABLE_CODES = ['diverged_project', 'no_project']
