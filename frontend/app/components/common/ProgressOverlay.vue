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
        <div class="text-xs text-slate-400 mt-1 mb-5">{{ hint || 'Бобёр-Учётчик трудится' }}</div>

        <!-- Детерминированный режим: заливка по проценту + бобёр на её краю -->
        <div v-if="determinate" class="relative h-6 rounded-full bg-slate-200 overflow-visible">
          <div
            class="h-full rounded-full transition-all duration-300"
            :style="{ width: (pct ?? 0) + '%', background: 'linear-gradient(90deg,#84cc16,#10b981)' }"
          />
          <div
            class="absolute -top-5 text-2xl po-beaver"
            :style="{ left: (pct ?? 0) + '%' }"
          >{{ finished ? '🦫✅' : '🦫' }}<span v-if="!finished" class="text-xs absolute top-2 left-5">🗂️</span></div>
        </div>

        <!-- Индетерминированный режим: бегущая полоса + едущий бобёр (видно, что идёт работа) -->
        <div v-else class="relative h-6 overflow-visible">
          <div class="absolute inset-0 rounded-full bg-slate-200 overflow-hidden">
            <div
              class="absolute top-0 h-full w-2/5 rounded-full po-sweep"
              style="background: linear-gradient(90deg,#84cc16,#10b981)"
            />
          </div>
          <div class="absolute -top-5 text-2xl po-ride">🦫<span class="text-xs absolute top-2 left-5">🗂️</span></div>
        </div>

        <div class="flex justify-between text-xs text-slate-500 mt-2">
          <span>{{ label || (determinate ? `обработано ${done ?? 0} / ${total}` : 'идёт обработка…') }}</span>
          <span v-if="pct !== null" class="font-semibold text-slate-700">{{ pct }}%</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Бобёр в детерминированном режиме: подпрыгивает на месте, центрируется по краю заливки */
.po-beaver { animation: po-bob 1s ease-in-out infinite; }
@keyframes po-bob {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50%      { transform: translateX(-50%) translateY(-3px); }
}
/* Бегущая полоса индетерминированного режима */
.po-sweep { animation: po-sweep 1.5s ease-in-out infinite; }
@keyframes po-sweep {
  0%   { transform: translateX(-120%); }
  100% { transform: translateX(320%); }
}
/* Бобёр едет вдоль полосы и подпрыгивает */
.po-ride { animation: po-bob 1s ease-in-out infinite, po-ride 1.5s ease-in-out infinite; }
@keyframes po-ride {
  0%   { left: 2%; }
  100% { left: 98%; }
}
</style>
