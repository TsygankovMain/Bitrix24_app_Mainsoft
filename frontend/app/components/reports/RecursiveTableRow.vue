<script setup lang="ts">
import { ref, computed } from 'vue'
import { openCrmItemCard } from '~/utils/openCrmItem'


const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  level: {
    type: Number,
    default: 0
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

const isOpen = ref(false) // Default closed

const hasChildren = computed(() => (props.node.children && props.node.children.length > 0) || (props.node.items && props.node.items.length > 0))

const toggle = () => {
    if (hasChildren.value) {
        isOpen.value = !isOpen.value
    }
}

const paddingLeft = computed(() => `${props.level * 20 + 20}px`)

const typeLabel = computed(() => {
    switch (props.node.type) {
        case 'employee': return 'Сотрудник'
        case 'project': return 'Проект'
        case 'task': return 'Задача'
        default: return props.node.type
    }
})

// Color coding based on level/type
const rowClass = computed(() => {
    if (props.node.type === 'employee') return 'bg-blue-50 hover:bg-blue-100 font-bold'
    if (props.node.type === 'project') return 'bg-gray-50 hover:bg-gray-100 font-semibold'
    return 'hover:bg-gray-50'
})
const openTask = (id: string | number) => {
    // Attempt to use global BX24 or window.open
    // @ts-ignore
    const BX24 = window.BX24;
    
    if (typeof BX24 !== 'undefined') {
        BX24.openPath(`/company/personal/user/0/tasks/task/view/${id}/`)
    } else {
        window.open(`/company/personal/user/0/tasks/task/view/${id}/`, '_blank')
    }
}

const handleLabelClick = (itemIdElem: string | number) => {
    if (props.clickableLabels && props.entityTypeId) {
        openCrmItemCard(props.entityTypeId, itemIdElem)
    }
}
</script>

<template>
  <template v-if="node">
      <!-- Node Row -->
      <tr :class="['cursor-pointer border-b transition-colors', rowClass]" @click="toggle">
        <td class="py-3 pr-4 text-sm text-gray-900 flex items-start" :style="{ paddingLeft: paddingLeft }">
            <div class="mr-2 text-gray-500 mt-0.5" v-if="hasChildren">
                 <!-- Chevron Icon -->
                <svg v-if="isOpen" xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                </svg>
            </div>
            <div class="mr-2 text-gray-400" v-else>
               <span class="w-4 inline-block"></span>
            </div>
            
            <div class="flex flex-col">
                <span 
                    v-if="node.type === 'task'" 
                    @click.stop="openTask(node.id)"
                    class="whitespace-normal break-words text-blue-600 hover:underline hover:text-blue-800"
                >
                    {{ node.name || node.id }}
                </span>
                <span v-else class="whitespace-normal break-words">{{ node.name || node.id }}</span>
            </div>
        </td>
        
        <!-- Hours Columns -->
        <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-900 font-medium">
            {{ node.total_hours?.toFixed(2) || '0.00' }}
        </td>
        <td class="px-6 py-2 whitespace-nowrap text-sm text-green-700">
            {{ node.billable_hours?.toFixed(2) || '0.00' }}
        </td>
        <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-500">
            {{ node.non_billable_hours?.toFixed(2) || '0.00' }}
        </td>
        
        <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-400">
            {{ typeLabel }}
        </td>
      </tr>

      <!-- Children (Recursive) -->
      <template v-if="isOpen && node.children">
          <RecursiveTableRow 
            v-for="(child, key) in node.children" 
            :key="key" 
            :node="child" 
            :level="level + 1"
            :clickable-labels="clickableLabels"
            :entity-type-id="entityTypeId"
          />
      </template>

      <!-- Items (Leaves) -->
      <template v-if="isOpen && node.items">
          <tr v-for="item in node.items" :key="item.id_elem" class="bg-white hover:bg-gray-50 border-b">
               <td class="py-2 pr-4 text-sm text-gray-600 flex items-start" :style="{ paddingLeft: `${(level + 1) * 20 + 20}px` }">
                   <span class="mr-2 mt-0.5">📄</span>
                   <span 
                       v-if="clickableLabels && entityTypeId && item.id_elem"
                       @click.stop="handleLabelClick(item.id_elem)"
                       class="whitespace-normal break-words text-blue-600 hover:underline hover:text-blue-800 cursor-pointer"
                   >{{ item.opisanie || 'Без описания' }}</span>
                   <span v-else class="whitespace-normal break-words">{{ item.opisanie || 'Без описания' }}</span>
               </td>
               
               <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-900">
                   {{ item.kolichestvo_chasov.toFixed(2) }}
               </td>
               
               <td class="px-6 py-2 whitespace-nowrap text-sm text-green-700">
                   {{ item.uchitivaem ? item.kolichestvo_chasov.toFixed(2) : '-' }}
               </td>
               
               <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-500">
                   {{ !item.uchitivaem ? item.kolichestvo_chasov.toFixed(2) : '-' }}
               </td>

               <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-500">
                   {{ item.data ? new Date(item.data).toLocaleDateString() : '-' }}
               </td>
          </tr>
      </template>
  </template>
</template>

