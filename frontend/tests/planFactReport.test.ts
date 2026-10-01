import test from 'node:test'
import assert from 'node:assert/strict'

import {
  completionOf,
  expandedKeysToDepth,
  flattenPlanFact,
  hasPlanMismatch,
  isPlanFactEnabled,
  keepPlanned,
  remainderOf,
  sumTotals,
} from '../app/utils/planFactReport'
import type { PlanFactNode } from '../app/types/report'

function node(partial: Partial<PlanFactNode> & Pick<PlanFactNode, 'type' | 'id' | 'name'>): PlanFactNode {
  return { total_hours: 0, billable_hours: 0, non_billable_hours: 0, ...partial }
}

const TREE: PlanFactNode[] = [
  node({
    type: 'project', id: '209', name: 'НАВИГАТОР АО',
    plan_hours: 960, total_hours: 206, billable_hours: 170, non_billable_hours: 36, planned_fact_hours: 156,
    children: [
      node({
        type: 'task', id: '6063', name: '6. Моделирование', responsible_name: 'Гареева Светлана',
        plan_hours: 960, own_plan_hours: 960, children_plan_hours: 360,
        total_hours: 156, billable_hours: 120, non_billable_hours: 36, planned_fact_hours: 156,
        employees: [node({ type: 'employee', id: '1217', name: 'Ухина Дарья', total_hours: 6, non_billable_hours: 6 })],
        children: [
          node({
            type: 'task', id: '6287', name: '6.1. Баязитова', plan_hours: 200, own_plan_hours: 200,
            total_hours: 150, billable_hours: 120, non_billable_hours: 30, planned_fact_hours: 150,
            employees: [node({ type: 'employee', id: '1199', name: 'Баязитова Алсу', total_hours: 150 })],
          }),
        ],
      }),
      node({ type: 'task', id: '9000', name: 'Задача без оценки', total_hours: 50, billable_hours: 50, planned_fact_hours: 0 }),
    ],
  }),
  node({ type: 'project', id: '25', name: 'ИТ-ЛАБ', total_hours: 40, non_billable_hours: 40, planned_fact_hours: 0 }),
]

test('isPlanFactEnabled: включено только при ключе plan_fact_report в состоянии on', () => {
  assert.equal(isPlanFactEnabled(null), false)
  assert.equal(isPlanFactEnabled({}), false)
  assert.equal(isPlanFactEnabled({ bdds: { state: 'on' } }), false)
  assert.equal(isPlanFactEnabled({ plan_fact_report: { state: 'off' } }), false)
  assert.equal(isPlanFactEnabled({ plan_fact_report: { state: 'on' } }), true)
})

test('остаток и выполнение считаются от факта по задачам с планом', () => {
  const project = TREE[0]!

  assert.equal(remainderOf(project), 804)
  assert.equal(Math.round(completionOf(project)!), 16)
  assert.equal(remainderOf(TREE[1]!), null)
  assert.equal(completionOf(TREE[1]!), null)
})

test('hasPlanMismatch: оценка этапа расходится с суммой подзадач', () => {
  const stage = TREE[0]!.children![0]!

  assert.equal(hasPlanMismatch(stage), true)
  assert.equal(hasPlanMismatch(stage.children![0]!), false)
})

test('sumTotals: итог по верхнему уровню', () => {
  assert.deepEqual(sumTotals(TREE), { plan: 960, total: 246, billable: 170, nonBillable: 76, plannedFact: 156 })
})

test('flattenPlanFact: свёрнуто — только верхний уровень, раскрытие показывает сотрудников и подзадачи', () => {
  assert.deepEqual(flattenPlanFact(TREE, new Set()).map(row => row.node.name), ['НАВИГАТОР АО', 'ИТ-ЛАБ'])

  const all = flattenPlanFact(TREE, expandedKeysToDepth(TREE, 99))
  assert.deepEqual(all.map(row => `${row.depth}:${row.node.name}`), [
    '0:НАВИГАТОР АО', '1:6. Моделирование', '2:Ухина Дарья', '2:6.1. Баязитова', '3:Баязитова Алсу',
    '1:Задача без оценки', '0:ИТ-ЛАБ',
  ])
  assert.equal(all[all.length - 1]!.expandable, false)

  const oneLevel = flattenPlanFact(TREE, expandedKeysToDepth(TREE, 1))
  assert.deepEqual(oneLevel.map(row => row.node.name), ['НАВИГАТОР АО', '6. Моделирование', 'Задача без оценки', 'ИТ-ЛАБ'])
})

test('flattenPlanFact: поиск показывает совпадение с родителями и не зависит от раскрытия', () => {
  const found = flattenPlanFact(TREE, new Set(), 'баязитова')

  assert.deepEqual(found.map(row => row.node.name), ['НАВИГАТОР АО', '6. Моделирование', '6.1. Баязитова', 'Баязитова Алсу'])
  assert.deepEqual(flattenPlanFact(TREE, new Set(), 'гареева').map(row => row.node.name).slice(0, 2), ['НАВИГАТОР АО', '6. Моделирование'])
  assert.deepEqual(flattenPlanFact(TREE, new Set(), 'нет такого'), [])
})

test('keepPlanned: остаются только ветки с планом, цифры родителя не пересчитываются', () => {
  const planned = keepPlanned(TREE)

  assert.deepEqual(planned.map(item => item.name), ['НАВИГАТОР АО'])
  assert.deepEqual(planned[0]!.children!.map(item => item.name), ['6. Моделирование'])
  assert.equal(planned[0]!.total_hours, 206)
})
