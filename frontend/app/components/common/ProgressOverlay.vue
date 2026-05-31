<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{
  visible: boolean
  title?: string
  hint?: string
  done?: number
  total?: number
  label?: string
}>()
// Детерминированный режим — только когда известно total (>0): движемся к 100%.
// Иначе — индетерминированный режим: «бегущая» полоса, чтобы было видно, что процесс идёт, а не завис.
const determinate = computed(() => !!props.total && props.total > 0)
const pct = computed(() => {
  if (!determinate.value) return null
  return Math.min(100, Math.round(((props.done ?? 0) / (props.total as number)) * 100))
})
const finished = computed(() => pct.value === 100)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[1000] flex items-center justify-center" style="background:rgba(15,23,42,.45)">
      <div class="bg-white rounded-2xl shadow-xl border border-slate-200 w-[440px] p-6 text-center">
        <div class="text-sm font-semibold text-slate-700">{{ title || 'Идёт операция…' }}</div>
        <div class="text-xs text-slate-400 mt-1 mb-4">{{ hint || 'Бобёр-Учётчик трудится' }}</div>

        <div class="flex items-center gap-3">
          <!-- Бобёр отдельно от полосы: стоит рядом, крупнее (1.5×), подпрыгивает на месте -->
          <div class="po-beaver shrink-0 relative leading-none" style="font-size:2.25rem">
            {{ finished ? '🦫✅' : '🦫' }}<span v-if="!finished" class="absolute" style="font-size:0.95rem; right:-6px; bottom:-4px">🗂️</span>
          </div>

          <div class="flex-1">
            <!-- Полоса: детерминированная заливка (по %) или бегущая (индетерминированно) -->
            <div class="relative h-4 rounded-full bg-slate-200 overflow-hidden">
              <div
                v-if="determinate"
                class="h-full rounded-full transition-all duration-300"
                :style="{ width: (pct ?? 0) + '%', background: 'linear-gradient(90deg,#84cc16,#10b981)' }"
              />
              <div
                v-else
                class="absolute top-0 h-full w-2/5 rounded-full po-sweep"
                style="background: linear-gradient(90deg,#84cc16,#10b981)"
              />
            </div>
            <div class="flex justify-between text-xs text-slate-500 mt-2">
              <span>{{ label || (determinate ? `обработано ${done ?? 0} / ${total}` : 'идёт обработка…') }}</span>
              <span v-if="pct !== null" class="font-semibold text-slate-700">{{ pct }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Бобёр подпрыгивает на месте (без горизонтального движения — он зафиксирован рядом с полосой) */
.po-beaver { animation: po-bob 1s ease-in-out infinite; }
@keyframes po-bob {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-4px); }
}
/* Бегущая полоса индетерминированного режима */
.po-sweep { animation: po-sweep 1.5s ease-in-out infinite; }
@keyframes po-sweep {
  0%   { transform: translateX(-120%); }
  100% { transform: translateX(320%); }
}
</style>
