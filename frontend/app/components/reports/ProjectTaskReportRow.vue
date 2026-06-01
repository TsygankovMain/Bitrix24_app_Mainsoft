<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ProjectTaskReportNode } from '~/types/report'
import { formatHours } from '~/utils/reportFormat'
import ProjectTaskReportEmployeeRow from './ProjectTaskReportEmployeeRow.vue'

// Рекурсивная самоссылка по имени
defineOptions({ name: 'ProjectTaskReportRow' })

const props = defineProps<{
  node: ProjectTaskReportNode
  depth: number
}>()

const expanded = ref(false)

const isProject = computed(() => props.depth === 0)
const hasChildren = computed(() =>
  !!(props.node.children && props.node.children.length)
  || !!(props.node.employees && props.node.employees.length)
)

const nameClass = computed(() => {
  if (isProject.value) return 'font-bold text-slate-900'
  if (props.depth === 1) return 'font-semibold text-slate-700'
  return 'text-slate-600'
})

function indent(depth: number) {
  return { paddingLeft: `${depth * 20 + 12}px` }
}

function toggle() {
  if (hasChildren.value) expanded.value = !expanded.value
}
</script>

<template>
  <!-- Строка узла (проект / задача / подзадача) -->
  <tr
    class="border-b border-slate-100 transition-colors"
    :class="[
      isProject ? 'bg-blue-50/60 hover:bg-blue-100/60' : 'hover:bg-slate-50',
      hasChildren ? 'cursor-pointer' : ''
    ]"
    @click="toggle"
  >
    <td class="px-4 text-left" :class="isProject ? 'py-3' : 'py-2'">
      <div class="flex items-center gap-2" :style="indent(depth)">
        <span
          v-if="hasChildren"
          class="inline-block w-3 text-xs text-slate-400 transition-transform"
          :class="expanded ? 'rotate-90' : ''"
        >▶</span>
        <span v-else class="inline-block w-3"></span>
        <span :class="nameClass">{{ node.name }}</span>
      </div>
    </td>
    <td
      class="px-4 text-right text-slate-700"
      :class="[isProject ? 'py-3 font-bold' : 'py-2', depth === 1 ? 'font-semibold' : '']"
    >{{ formatHours(node.total_hours) }}</td>
    <td
      class="px-4 text-right text-emerald-600"
      :class="isProject ? 'py-3 font-bold' : 'py-2'"
    >{{ formatHours(node.billable_hours) }}</td>
    <td
      class="px-4 text-right"
      :class="[isProject ? 'py-3 font-bold' : 'py-2', node.non_billable_hours ? 'text-rose-500' : 'text-slate-400']"
    >{{ node.non_billable_hours ? formatHours(node.non_billable_hours) : '—' }}</td>
  </tr>

  <!-- Раскрытое содержимое -->
  <template v-if="expanded">
    <ProjectTaskReportRow
      v-for="(child, idx) in node.children"
      :key="'c' + idx"
      :node="child"
      :depth="depth + 1"
    />
    <ProjectTaskReportEmployeeRow
      v-for="(emp, idx) in node.employees"
      :key="'e' + idx"
      :employee="emp"
      :depth="depth + 1"
    />
  </template>
</template>
