<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectTaskReportNode } from '~/types/report'
import { formatHours } from '~/utils/reportFormat'
import ProjectTaskReportRow from './ProjectTaskReportRow.vue'

const props = defineProps<{
  rows: ProjectTaskReportNode[]
}>()

const totals = computed(() => ({
  total: props.rows.reduce((s, n) => s + (n.total_hours || 0), 0),
  billable: props.rows.reduce((s, n) => s + (n.billable_hours || 0), 0),
  nonBillable: props.rows.reduce((s, n) => s + (n.non_billable_hours || 0), 0)
}))
</script>

<template>
  <div class="ms-table-shell">
    <table class="ms-table w-full">
      <thead>
        <tr>
          <th class="text-left">Название</th>
          <th class="text-right">Всего, ч</th>
          <th class="text-right">Учтено, ч</th>
          <th class="text-right">Не учтено, ч</th>
        </tr>
      </thead>
      <tbody>
        <ProjectTaskReportRow
          v-for="(node, idx) in rows"
          :key="idx"
          :node="node"
          :depth="0"
        />

        <!-- ИТОГО -->
        <tr v-if="rows.length" class="border-t-2 border-slate-300 bg-slate-100 font-bold">
          <td class="px-4 py-3 text-left text-slate-700">ИТОГО</td>
          <td class="px-4 py-3 text-right text-slate-800">{{ formatHours(totals.total) }}</td>
          <td class="px-4 py-3 text-right text-emerald-700">{{ formatHours(totals.billable) }}</td>
          <td class="px-4 py-3 text-right text-rose-600">{{ formatHours(totals.nonBillable) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
