<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import {
  formatProjectDate,
  formatProjectHours,
  formatProjectCurrency,
  formatProjectMoney,
  formatProjectPercent,
  getBudgetStatusBadgeClass,
  getStageBadgeClass
} from '~/utils/projectBoard'

const props = defineProps<{
  card: ProjectBoardCardRecord
}>()

const emit = defineEmits<{
  (event: 'edit', card: ProjectBoardCardRecord): void
  (event: 'dragstart', projectId: string): void
}>()

const stageBadgeClass = computed(() => getStageBadgeClass(props.card.stage))
const budgetBadgeClass = computed(() => getBudgetStatusBadgeClass(props.card.budget_health_status))
const isSupportCard = computed(() => Boolean(props.card.is_support || String(props.card.project_type || '').toLowerCase() === 'support'))
const budgetProgressPercent = computed(() => {
  const value = Number(props.card.budget_utilization_percent)
  if (!Number.isFinite(value)) {
    return null
  }
  return Math.max(0, Math.min(value, 100))
})
const lastWriteoffLabel = computed(() => {
  if (!props.card.last_writeoff_at) {
    return 'Списаний пока нет'
  }

  if (props.card.last_writeoff_days <= 0) {
    return `Последнее списание ${formatProjectDate(props.card.last_writeoff_at)}`
  }

  return `${props.card.last_writeoff_days} дн. с последнего списания`
})

function handleDragStart(event: DragEvent) {
  event.dataTransfer?.setData('text/plain', props.card.project_id)
  emit('dragstart', props.card.project_id)
}
</script>

<template>
  <button
    type="button"
    draggable="true"
    class="group w-full cursor-grab rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md active:cursor-grabbing"
    @click="emit('edit', card)"
    @dragstart="handleDragStart"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="truncate text-sm font-semibold text-slate-900">
          {{ card.project_name }}
        </div>
        <div class="mt-1 flex flex-wrap gap-2">
          <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', stageBadgeClass]">
            {{ card.stage }}
          </span>
          <span
            v-if="card.is_support"
            class="inline-flex rounded-full bg-cyan-100 px-2.5 py-1 text-[11px] font-semibold text-cyan-700"
          >
            Support
          </span>
          <span
            v-if="card.stage_source === 'auto'"
            class="inline-flex rounded-full bg-orange-100 px-2.5 py-1 text-[11px] font-semibold text-orange-700"
          >
            Авто
          </span>
          <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', budgetBadgeClass]">
            {{ card.budget_health_status || 'Без лимита' }}
          </span>
        </div>
      </div>

      <div class="text-right text-[11px] text-slate-400">
        #{{ card.project_id }}
      </div>
    </div>

    <div class="mt-4 grid grid-cols-2 gap-3 text-xs">
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <div class="text-slate-400">Бюджет</div>
        <div class="mt-1 font-semibold text-slate-800">{{ formatProjectHours(card.project_hours_budget) }}</div>
      </div>
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <div class="text-slate-400">Ставка</div>
        <div class="mt-1 font-semibold text-slate-800">{{ formatProjectMoney(card.hourly_rate) }}</div>
      </div>
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <div class="text-slate-400">План, ₽</div>
        <div class="mt-1 font-semibold text-slate-800">{{ formatProjectCurrency(card.planned_amount ?? card.planned_budget_amount) }}</div>
      </div>
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <div class="text-slate-400">Факт, ₽</div>
        <div class="mt-1 font-semibold text-slate-800">{{ formatProjectCurrency(card.actual_cost_amount) }}</div>
      </div>
    </div>

    <div v-if="!isSupportCard" class="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <div class="flex items-center justify-between gap-2">
        <span>Освоение</span>
        <span class="font-semibold text-slate-800">{{ formatProjectPercent(card.budget_utilization_percent) }}</span>
      </div>
      <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          class="h-full rounded-full bg-emerald-500 transition-all"
          :class="{
            'bg-amber-500': card.budget_health_status === 'Риск',
            'bg-rose-500': card.budget_health_status === 'Перерасход',
            'bg-slate-400': card.budget_health_status === 'Без лимита',
          }"
          :style="{ width: `${budgetProgressPercent ?? 0}%` }"
        />
      </div>
    </div>
    <div v-else class="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <div class="flex items-center justify-between gap-2">
        <span>Финрезультат поддержки</span>
        <span class="font-semibold text-slate-800">{{ formatProjectCurrency(card.actual_financial_result) }}</span>
      </div>
    </div>

    <div class="mt-4 space-y-2 text-xs text-slate-600">
      <div class="flex items-center justify-between gap-3">
        <span class="text-slate-400">Куратор</span>
        <span class="truncate font-medium text-slate-800">{{ card.curator_name || 'Не назначен' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-slate-400">Компания</span>
        <span class="truncate font-medium text-slate-800">{{ card.company_name || 'Не выбрана' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-slate-400">Наше юрлицо</span>
        <span class="truncate font-medium text-slate-800">{{ card.our_legal_entity_name || 'Не выбрано' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-slate-400">Сроки</span>
        <span class="text-right font-medium text-slate-800">
          {{ card.project_start_date ? formatProjectDate(card.project_start_date) : '—' }}
          -
          {{ card.project_end_date ? formatProjectDate(card.project_end_date) : '—' }}
        </span>
      </div>
    </div>

    <div class="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
      {{ lastWriteoffLabel }}
    </div>
  </button>
</template>
