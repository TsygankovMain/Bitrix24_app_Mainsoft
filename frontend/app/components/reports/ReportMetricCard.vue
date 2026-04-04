<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  label: string
  value: string | number
  caption?: string
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'info'
}>(), {
  caption: '',
  tone: 'default'
})

const containerClass = computed(() => {
  switch (props.tone) {
    case 'success':
      return 'border-emerald-100 bg-emerald-50'
    case 'warning':
      return 'border-amber-100 bg-amber-50'
    case 'danger':
      return 'border-red-100 bg-red-50'
    case 'info':
      return 'border-sky-100 bg-sky-50'
    default:
      return 'border-gray-200 bg-white'
  }
})

const valueClass = computed(() => {
  switch (props.tone) {
    case 'success':
      return 'text-emerald-700'
    case 'warning':
      return 'text-amber-700'
    case 'danger':
      return 'text-red-700'
    case 'info':
      return 'text-sky-700'
    default:
      return 'text-gray-900'
  }
})
</script>

<template>
  <div :class="['rounded-xl border p-4 shadow-sm', containerClass]">
    <div class="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">
      {{ label }}
    </div>
    <div :class="['mt-2 text-2xl font-bold', valueClass]">
      {{ value }}
    </div>
    <div v-if="caption" class="mt-1 text-sm text-gray-500">
      {{ caption }}
    </div>
  </div>
</template>
