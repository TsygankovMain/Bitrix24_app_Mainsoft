<script setup lang="ts">
import { defineProps, defineEmits, computed } from 'vue'

const props = defineProps<{
  item: any
  users: Record<string, string>
  updatingItemId: number | string | null
  fields: {
    hours: string
    isConsidered: string
    employee: string
  }
}>()

const emit = defineEmits<{
  (e: 'toggle-hours', id: number | string): void
  (e: 'open-item', id: number | string): void
}>()

const hours = computed(() => parseFloat(props.item[props.fields.hours]) || 0)
const isConsidered = computed(() => props.item[props.fields.isConsidered] === true || props.item[props.fields.isConsidered] === 'Y')
const isUpdating = computed(() => props.updatingItemId === props.item.id)

const formatDate = (d: string) => d ? new Date(d).toLocaleDateString('ru-RU') : 'Не указана'
</script>

<template>
  <div :class="`p-3 border-t transition-opacity ${isUpdating ? 'opacity-50' : ''}`">
    <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-2">
      <div class="flex-1 min-w-0">
        <p 
          class="font-semibold text-slate-800 truncate hover:text-blue-600 cursor-pointer" 
          @click="emit('open-item', item.id)" 
          :title="item.title"
        >
          {{ item.title || 'Без названия' }}
        </p>
        <div class="flex items-center text-xs text-slate-500 mt-2 gap-3">
          <div class="flex items-center">
            <span class="material-symbols-outlined text-sm mr-1">person</span>
            {{ users[item[fields.employee]] || 'Неизвестно' }}
          </div>
          <div class="flex items-center">
            <span class="material-symbols-outlined text-sm mr-1">calendar_today</span>
            {{ formatDate(item.createdTime) }}
          </div>
        </div>
      </div>
      <div class="flex md:flex-col items-center md:items-end justify-between mt-2 md:mt-0 gap-2">
        <div class="flex items-center gap-2 text-sm font-bold">
          <span 
            :class="isConsidered ? 'text-green-600' : 'text-red-600'" 
            :title="isConsidered ? 'Учитываемые' : 'Не учитываемые'"
          >
            {{ hours.toFixed(2) }}ч
          </span>
        </div>
        <button 
          @click="emit('toggle-hours', item.id)" 
          :disabled="!!isUpdating"
          class="px-2 py-1 text-xs font-semibold rounded-full transition-all flex items-center bg-blue-100 text-blue-800 hover:bg-blue-200 disabled:bg-slate-200 disabled:text-slate-500 disabled:cursor-not-allowed"
        >
          <span :class="`material-symbols-outlined text-sm mr-1 ${isUpdating ? 'animate-spin' : ''}`">
            {{ isUpdating ? 'sync' : 'swap_horiz' }}
          </span>
          {{ isUpdating ? '...' : 'Переключить' }}
        </button>
      </div>
    </div>
  </div>
</template>
