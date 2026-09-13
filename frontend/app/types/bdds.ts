/**
 * Контракт функции «БДДС по проектам», этап 1.
 *
 * Строка реестра — это ТА ЖЕ карточка проекта, что на доске, плюс метрики
 * бюджета и прогноз. Поэтому поля названы так же, как в
 * types/project-board.ts, и утилиты доски (полоса освоения, поиск, риск)
 * читают их напрямую — третьего описания проекта в приложении не
 * появляется.
 *
 * Чего здесь НЕТ: статей ДДС, плана по месяцам, колонки «в ожидании» и
 * корректировок. Это этапы 2 и 3, они ждут ответов пользователя (записка к
 * макету, вопросы 1, 2, 5, 7, 8). Пустое поле «в ожидании» читалось бы как
 * «денег в пути нет», а это не то же самое, что «мы этого ещё не считаем».
 */

import type { ProjectBudgetHealthStatus, ProjectFinanceOperationRecord } from './project-board'

export type { ProjectBudgetHealthStatus, ProjectFinanceOperationRecord }

/** Как посчитан прогноз. Пока один способ — линейный темп (вариант A). */
export type BddsForecastMethod = 'linear_pace' | string

export interface BddsProjectRecord {
  project_id: string
  project_item_id: string | null
  project_name: string
  stage: string
  is_archived: boolean
  is_support: boolean
  project_type: 'delivery' | 'support' | string
  budget_mode: 'hours' | 'amount' | 'hours_and_amount' | 'support' | string
  hourly_rate: number
  project_hours_budget: number | null
  planned_budget_amount: number | null
  curator_user_id: string | null
  curator_name: string | null
  company_id: string | null
  company_name: string | null
  our_legal_entity_id: string | null
  our_legal_entity_name: string | null
  project_start_date: string | null
  project_end_date: string | null
  last_writeoff_at: string | null
  last_writeoff_days: number

  // --- Метрики бюджета ---
  planned_hours: number | null
  planned_amount: number | null
  actual_hours: number
  actual_cost_amount: number
  actual_income_amount: number
  actual_expense_amount: number
  actual_financial_result: number
  hours_remaining: number | null
  budget_remaining: number | null
  budget_utilization_mode: 'hours' | 'amount' | 'none' | 'support' | string
  budget_utilization_ratio: number | null
  budget_utilization_percent: number | null
  budget_health_status: ProjectBudgetHealthStatus
  budget_health_reason?: string | null
  support_health_status?: ProjectBudgetHealthStatus | null
  support_health_reason?: string | null
  risk_threshold_ratio: number
  overrun_threshold_ratio: number

  /**
   * У проекта есть плановый лимит.
   *
   * Отдаётся сервером явно, а не выводится из нулей: «плана нет» и «план
   * ноль» — разные вещи, и у поддержки плана нет по существу.
   */
  has_budget: boolean

  /**
   * Часы, у которых на списании нет снимка ставки.
   *
   * Их стоимость посчитана по ТЕКУЩЕЙ ставке карточки, то есть это оценка,
   * а не факт. На стенде такие записи есть, и интерфейс обязан это
   * подписать.
   */
  actual_hours_without_rate_snapshot: number
  fallback_hourly_rate: number

  // --- Прогноз ---
  forecast_cost_amount: number | null
  forecast_overrun_amount: number | null
  forecast_monthly_rate: number | null
  forecast_months_elapsed: number | null
  forecast_months_left: number | null
  forecast_method: BddsForecastMethod
  forecast_reason: string

  recent_finance_operations?: ProjectFinanceOperationRecord[]
}

export interface BddsTotals {
  projects_count: number
  with_budget_count: number
  without_budget_count: number
  planned_amount: number
  planned_hours: number
  actual_cost_amount: number
  actual_cost_amount_with_budget: number
  actual_hours: number
  actual_income_amount: number
  actual_expense_amount: number
  actual_financial_result: number
  budget_remaining: number | null
  budget_utilization_percent: number | null
}

export interface BddsThresholds {
  risk_percent: number
  overrun_percent: number
  support_boundary_amount: number
  notifications_enabled: boolean
  notify_cooldown_hours: number
  notify_user_ids: string[]
}

export interface BddsProjectsResponse {
  projects: BddsProjectRecord[]
  totals: BddsTotals
  status_counts: Record<string, number>
  thresholds: BddsThresholds
}

export interface BddsProjectResponse {
  project: BddsProjectRecord
  thresholds: BddsThresholds
}

export interface BddsNotifierRunResult {
  status: string
  source?: string
  checked?: number
  sent?: number
  skipped?: number
  cooldown_skipped?: number
  errors?: number
  events?: Array<{
    project_id?: string
    project_name?: string
    event_code?: string
    status?: string
    reason?: string
    recipients?: string[]
  }>
}

// ---------------------------------------------------------------------------
// Операции «поступление / списание» по проектам
// ---------------------------------------------------------------------------
//
// Ответ GET /api/finance-operations. Сама операция описана ОДИН раз —
// ProjectFinanceOperationRecord в types/project-board.ts, и второго описания
// здесь не появляется: это те же элементы смарт-процесса, что участвуют в
// расчёте бюджета проекта. Здесь только обвязка страницы: сколько их,
// есть ли ещё и итоги по выборке.

/** Тип операции в интерфейсе. Строка — потому что портал пишет по-разному. */
export type BddsOperationType = 'income' | 'expense'

/** Итоги по ВЫБОРКЕ (не по видимой странице): сервер считает при totals=1. */
export interface BddsOperationTotals {
  income: number
  expense: number
  /** Поступления минус списания. Не финрезультат проекта: часов здесь нет. */
  net: number
  count: number
}

export interface BddsOperationsResponse {
  operations: ProjectFinanceOperationRecord[]
  count: number
  entity_type_id?: number
  offset?: number
  limit?: number
  /**
   * Всего операций в выборке — либо null.
   *
   * null означает «сервер не считал»: на коротком пути он видел окно
   * страницы, а не всю выборку. Показывать вместо этого длину окна значило
   * бы выдать 21 операцию за все операции проекта.
   */
  total?: number | null
  has_more?: boolean
  /** Выборка длиннее предела одного прохода: показано не всё. */
  truncated?: boolean
  totals?: BddsOperationTotals | null
}

export interface BddsOperationCreatePayload {
  project_item_id: string
  operation_type: BddsOperationType
  amount: number
  operation_date: string
  /** Назначение платежа — заголовок элемента смарт-процесса. */
  title?: string | null
  comment?: string | null
  currency?: string | null
  source?: string | null
  deal_id?: string | null
  responsible_user_id?: string | null
}
