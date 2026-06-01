<script setup lang="ts">
import type { PropType } from 'vue'
import type { HierarchicalReportNode } from '~/types/report'
import RecursiveTableRow from './RecursiveTableRow.vue'

defineProps({
  data: {
    type: Array as PropType<HierarchicalReportNode[]>,
    required: true
  },
  clickableLabels: {
    type: Boolean,
    default: false
  },
  entityTypeId: {
    type: [String, Number],
    default: 0
  }
})
</script>

<template>
  <div class="ms-table-shell">
    <table class="ms-table">
      <thead>
        <tr>
          <th class="w-[40%]">Структура</th>
          <th>Всего</th>
          <th>Учит.</th>
          <th>Не учит.</th>
          <th>Тип</th>
        </tr>
      </thead>
      <tbody>
        <RecursiveTableRow 
            v-for="node in data" 
            :key="node.id" 
            :node="node" 
            :level="0"
            :clickable-labels="clickableLabels"
            :entity-type-id="entityTypeId"
        />
      </tbody>
    </table>
  </div>
</template>
