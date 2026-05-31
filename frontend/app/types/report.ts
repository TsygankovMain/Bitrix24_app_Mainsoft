export type FilterMode = 'include' | 'exclude'

export interface FilterValue {
  ids?: Array<string | number>
  mode?: FilterMode
}

export interface FilterOption {
  id: string | number
  name: string
  inn?: string | null
  search_text?: string | null
}

export interface ReportFilterOptions {
  employees: FilterOption[]
  projects: FilterOption[]
}

export interface HierarchicalReportNode {
  name: string
  type?: string
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  children?: HierarchicalReportNode[]
}

export interface DailyWorkloadItem {
  task_id?: string | number
  task_name?: string
  project_name?: string
  hours?: number
  billable?: boolean
  [key: string]: unknown
}

export interface DailyWorkloadCell {
  total: number
  status: string
  items: DailyWorkloadItem[]
}

export interface DailyWorkloadDay {
  date: string
  day_name?: string
  day_number?: string | number
}

export interface DailyWorkloadRow {
  employee: {
    id?: string | number
    name: string
  }
  days: Record<string, DailyWorkloadCell | undefined>
}

export interface DailyWorkloadReport {
  header_days: DailyWorkloadDay[]
  rows: DailyWorkloadRow[]
}

export interface RevenueLeakageSummary {
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  loss_rate: number
  project_count: number
  high_risk_project_count: number
  high_risk_employee_count: number
}

export interface RevenueLeakageProjectRow {
  name: string
  total_hours: number
  non_billable_hours: number
  loss_rate: number
}

export interface RevenueLeakageRiskRow {
  project_name: string
  employee_id: string | number
  employee_name: string
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  loss_rate: number
}

export interface RevenueLeakageReport {
  summary: RevenueLeakageSummary
  project_rows: RevenueLeakageProjectRow[]
  risk_rows: RevenueLeakageRiskRow[]
}

export interface TimeDisciplineSummary {
  total_entries: number
  same_day_share: number
  next_day_share: number
  two_plus_share: number
  avg_lag_days: number
  high_risk_employee_count: number
  fallback_entries: number
}

export interface TimeDisciplineLagBucket {
  label: string
  count: number
}

export interface TimeDisciplineEmployeeRow {
  employee_name: string
  entry_count: number
  same_day_share: number
  avg_lag_days: number
  late_entries: number
  max_lag_days: number
  last_late_entry_date?: string | null
  risk_level: string
}

export interface TimeEntryDisciplineReport {
  summary: TimeDisciplineSummary
  lag_buckets: TimeDisciplineLagBucket[]
  employee_rows: TimeDisciplineEmployeeRow[]
}

export interface FocusAnalysisSummary {
  avg_focus_index: number
  avg_entry_size: number
  avg_entries_per_employee: number
  high_risk_employee_count: number
}

export interface FocusAnalysisEmployeeRow {
  employee_name: string
  project_count: number
  task_count: number
  entry_count: number
  total_hours: number
  avg_entry_hours: number
  focus_index: number
  top_project_hours: number
  risk_level: string
}

export interface FocusAnalysisReport {
  summary: FocusAnalysisSummary
  employee_rows: FocusAnalysisEmployeeRow[]
}

export interface ProjectTaskReportItem {
  data?: string
  kolichestvo_chasov?: number
  uchitivaem?: boolean
  nazvanie_zadachi?: string
  opisanie?: string
  id_elem?: string | number
}

export interface ProjectTaskReportEmployee {
  name: string
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  items?: ProjectTaskReportItem[]
}

export interface ProjectTaskReportNode {
  name: string
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  children?: ProjectTaskReportNode[]
  employees?: ProjectTaskReportEmployee[]
}
