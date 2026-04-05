<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import {
  formatProjectDate,
  formatProjectHours,
  formatProjectMoney,
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
    class="group w-full rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md cursor-grab active:cursor-grabbing"
    @click="emit('edit', card)"
    @dragstart="handleDragStart"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="truncate text-sm font-semibold text-gray-900">
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
        </div>
      </div>

      <div class="text-right text-[11px] text-gray-400">
        #{{ card.project_id }}
      </div>
    </div>

    <div class="mt-4 grid grid-cols-2 gap-3 text-xs">
      <div class="rounded-xl bg-gray-50 px-3 py-2">
        <div class="text-gray-400">Бюджет</div>
        <div class="mt-1 font-semibold text-gray-800">{{ formatProjectHours(card.project_hours_budget) }}</div>
      </div>
      <div class="rounded-xl bg-gray-50 px-3 py-2">
        <div class="text-gray-400">Ставка</div>
        <div class="mt-1 font-semibold text-gray-800">{{ formatProjectMoney(card.hourly_rate) }}</div>
      </div>
    </div>

    <div class="mt-4 space-y-2 text-xs text-gray-600">
      <div class="flex items-center justify-between gap-3">
        <span class="text-gray-400">Куратор</span>
        <span class="truncate font-medium text-gray-800">{{ card.curator_name || 'Не назначен' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-gray-400">Компания</span>
        <span class="truncate font-medium text-gray-800">{{ card.company_name || 'Не выбрана' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-gray-400">Наше юрлицо</span>
        <span class="truncate font-medium text-gray-800">{{ card.our_legal_entity_name || 'Не выбрано' }}</span>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-gray-400">Сроки</span>
        <span class="text-right font-medium text-gray-800">
          {{ card.project_start_date ? formatProjectDate(card.project_start_date) : '—' }}
          -
          {{ card.project_end_date ? formatProjectDate(card.project_end_date) : '—' }}
        </span>
      </div>
    </div>

    <div class="mt-4 rounded-xl bg-gray-50 px-3 py-2 text-xs text-gray-600">
      {{ lastWriteoffLabel }}
    </div>
  </button>
</template>
