<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{
  visible: boolean
  title?: string
  done?: number
  total?: number
  label?: string
}>()
const pct = computed(() => {
  if (!props.total || props.total <= 0) return null
  return Math.min(100, Math.round(((props.done ?? 0) / props.total) * 100))
})
const finished = computed(() => pct.value === 100)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[1000] flex items-center justify-center" style="background:rgba(15,23,42,.45)">
      <div class="bg-white rounded-2xl shadow-xl border border-slate-200 w-[440px] p-6 text-center">
        <div class="text-sm font-semibold text-slate-700">{{ title || 'Идёт операция…' }}</div>
        <div class="text-xs text-slate-400 mt-1 mb-5">Бобёр-Учётчик тащит карточки в 1С</div>
        <div class="relative h-6 rounded-full bg-slate-200 overflow-visible">
          <div
            class="h-full rounded-full transition-all duration-300"
            :style="{ width: (pct ?? 30) + '%', background: 'linear-gradient(90deg,#84cc16,#10b981)' }"
          />
          <div
            class="absolute -top-5 text-2xl"
            :style="{ left: (pct ?? 30) + '%', transform: 'translateX(-50%)', animation: 'bobx 1s ease-in-out infinite' }"
          >{{ finished ? '🦫✅' : '🦫' }}<span v-if="!finished" class="text-xs absolute top-2 left-5">🗂️</span></div>
        </div>
        <div class="flex justify-between text-xs text-slate-500 mt-2">
          <span>{{ label || (total ? `обработано ${done ?? 0} / ${total}` : 'обработка…') }}</span>
          <span v-if="pct !== null" class="font-semibold text-slate-700">{{ pct }}%</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
@keyframes bobx { 0%,100% { transform: translateX(-50%) translateY(0) } 50% { transform: translateX(-50%) translateY(-3px) } }
</style>
