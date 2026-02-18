<script setup lang="ts">
import type { PropType } from 'vue'
import RecursiveTableRow from './RecursiveTableRow.vue'

defineProps({
  data: {
    type: Array as PropType<any[]>,
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
  <div class="overflow-x-auto border rounded-lg">
    <table class="min-w-full divide-y divide-gray-200">
      <thead class="bg-gray-50">
        <tr>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-[40%]">Структура</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Всего</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Учит.</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Не учит.</th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Тип</th>
        </tr>
      </thead>
      <tbody class="bg-white divide-y divide-gray-200">
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

