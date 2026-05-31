// Типы дозаполнения ИНН в карточках списания (Спринт 2)

export type InnRowStatus = 'ready' | 'attention' | 'no_project'

export interface InnBackfillKpi {
  total: number
  without_inn: number
  resolvable: number
  attention: number
}

export interface InnBackfillRow {
  bitrix_id: number | string
  date?: string | null
  employee_id?: string
  employee_name?: string
  task?: string
  project_id?: string
  project_name?: string
  our_blank: boolean
  client_blank: boolean
  suggest_our_inn: string
  suggest_client_inn: string
  status: InnRowStatus
}

export interface InnBackfillGroup {
  key: string
  project_name: string
  project_id?: string
  our_inn: string
  client_inn: string
  count: number
  rows: InnBackfillRow[]
}

export interface InnScanResult {
  kpi: InnBackfillKpi
  groups: InnBackfillGroup[]
  warning?: string | null
}

export interface InnApplyItem {
  bitrix_id: number | string
  our_inn?: string
  client_inn?: string
}

export interface InnApplyFailure {
  bitrix_id: number | string
  error: string
}

export interface InnApplyResult {
  status: string
  updated: number
  failed: InnApplyFailure[]
  truncated?: boolean
}

export interface InnProjectItemsResult {
  items: InnApplyItem[]
  total: number
}

export interface ProjectHealthRow {
  project_id: string
  project_name: string
  has_company: boolean
  has_legal_entity: boolean
  client_inn: string
  our_inn: string
}

export interface ProjectsHealthResult {
  projects: ProjectHealthRow[]
}
