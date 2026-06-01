<script setup lang="ts">
import { ref, computed, inject } from 'vue'
import type { ProjectTaskReportEmployee } from '~/types/report'
import { formatHours, formatReportDate } from '~/utils/reportFormat'
import { PROJECT_TASK_LABEL_KEY } from '~/composables/useProjectTaskLabel'

const props = defineProps<{
  employee: ProjectTaskReportEmployee
  depth: number
}>()

const expanded = ref(false)
const hasItems = computed(() => !!(props.employee.items && props.employee.items.length))

// Кликабельные метки времени (provide со страницы отчёта)
const labelCtx = inject(PROJECT_TASK_LABEL_KEY, undefined)
const labelClickable = computed(() => !!labelCtx?.enabled.value)

function indent(depth: number) {
  return { paddingLeft: `${depth * 20 + 12}px` }
}

function toggle() {
  if (hasItems.value) expanded.value = !expanded.value
}
</script>

<template>
  <!-- Строка сотрудника -->
  <tr
    class="border-b border-slate-100 transition-colors hover:bg-slate-50"
    :class="hasItems ? 'cursor-pointer' : ''"
    @click="toggle"
  >
    <td class="px-4 py-2 text-left">
      <div class="flex items-center gap-2" :style="indent(depth)">
        <span
          v-if="hasItems"
          class="inline-block w-3 text-xs text-slate-400 transition-transform"
          :class="expanded ? 'rotate-90' : ''"
        >▶</span>
        <span v-else class="inline-block w-3"/>
        <span class="text-slate-600">{{ employee.name }}</span>
      </div>
    </td>
    <td class="px-4 py-2 text-right text-slate-600">{{ formatHours(employee.total_hours) }}</td>
    <td class="px-4 py-2 text-right text-emerald-600">{{ formatHours(employee.billable_hours) }}</td>
    <td
      class="px-4 py-2 text-right"
      :class="employee.non_billable_hours ? 'text-rose-500' : 'text-slate-400'"
    >{{ employee.non_billable_hours ? formatHours(employee.non_billable_hours) : '—' }}</td>
  </tr>

  <!-- Метки времени -->
  <template v-if="expanded && employee.items">
    <tr
      v-for="(item, idx) in employee.items"
      :key="idx"
      class="border-b border-slate-100/60 bg-slate-50/60 text-xs"
    >
      <td class="px-4 py-1.5 text-left">
        <div class="flex items-center gap-2" :style="indent(depth + 1)">
          <span
            v-if="labelClickable && item.id_elem"
            class="cursor-pointer text-[#0075ff] hover:text-blue-700 hover:underline"
            @click.stop="labelCtx!.onClick(item.id_elem)"
          >{{ item.nazvanie_zadachi || item.opisanie || 'Без названия' }}</span>
          <span v-else class="text-slate-500">{{ item.nazvanie_zadachi || item.opisanie || 'Без названия' }}</span>
          <span class="text-slate-400">{{ formatReportDate(item.data) }}</span>
        </div>
      </td>
      <td class="px-4 py-1.5 text-right text-slate-500">{{ formatHours(item.kolichestvo_chasov) }}</td>
      <td
        class="px-4 py-1.5 text-right"
        :class="item.uchitivaem ? 'text-emerald-600' : 'text-slate-400'"
      >{{ item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</td>
      <td
        class="px-4 py-1.5 text-right"
        :class="!item.uchitivaem ? 'text-rose-500' : 'text-slate-400'"
      >{{ !item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</td>
    </tr>
  </template>
</template>
