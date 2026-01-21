<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  node: any // TaskNode
  level: number
}>()

const emit = defineEmits<{
  (e: 'add', node: any): void
  (e: 'edit', item: any, node: any): void
  (e: 'toggle', node: any): void
  (e: 'toggle-billable', item: any, node: any): void
}>()

const paddingLeft = computed(() => {
  return `${props.level * 20}px`
})

const formatHours = (val: number) => Number(val).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
const formatDate = (d: string) => {
    try {
        return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
    } catch { return d }
}

const toggleOpen = () => {
    emit('toggle', props.node)
}
</script>

<template>
  <div class="border-b border-gray-100 last:border-0">
    <!-- Task Row -->
    <div class="flex items-center py-3 px-4 hover:bg-gray-50 group transition-colors">
      <!-- Indent -->
      <div :style="{ width: paddingLeft }"></div>
      
      <!-- Chevron -->
      <button 
        @click="toggleOpen"
        class="mr-2 text-gray-400 hover:text-gray-600 transition-colors focus:outline-none"
        :class="{ 'invisible': !node.children.length && !node.items.length }"
      >
        <svg v-if="node.isOpen" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
        <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
      </button>

      <!-- Title -->
      <div class="flex-grow flex items-center min-w-0">
        <span class="text-sm font-medium text-gray-900 truncate" :title="node.title">
            {{ node.title }}
        </span>
      </div>

      <!-- Stats Badge -->
      <div class="flex items-center space-x-3">
         <div v-if="node.stats.total > 0" class="flex text-xs font-semibold space-x-1">
             <span class="text-gray-500" title="Всего">{{ formatHours(node.stats.total) }}ч</span>
             <span class="text-gray-300">|</span>
             <span class="text-green-600" title="Оплачиваемо">{{ formatHours(node.stats.billable) }}ч</span>
         </div>
         
         <!-- Add Button -->
         <button 
           @click="emit('add', node)"
           class="p-1 rounded-full text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
           title="Добавить часы"
         >
           <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
         </button>
      </div>
    </div>

    <!-- Items (Logs) -->
    <div v-if="node.isOpen && node.items.length" class="bg-slate-50 border-t border-gray-100">
        <div 
            v-for="item in node.items" 
            :key="item.id"
            class="flex items-center py-2 px-4 pl-12 hover:bg-slate-100 transition-colors text-sm cursor-pointer"
            :style="{ paddingLeft: `calc(${paddingLeft} + 40px)` }"
            @click="emit('edit', item, node)"
        >
            <!-- Avatar (Placeholder) -->
            <div class="h-6 w-6 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center text-xs font-bold mr-3 flex-shrink-0">
                {{ item.employeeId ? 'U' : '?' }}
            </div>
            
            <div class="flex-grow min-w-0 mr-4">
                <div class="text-gray-900 truncate">{{ item.description }}</div>
                <div class="text-xs text-gray-500">{{ formatDate(item.date) }}</div>
            </div>

            <div class="flex items-center space-x-4 flex-shrink-0">
                <span class="font-medium text-gray-700">{{ formatHours(item.hours) }} ч</span>
                
                <!-- Billable Toggle (Click stop propagation to avoid edit modal) -->
                <button 
                  @click.stop="emit('toggle-billable', item, node)"
                  class="focus:outline-none transition-colors"
                  :title="item.isBillable ? 'Оплачиваемо' : 'Не оплачиваемо'"
                >
                   <svg v-if="item.isBillable" class="w-5 h-5 text-green-500 hover:text-green-600" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>
                   <svg v-else class="w-5 h-5 text-gray-400 hover:text-gray-500" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"></path></svg>
                </button>
            </div>
        </div>
    </div>

    <!-- Children Recursion -->
    <div v-if="node.isOpen && node.children.length">
        <TaskTreeItem 
            v-for="child in node.children" 
            :key="child.id" 
            :node="child" 
            :level="level + 1"
            @add="(n) => emit('add', n)"
            @edit="(i, n) => emit('edit', i, n)"
            @toggle="(n) => emit('toggle', n)"
            @toggle-billable="(i, n) => emit('toggle-billable', i, n)"
        />
    </div>
  </div>
</template>
