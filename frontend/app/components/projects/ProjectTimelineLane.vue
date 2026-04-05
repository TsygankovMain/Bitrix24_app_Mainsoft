<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import { formatProjectDate, getStageBadgeClass, parseProjectDateValue } from '~/utils/projectBoard'

const props = defineProps<{
  card: ProjectBoardCardRecord
  rangeStart: string
  rangeEnd: string
}>()

const emit = defineEmits<{
  (event: 'open', card: ProjectBoardCardRecord): void
}>()

const stageBadgeClass = computed(() => getStageBadgeClass(props.card.stage))

const anchorStart = computed(() => toDate(props.card.project_start_date || props.card.last_writeoff_at || props.card.created_at))
const anchorEnd = computed(() => {
  const explicitEnd = toDate(props.card.project_end_date)
  if (explicitEnd) {
    return explicitEnd
  }

  return anchorStart.value || toDate(props.card.updated_at)
})

const range = computed(() => {
  const start = toDate(props.rangeStart)
  const end = toDate(props.rangeEnd)

  if (!start || !end) {
    return {
      left: '0%',
      width: '4%'
    }
  }

  const totalDays = Math.max(diffDays(start, end) + 1, 1)
  const taskStart = anchorStart.value || start
  const taskEnd = anchorEnd.value || taskStart
  const safeStart = taskStart < start ? start : taskStart
  const safeEnd = taskEnd > end ? end : taskEnd
  const offset = Math.max(diffDays(start, safeStart), 0)
  const length = Math.max(diffDays(safeStart, safeEnd) + 1, 1)

  return {
    left: `${(offset / totalDays) * 100}%`,
    width: `${Math.max((length / totalDays) * 100, 4)}%`
  }
})

function toDate(value?: string | null) {
  if (!value) {
    return null
  }

  const parsed = parseProjectDateValue(value)
  if (Number.isNaN(parsed.getTime())) {
    return null
  }

  return parsed
}

function diffDays(start: Date, end: Date) {
  const left = Date.UTC(start.getFullYear(), start.getMonth(), start.getDate())
  const right = Date.UTC(end.getFullYear(), end.getMonth(), end.getDate())
  return Math.round((right - left) / 86400000)
}
</script>

<template>
  <button
    type="button"
    class="grid w-full grid-cols-[280px_minmax(0,1fr)] gap-4 rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md"
    @click="emit('open', card)"
  >
    <div class="min-w-0">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="truncate text-sm font-semibold text-gray-900">{{ card.project_name }}</div>
          <div class="mt-1 text-xs text-gray-500">
            {{ card.company_name || 'Без компании' }} · {{ card.curator_name || 'Без куратора' }}
          </div>
          <div class="mt-1 text-xs text-gray-400">
            {{ card.our_legal_entity_name || 'Юрлицо не выбрано' }}
          </div>
        </div>
        <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', stageBadgeClass]">
          {{ card.stage }}
        </span>
      </div>

      <div class="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
        <span class="rounded-full bg-gray-100 px-2.5 py-1">
          Старт: {{ card.project_start_date ? formatProjectDate(card.project_start_date) : 'не задан' }}
        </span>
        <span class="rounded-full bg-gray-100 px-2.5 py-1">
          Финиш: {{ card.project_end_date ? formatProjectDate(card.project_end_date) : 'не задан' }}
        </span>
        <span
          v-if="card.last_writeoff_at"
          class="rounded-full bg-gray-100 px-2.5 py-1"
        >
          Последнее списание: {{ formatProjectDate(card.last_writeoff_at) }}
        </span>
      </div>
    </div>

    <div class="flex items-center">
      <div class="relative h-14 w-full overflow-hidden rounded-2xl bg-gray-50 px-3">
        <div class="absolute inset-x-3 top-1/2 h-2 -translate-y-1/2 rounded-full bg-gray-200" />
        <div
          class="absolute top-1/2 h-6 -translate-y-1/2 rounded-full bg-lime-300 shadow-sm"
          :style="range"
        />
      </div>
    </div>
  </button>
</template>
