<script setup lang="ts">
/**
 * Таблица отчёта «План / факт».
 *
 * Что показывать и что в итогах — решает utils/planFactReport.ts; здесь только
 * разметка и раскрытие строк. Название задачи — ссылка на её карточку: оценку
 * правят там, после чего отчёт формируют заново.
 */
import { computed, ref, watch } from 'vue'
import type { PlanFactNode } from '~/types/report'
import { formatHours } from '~/utils/reportFormat'
import {
  completionOf,
  expandedKeysToDepth,
  flattenPlanFact,
  hasPlanMismatch,
  remainderOf,
  sumTotals,
} from '~/utils/planFactReport'

const props = defineProps<{
  rows: PlanFactNode[]
  search?: string
  /** Подпись первой колонки: зависит от группировки. */
  nameHeader?: string
}>()

const expanded = ref<Set<string>>(new Set())

// Новые данные или другая группировка — ключи прежнего дерева не подходят.
watch(() => props.rows, () => {
  expanded.value = new Set()
})

const visibleRows = computed(() => flattenPlanFact(props.rows, expanded.value, props.search || ''))
const totals = computed(() => sumTotals(props.rows))
const totalsNode = computed<PlanFactNode>(() => ({
  type: 'project',
  id: 'total',
  name: 'Итого',
  plan_hours: totals.value.plan,
  total_hours: totals.value.total,
  billable_hours: totals.value.billable,
  non_billable_hours: totals.value.nonBillable,
  planned_fact_hours: totals.value.plannedFact,
}))

function toggle(key: string, expandable: boolean) {
  if (!expandable || (props.search || '').trim() !== '') {
    return
  }

  const next = new Set(expanded.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expanded.value = next
}

function expandToDepth(depth: number) {
  expanded.value = expandedKeysToDepth(props.rows, depth)
}

defineExpose({ expandToDepth })

function openTask(id: string) {
  const path = `/company/personal/user/0/tasks/task/view/${id}/`
  // @ts-expect-error BX24 подключается порталом и не типизирован на window
  const BX24 = window.BX24

  if (typeof BX24 !== 'undefined') {
    BX24.openPath(path)
  } else {
    window.open(path, '_blank')
  }
}

function isTaskLink(node: PlanFactNode): boolean {
  return node.type === 'task' && /^\d+$/.test(String(node.id))
}

function planText(node: PlanFactNode): string {
  return node.plan_hours ? formatHours(node.plan_hours) : '—'
}

function remainderText(node: PlanFactNode): string {
  const value = remainderOf(node)

  return value === null ? '—' : formatHours(value)
}

function remainderClass(node: PlanFactNode): string {
  const value = remainderOf(node)
  if (value === null) {
    return 'text-slate-400'
  }

  return value < 0 ? 'font-semibold text-rose-600' : 'text-emerald-700'
}

function completionText(node: PlanFactNode): string {
  const value = completionOf(node)

  return value === null ? '—' : `${Math.round(value)}%`
}

function barWidth(node: PlanFactNode): string {
  return `${Math.min(100, Math.max(0, completionOf(node) || 0))}%`
}

function rowClass(depth: number, node: PlanFactNode): string {
  if (depth === 0) {
    return 'bg-blue-50/60 font-bold text-slate-900 hover:bg-blue-100/60'
  }
  if (node.type === 'employee') {
    return 'text-slate-500 hover:bg-slate-50'
  }

  return 'text-slate-700 hover:bg-slate-50'
}
</script>

<template>
  <div class="ms-table-shell">
    <table class="ms-table w-full">
      <thead>
        <tr>
          <th class="text-left">{{ nameHeader || 'Проект / задача / сотрудник' }}</th>
          <th class="text-right">План, ч</th>
          <th class="text-right">Факт всего, ч</th>
          <th class="text-right">Факт учит., ч</th>
          <th class="text-right">Факт неучит., ч</th>
          <th class="text-right" title="План минус факт по задачам, у которых есть план">Остаток, ч</th>
          <th class="text-right">Выполнение</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="rows.length" class="border-b-2 border-slate-300 bg-slate-100 font-bold">
          <td class="px-4 py-3 text-left text-slate-700">Итого</td>
          <td class="px-4 py-3 text-right text-slate-800">{{ planText(totalsNode) }}</td>
          <td class="px-4 py-3 text-right text-slate-800">{{ formatHours(totals.total) }}</td>
          <td class="px-4 py-3 text-right text-emerald-700">{{ formatHours(totals.billable) }}</td>
          <td class="px-4 py-3 text-right text-rose-600">{{ formatHours(totals.nonBillable) }}</td>
          <td class="px-4 py-3 text-right" :class="remainderClass(totalsNode)">{{ remainderText(totalsNode) }}</td>
          <td class="px-4 py-3 text-right text-slate-700">{{ completionText(totalsNode) }}</td>
        </tr>

        <tr
          v-for="row in visibleRows"
          :key="row.key"
          class="border-b border-slate-100 transition-colors"
          :class="[rowClass(row.depth, row.node), row.expandable ? 'cursor-pointer' : '']"
          @click="toggle(row.key, row.expandable)"
        >
          <td class="px-4 py-2 text-left">
            <div class="flex items-start gap-2" :style="{ paddingLeft: `${row.depth * 20}px` }">
              <span
                v-if="row.expandable"
                class="mt-0.5 inline-block w-3 shrink-0 text-xs text-slate-400 transition-transform"
                :class="row.expanded ? 'rotate-90' : ''"
              >▶</span>
              <span v-else class="inline-block w-3 shrink-0" />
              <span class="min-w-0">
                <span
                  v-if="isTaskLink(row.node)"
                  class="whitespace-normal break-words text-[#0075ff] hover:underline"
                  title="Открыть задачу"
                  @click.stop="openTask(row.node.id)"
                >{{ row.node.name }}</span>
                <span
                  v-else
                  class="whitespace-normal break-words"
                  :class="row.node.type === 'employee' ? 'italic' : ''"
                >{{ row.node.name }}</span>
                <span
                  v-if="hasPlanMismatch(row.node)"
                  class="ml-2 rounded bg-amber-100 px-1.5 text-xs font-normal text-amber-800"
                  :title="`Оценка этапа ${formatHours(row.node.own_plan_hours)} ч, сумма оценок подзадач ${formatHours(row.node.children_plan_hours)} ч`"
                >≠ подзадачи {{ formatHours(row.node.children_plan_hours) }}</span>
                <span
                  v-if="row.node.is_closed"
                  class="ml-2 rounded bg-emerald-50 px-1.5 text-xs font-normal text-emerald-700"
                >завершена</span>
                <span
                  v-if="row.node.responsible_name"
                  class="ml-2 text-xs font-normal text-slate-400"
                >{{ row.node.responsible_name }}</span>
              </span>
            </div>
          </td>
          <td class="px-4 py-2 text-right">{{ planText(row.node) }}</td>
          <td class="px-4 py-2 text-right">{{ formatHours(row.node.total_hours) }}</td>
          <td class="px-4 py-2 text-right text-emerald-600">{{ formatHours(row.node.billable_hours) }}</td>
          <td
            class="px-4 py-2 text-right"
            :class="row.node.non_billable_hours ? 'text-rose-500' : 'text-slate-400'"
          >{{ row.node.non_billable_hours ? formatHours(row.node.non_billable_hours) : '—' }}</td>
          <td class="px-4 py-2 text-right" :class="remainderClass(row.node)">{{ remainderText(row.node) }}</td>
          <td class="whitespace-nowrap px-4 py-2 text-right font-normal">
            <template v-if="completionOf(row.node) !== null">
              <span class="mr-2 inline-block h-1.5 w-12 overflow-hidden rounded bg-slate-200 align-middle">
                <span
                  class="block h-full"
                  :class="(completionOf(row.node) || 0) > 100 ? 'bg-rose-500' : 'bg-[#0075ff]'"
                  :style="{ width: barWidth(row.node) }"
                />
              </span>{{ completionText(row.node) }}
            </template>
            <span v-else class="text-slate-400">—</span>
          </td>
        </tr>

        <tr v-if="rows.length && visibleRows.length === 0">
          <td colspan="7" class="px-4 py-6 text-center text-slate-400">По запросу ничего не найдено</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
