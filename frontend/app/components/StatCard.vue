<script setup lang="ts">
import { defineProps } from 'vue'

defineProps<{
  icon: string
  label: string
  value: string | number
  unit: string
  color: string
}>()
</script>

<template>
  <div class="p-3 bg-white rounded-lg border border-slate-200 shadow-sm flex items-center">
    <span :class="`material-symbols-outlined text-3xl mr-3 ${color}`">{{ icon }}</span>
    <div>
      <p class="text-xs text-slate-500">{{ label }}</p>
      <p class="text-xl font-bold text-slate-900">
        {{ value }} <span class="text-sm text-slate-500">{{ unit }}</span>
      </p>
    </div>
  </div>
</template>
