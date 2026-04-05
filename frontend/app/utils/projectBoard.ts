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

export interface ProjectBoardCardRecord {
  id: string
  project_id: string
  project_name: string
  stage: ProjectBoardStage | string
  manual_stage: ProjectBoardStage | string | null
  is_archived: boolean
  archived_at: string | null
  project_hours_budget: number | null
  hourly_rate: number
  is_support: boolean
  curator_user_id: string | null
  curator_name: string | null
  project_start_date: string | null
  project_end_date: string | null
  company_id: string | null
  company_name: string | null
  our_legal_entity_id: string | null
  our_legal_entity_name: string | null
  last_writeoff_at: string | null
  last_writeoff_days: number
  stage_source: 'manual' | 'auto' | string
  created_at: string | null
  updated_at: string | null
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
  summary: {
    total_count: number
    active_count: number
    archived_count: number
    support_count: number
    inactive_30_count: number
    inactive_90_count: number
  }
}

export const PROJECT_STAGE_META = {
  'Новый': {
    badge: 'bg-sky-100 text-sky-700',
    column: 'from-sky-50 to-white',
  },
  'В просчете': {
    badge: 'bg-amber-100 text-amber-700',
    column: 'from-amber-50 to-white',
  },
  'В работе': {
    badge: 'bg-emerald-100 text-emerald-700',
    column: 'from-emerald-50 to-white',
  },
  'Нет списаний 1 месяц': {
    badge: 'bg-orange-100 text-orange-700',
    column: 'from-orange-50 to-white',
  },
  'Нет списаний 3 месяца': {
    badge: 'bg-rose-100 text-rose-700',
    column: 'from-rose-50 to-white',
  },
  'Успех': {
    badge: 'bg-lime-100 text-lime-700',
    column: 'from-lime-50 to-white',
  },
  'Провал': {
    badge: 'bg-slate-200 text-slate-700',
    column: 'from-slate-100 to-white',
  }
} as const

export function getStageBadgeClass(stage: string) {
  return PROJECT_STAGE_META[stage as ProjectBoardStage]?.badge || 'bg-gray-100 text-gray-700'
}

export function getStageColumnClass(stage: string) {
  return PROJECT_STAGE_META[stage as ProjectBoardStage]?.column || 'from-gray-50 to-white'
}

export function formatProjectDate(value?: string | null) {
  if (!value) {
    return 'Не задано'
  }

  const parsed = parseProjectDateValue(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  }).format(parsed)
}

export function formatProjectMoney(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${Number(value).toFixed(0)} ₽/ч`
}

export function formatProjectHours(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${Number(value).toFixed(0)} ч`
}

export function getTimelineAnchor(card: ProjectBoardCardRecord) {
  return card.project_start_date || card.last_writeoff_at || card.created_at || card.updated_at
}

export function parseProjectDateValue(value?: string | null) {
  if (!value) {
    return new Date('')
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split('-').map(Number)
    return new Date(year, month - 1, day)
  }

  return new Date(value)
}
