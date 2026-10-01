/**
 * Отчёт «План / факт» — модель таблицы.
 *
 * Здесь только чистые функции: какие строки видны, что в итогах, чему равен
 * остаток. Компонент PlanFactReportTable.vue рисует готовый список — по той же
 * причине, по которой модель меню вынесена в appNavigation.ts: node:test не
 * резолвит .vue, и логика внутри компонента осталась бы без проверки.
 *
 * Цифры считает сервер (main/plan_fact_report.py). Здесь они только
 * складываются по верхнему уровню для строки «Итого».
 */

import type { PlanFactNode } from '~/types/report'

/** Ключ отчёта в ответе /api/features. Отдаётся только порталам из белого списка сервера. */
export const PLAN_FACT_FEATURE_KEY = 'plan_fact_report'

/** Включён ли отчёт для портала — по разобранному ответу /api/features. */
export function isPlanFactEnabled(features: Record<string, { state?: string }> | null | undefined): boolean {
  return features?.[PLAN_FACT_FEATURE_KEY]?.state === 'on'
}

export type PlanFactRow = {
  /** Уникальный путь строки в дереве — ключ раскрытия. */
  key: string
  depth: number
  node: PlanFactNode
  /** Есть что раскрывать. */
  expandable: boolean
  expanded: boolean
}

export type PlanFactTotals = {
  plan: number
  total: number
  billable: number
  nonBillable: number
  plannedFact: number
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/** Факт, с которым сравнивается план. У сотрудника под задачей плана нет — остатка тоже. */
export function plannedFactOf(node: PlanFactNode): number {
  return typeof node.planned_fact_hours === 'number' ? node.planned_fact_hours : num(node.total_hours)
}

/** Остаток = план − факт по задачам с планом. null — плана нет, сравнивать не с чем. */
export function remainderOf(node: PlanFactNode): number | null {
  const plan = num(node.plan_hours)

  return plan > 0 ? plan - plannedFactOf(node) : null
}

/** Выполнение плана в процентах либо null, если плана нет. */
export function completionOf(node: PlanFactNode): number | null {
  const plan = num(node.plan_hours)

  return plan > 0 ? (plannedFactOf(node) / plan) * 100 : null
}

/** Оценка этапа расходится с суммой оценок подзадач. */
export function hasPlanMismatch(node: PlanFactNode): boolean {
  const own = num(node.own_plan_hours)
  const kids = num(node.children_plan_hours)

  return own > 0 && kids > 0 && Math.abs(own - kids) > 0.01
}

export function sumTotals(roots: PlanFactNode[]): PlanFactTotals {
  return roots.reduce<PlanFactTotals>((acc, node) => ({
    plan: acc.plan + num(node.plan_hours),
    total: acc.total + num(node.total_hours),
    billable: acc.billable + num(node.billable_hours),
    nonBillable: acc.nonBillable + num(node.non_billable_hours),
    plannedFact: acc.plannedFact + plannedFactOf(node),
  }), { plan: 0, total: 0, billable: 0, nonBillable: 0, plannedFact: 0 })
}

function childrenOf(node: PlanFactNode): PlanFactNode[] {
  // Сначала сотрудники самой задачи, затем подзадачи — как в выгрузке Excel.
  return [...(node.employees || []), ...(node.children || [])]
}

function matches(node: PlanFactNode, query: string): boolean {
  return `${node.name || ''} ${node.responsible_name || ''}`.toLowerCase().includes(query)
}

/**
 * «Только с планом»: оставляем ветки, где есть план, и сотрудников под ними.
 * Фильтр не пересчитывает цифры — у родителя остаются его итоги.
 */
export function keepPlanned(roots: PlanFactNode[]): PlanFactNode[] {
  const walk = (node: PlanFactNode): PlanFactNode | null => {
    if (num(node.plan_hours) <= 0) {
      return null
    }

    return {
      ...node,
      children: (node.children || []).map(walk).filter((child): child is PlanFactNode => child !== null),
    }
  }

  return roots.map(walk).filter((node): node is PlanFactNode => node !== null)
}

/**
 * Дерево -> видимые строки.
 *
 * Без поиска видимость определяет набор раскрытых ключей. С поиском
 * показывается всё совпавшее вместе с цепочкой родителей (а у совпавшего
 * узла — и его содержимое), раскрытие при этом игнорируется: иначе найденная
 * строка могла бы остаться свёрнутой.
 */
export function flattenPlanFact(
  roots: PlanFactNode[],
  expanded: ReadonlySet<string>,
  search = ''
): PlanFactRow[] {
  const query = search.trim().toLowerCase()
  const rows: PlanFactRow[] = []

  const hasMatch = (node: PlanFactNode): boolean =>
    matches(node, query) || childrenOf(node).some(hasMatch)

  const walk = (node: PlanFactNode, depth: number, key: string, forced: boolean) => {
    const kids = childrenOf(node)
    const selfMatch = query !== '' && matches(node, query)

    if (query !== '' && !forced && !selfMatch && !kids.some(hasMatch)) {
      return
    }

    const isExpanded = query !== '' ? kids.length > 0 : expanded.has(key)
    rows.push({ key, depth, node, expandable: kids.length > 0, expanded: isExpanded })

    if (!isExpanded) {
      return
    }

    kids.forEach((child, index) => {
      walk(child, depth + 1, `${key}/${child.type}:${child.id}:${index}`, forced || selfMatch)
    })
  }

  roots.forEach((root, index) => walk(root, 0, `${root.type}:${root.id}:${index}`, false))

  return rows
}

/** Ключи всех раскрываемых узлов до заданной глубины (0 — ничего не раскрыто). */
export function expandedKeysToDepth(roots: PlanFactNode[], depth: number): Set<string> {
  const keys = new Set<string>()

  const walk = (node: PlanFactNode, level: number, key: string) => {
    const kids = childrenOf(node)
    if (level >= depth || kids.length === 0) {
      return
    }

    keys.add(key)
    kids.forEach((child, index) => walk(child, level + 1, `${key}/${child.type}:${child.id}:${index}`))
  }

  roots.forEach((root, index) => walk(root, 0, `${root.type}:${root.id}:${index}`))

  return keys
}
