<script setup lang="ts">
import { defineProps, defineEmits, computed } from 'vue'
import HoursItemCard from './HoursItemCard.vue'

const props = defineProps<{
  task: any
  level: number
  clientHourRate: number
  openTaskIds: Set<string | number>
  users: Record<string, string>
  updatingItemId: number | string | null
  fields: {
    hours: string
    isConsidered: string
    employee: string
  }
}>()

const emit = defineEmits<{
  (e: 'toggle-group', id: number | string): void
  (e: 'open-modal', id: number | string): void
  (e: 'toggle-hours', id: number | string): void
  (e: 'open-item', id: number | string): void
}>()

const hasContent = computed(() => props.task.items.length > 0 || props.task.children.length > 0)
const isOpen = computed(() => props.openTaskIds.has(props.task.taskId))
const clientSum = computed(() => (props.task.cumulativeConsidered || 0) * props.clientHourRate)

// Formatting helpers
// @ts-ignore
const formatMoney = (val) => val.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
// @ts-ignore
const formatHours = (val) => val.toFixed(2)

const onToggleGroup = () => emit('toggle-group', props.task.taskId)
</script>

<template>
  <div :style="{ marginLeft: level > 0 ? '1rem' : '0' }" v-if="hasContent || level === 0">
    <div class="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden mb-2">
      <!-- Header -->
      <div class="w-full text-left p-3 bg-slate-50 border-b flex justify-between items-center">
        <div class="flex-1 min-w-0 cursor-pointer" @click="onToggleGroup">
          <h3 class="text-sm font-bold text-slate-900 truncate">
            <span v-if="level > 0" class="font-normal text-purple-600">[Подзадача] </span>
            {{ task.taskTitle }}
          </h3>
          <p class="text-xs text-slate-600 mt-1 flex items-center">
            <span>ID: {{ task.taskId }}</span>
          </p>
        </div>
        
        <div class="flex items-center gap-4 ml-4 text-right shrink-0">
          <!-- Client Sum -->
          <div v-if="clientHourRate > 0" class="border-r pr-4 border-slate-200 hidden sm:block">
            <p class="text-xs text-blue-600">Сумма для клиента</p>
            <p class="text-sm font-bold text-slate-800">{{ formatMoney(clientSum) }} руб.</p>
          </div>
          
          <!-- Considered -->
          <div>
            <p class="text-xs text-green-600">Учтено (всего)</p>
            <p class="text-sm font-bold text-slate-800">{{ formatHours(task.cumulativeConsidered) }} ч</p>
            <p v-if="task.children.length > 0 && task.totalConsidered > 0" class="text-xs text-slate-500 italic">
              в т.ч. своих: {{ formatHours(task.totalConsidered) }} ч
            </p>
          </div>
          
          <!-- Unconsidered -->
          <div>
            <p class="text-xs text-red-600">Не учтено (всего)</p>
            <p class="text-sm font-bold text-slate-800">{{ formatHours(task.cumulativeUnconsidered) }} ч</p>
            <p v-if="task.children.length > 0 && task.totalUnconsidered > 0" class="text-xs text-slate-500 italic">
              в т.ч. своих: {{ formatHours(task.totalUnconsidered) }} ч
            </p>
          </div>

          <!-- Actions -->
          <div class="flex flex-col items-center gap-1">
            <button 
              @click="emit('open-modal', task.taskId)" 
              title="Отразить часы для этой задачи" 
              class="p-1 rounded-full bg-green-100 text-green-700 hover:bg-green-200"
            >
              <span class="material-symbols-outlined text-base">add</span>
            </button>
            <button 
              @click="onToggleGroup" 
              title="Развернуть/Свернуть" 
              class="p-1 rounded-full hover:bg-slate-200"
            >
              <span :class="`material-symbols-outlined text-slate-500 transition-transform ${isOpen ? 'rotate-180' : ''}`">
                expand_more
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- Body -->
      <div v-if="isOpen">
        <!-- Items List -->
        <HoursItemCard 
          v-for="item in task.items" 
          :key="item.id" 
          :item="item" 
          :users="users"
          :updatingItemId="updatingItemId"
          :fields="fields"
          @toggle-hours="(id) => emit('toggle-hours', id)"
          @open-item="(id) => emit('open-item', id)"
        />
        
        <!-- Children Recursive -->
        <div v-if="task.children.length > 0" class="p-2 space-y-2 bg-slate-50 border-t">
          <TaskGroup 
            v-for="childTask in task.children" 
            :key="childTask.taskId" 
            :task="childTask" 
            :level="level + 1" 
            :clientHourRate="clientHourRate"
            :openTaskIds="openTaskIds"
            :users="users"
            :updatingItemId="updatingItemId"
            :fields="fields"
            @toggle-group="(id) => emit('toggle-group', id)"
            @open-modal="(id) => emit('open-modal', id)"
            @toggle-hours="(id) => emit('toggle-hours', id)"
            @open-item="(id) => emit('open-item', id)"
          />
        </div>
      </div>
    </div>
  </div>
</template>
