export const PROJECT_STAGE_ORDER = [
  'Новый',
  'В просчете',
  'В работе',
  'Нет списаний 1 месяц',
  'Нет списаний 3 месяца',
  'Успех',
  'Провал'
] as const

export const PROJECT_MANUAL_STAGES = [
  'Новый',
  'В просчете',
  'В работе',
  'Успех',
  'Провал'
] as const

export type ProjectBoardStage = typeof PROJECT_STAGE_ORDER[number]

export interface ProjectBoardDirectoryOption {
  id: string | number
  name: string | number
  inn?: string | null
  is_my_company?: boolean
  search_text?: string | null
}

export interface ProjectBoardCardRecord {
  id: string
  project_item_id: string | null
  project_id: string
  project_name: string
  stage: ProjectBoardStage | string
  manual_stage: ProjectBoardStage | string | null
  is_archived: boolean
  archived_at: string | null
  project_hours_budget: number | null
  hourly_rate: number
  project_income: number | null
  project_expense: number | null
  is_support: boolean
  curator_user_id: string | null
  curator_name: string | null
  project_start_date: string | null
  project_end_date: string | null
  company_id: string | null
  company_name: string | null
  company_inn?: string | null
  our_legal_entity_id: string | null
  our_legal_entity_name: string | null
  our_legal_entity_inn?: string | null
  last_writeoff_at: string | null
  last_writeoff_days: number
  stage_source: 'manual' | 'auto' | string
  created_at: string | null
  updated_at: string | null
}

export interface ProjectBoardSummary {
  total_count: number
  active_count: number
  archived_count: number
  support_count: number
  inactive_30_count: number
  inactive_90_count: number
}

export interface ProjectBoardResponse {
  stages: Array<{
    id: ProjectBoardStage | string
    title: string
    kind: 'manual' | 'auto'
    can_drop: boolean
  }>
  cards: ProjectBoardCardRecord[]
  warning?: string
  summary: ProjectBoardSummary
}

export interface ProjectBoardMetaPayload {
  filters?: {
    curators?: ProjectBoardDirectoryOption[]
    companies?: ProjectBoardDirectoryOption[]
    legal_entities?: ProjectBoardDirectoryOption[]
  }
  directories?: {
    employees?: ProjectBoardDirectoryOption[]
    companies?: ProjectBoardDirectoryOption[]
    legal_entities?: ProjectBoardDirectoryOption[]
  }
  employees?: ProjectBoardDirectoryOption[]
  companies?: ProjectBoardDirectoryOption[]
  legal_entities?: ProjectBoardDirectoryOption[]
  warning?: string
}
