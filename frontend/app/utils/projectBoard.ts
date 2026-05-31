import type {
  ProjectBudgetHealthStatus,
  ProjectBoardCardRecord,
  ProjectBoardResponse,
  ProjectBoardStage,
} from '../types/project-board'

export type {
  ProjectBudgetHealthStatus,
  ProjectBudgetSnapshot,
  ProjectFinanceOperationRecord,
  ProjectBoardCardRecord,
  ProjectBoardDirectoryOption,
  ProjectBoardMetaPayload,
  ProjectBoardResponse,
  ProjectBoardStage,
  ProjectBoardSummary,
} from '../types/project-board'

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

export const PROJECT_BUDGET_STATUS_META: Record<ProjectBudgetHealthStatus, string> = {
  'Норма': 'bg-emerald-100 text-emerald-700',
  'Риск': 'bg-amber-100 text-amber-800',
  'Перерасход': 'bg-rose-100 text-rose-700',
  'Без лимита': 'bg-slate-200 text-slate-700',
  'Плюс': 'bg-emerald-100 text-emerald-700',
  'Граница': 'bg-amber-100 text-amber-800',
  'Минус': 'bg-rose-100 text-rose-700',
}

const PROJECT_STAGE_FALLBACK_PALETTE = [
  {
    badge: 'bg-sky-100 text-sky-700',
    column: 'from-sky-50 to-white',
  },
  {
    badge: 'bg-emerald-100 text-emerald-700',
    column: 'from-emerald-50 to-white',
  },
  {
    badge: 'bg-amber-100 text-amber-700',
    column: 'from-amber-50 to-white',
  },
  {
    badge: 'bg-cyan-100 text-cyan-700',
    column: 'from-cyan-50 to-white',
  },
  {
    badge: 'bg-fuchsia-100 text-fuchsia-700',
    column: 'from-fuchsia-50 to-white',
  },
  {
    badge: 'bg-slate-200 text-slate-700',
    column: 'from-slate-100 to-white',
  },
] as const

function getFallbackStageMeta(stage: string) {
  const normalized = String(stage || '').trim()
  const defaultMeta = PROJECT_STAGE_FALLBACK_PALETTE[PROJECT_STAGE_FALLBACK_PALETTE.length - 1] ?? {
    badge: 'bg-slate-200 text-slate-700',
    column: 'from-slate-100 to-white',
  }
  if (!normalized) {
    return defaultMeta
  }

  const hash = Array.from(normalized).reduce((acc, char) => acc + char.charCodeAt(0), 0)
  return PROJECT_STAGE_FALLBACK_PALETTE[hash % PROJECT_STAGE_FALLBACK_PALETTE.length] ?? defaultMeta
}

export function getStageBadgeClass(stage: string) {
  return PROJECT_STAGE_META[stage as ProjectBoardStage]?.badge || getFallbackStageMeta(stage).badge
}

export function getStageColumnClass(stage: string) {
  return PROJECT_STAGE_META[stage as ProjectBoardStage]?.column || getFallbackStageMeta(stage).column
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

export function formatProjectCurrency(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 0
  }).format(Number(value))} ₽`
}

export function formatProjectHours(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${Number(value).toFixed(0)} ч`
}

export function formatProjectPercent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${Number(value).toFixed(1)}%`
}

export function getBudgetStatusBadgeClass(status?: ProjectBudgetHealthStatus | null) {
  const normalizedStatus = String(status || '').trim() as ProjectBudgetHealthStatus
  return PROJECT_BUDGET_STATUS_META[normalizedStatus] || PROJECT_BUDGET_STATUS_META['Без лимита']
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
    if (year === undefined || month === undefined || day === undefined) {
      return new Date(value)
    }
    return new Date(year, month - 1, day)
  }

  return new Date(value)
}

export function buildProjectBoardSummary(cards: ProjectBoardCardRecord[]): ProjectBoardResponse['summary'] {
  return {
    total_count: cards.length,
    active_count: cards.filter(card => !card.is_archived).length,
    archived_count: cards.filter(card => card.is_archived).length,
    support_count: cards.filter(card => !card.is_archived && card.is_support).length,
    inactive_30_count: cards.filter(card => !card.is_archived && card.stage === 'Нет списаний 1 месяц').length,
    inactive_90_count: cards.filter(card => !card.is_archived && card.stage === 'Нет списаний 3 месяца').length
  }
}

export function upsertProjectBoardCard(cards: ProjectBoardCardRecord[], updatedCard: ProjectBoardCardRecord) {
  const nextCards = [...cards]
  const currentIndex = nextCards.findIndex(card => card.project_id === updatedCard.project_id)

  if (currentIndex === -1) {
    nextCards.unshift(updatedCard)
  } else {
    nextCards.splice(currentIndex, 1, updatedCard)
  }

  return nextCards
}
