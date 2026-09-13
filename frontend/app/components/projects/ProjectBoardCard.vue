<script setup lang="ts">
/**
 * Компактная карточка проекта на доске.
 *
 * Было: двенадцать полей в четыре блока (бюджет, ставка, план, факт, освоение,
 * куратор, компания, юрлицо, сроки, давность списания) — карточка высотой
 * почти в треть экрана, три-четыре штуки в колонке, и доска на 20 проектов
 * листалась вертикально метрами.
 *
 * Стало пять полей по макету «вариант A»: название, клиент, освоение полосой,
 * куратор, последняя активность (или признак риска вместо неё). Всё остальное —
 * ставка, юрлицо, сроки, финансовые операции — осталось в дровере, который
 * открывается кликом по карточке: карточка отвечает на вопрос «что тут
 * происходит», дровер — на «какие именно цифры».
 *
 * Быстрые действия внизу видны ВСЕГДА, а не по наведению: на доске это
 * основной способ уйти в карточку смарт-процесса или в отчёт, не открывая
 * дровер, а скрытые по hover кнопки не находятся ни с клавиатуры, ни с
 * тачпада планшета.
 */

import { computed } from 'vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import { formatProjectCurrency } from '~/utils/projectBoard'
import {
  boardCardRiskReasons,
  buildBoardInitials,
  buildBoardUtilization,
  formatBoardActivity,
  getBoardAvatarToneClass,
  isBoardCardSupport,
} from '~/utils/projectBoardView'

const props = defineProps<{
  card: ProjectBoardCardRecord
  /** Известен ли тип смарт-процесса: без него кнопка «Карточка СП» никуда не ведёт. */
  canOpenSpa?: boolean
}>()

const emit = defineEmits<{
  (event: 'edit' | 'open-spa' | 'open-report' | 'open-group', card: ProjectBoardCardRecord): void
  (event: 'dragstart', projectId: string): void
}>()

const isSupportCard = computed(() => isBoardCardSupport(props.card))
const utilization = computed(() => buildBoardUtilization(props.card))
const riskReasons = computed(() => boardCardRiskReasons(props.card))
const riskLabel = computed(() => riskReasons.value[0] || '')
const riskTitle = computed(() => riskReasons.value.join(' · '))
const initials = computed(() => buildBoardInitials(props.card.curator_name))
const avatarToneClass = computed(() => getBoardAvatarToneClass(props.card.curator_name))
const activityLabel = computed(() => formatBoardActivity(props.card))

const BAR_TONE_CLASS = {
  neutral: 'bg-[#0075ff]',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
} as const

const LABEL_TONE_CLASS = {
  neutral: 'text-slate-700',
  warning: 'text-amber-700',
  danger: 'text-rose-700',
} as const

/** Перерасход подсвечивает всю карточку рамкой: в колонке из восьми штук полосу видно не сразу. */
const cardToneClass = computed(() => {
  if (utilization.value.tone === 'danger') {
    return 'border-rose-200'
  }

  return 'border-slate-200'
})

function handleDragStart(event: DragEvent) {
  event.dataTransfer?.setData('text/plain', props.card.project_id)
  emit('dragstart', props.card.project_id)
}

function handleOpen() {
  emit('edit', props.card)
}
</script>

<template>
  <article
    draggable="true"
    role="button"
    tabindex="0"
    :aria-label="`Проект ${card.project_name}`"
    :class="[
      'group cursor-grab rounded-xl border bg-white p-2.5 text-left shadow-sm transition hover:border-slate-300 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0075ff] active:cursor-grabbing',
      cardToneClass,
    ]"
    @click="handleOpen"
    @keydown.enter.prevent="handleOpen"
    @keydown.space.prevent="handleOpen"
    @dragstart="handleDragStart"
  >
    <div class="flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <div class="line-clamp-2 text-[13px] font-semibold leading-snug text-slate-900" :title="card.project_name">
          {{ card.project_name }}
        </div>
        <div class="mt-0.5 truncate text-[11.5px] text-slate-500" :title="card.company_name || ''">
          {{ card.company_name || 'Без компании' }}
        </div>
      </div>

      <div class="flex shrink-0 flex-col items-end gap-1">
        <span
          v-if="isSupportCard"
          class="inline-flex rounded-md bg-cyan-50 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-700"
          title="Проект поддержки"
        >
          Поддержка
        </span>
        <span
          v-if="card.stage_source === 'auto'"
          class="inline-flex rounded-md bg-orange-50 px-1.5 py-0.5 text-[10px] font-semibold text-orange-700"
          title="Стадию поставила автоматическая проверка списаний"
        >
          Авто
        </span>
      </div>
    </div>

    <!--
      Поддержка живёт не бюджетом, а финрезультатом месяца: полоса освоения там
      всегда пустая и врала бы «ничего не сделано». Поэтому у поддержки вместо
      полосы — часы и финрезультат строкой.
    -->
    <div v-if="isSupportCard" class="mt-2 flex items-center justify-between gap-2 text-[11.5px]">
      <span class="text-slate-500">Финрезультат</span>
      <span class="font-semibold text-slate-800">{{ formatProjectCurrency(card.actual_financial_result) }}</span>
    </div>

    <div v-else class="mt-2">
      <div v-if="!utilization.isEmpty" class="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          class="h-full rounded-full transition-all"
          :class="BAR_TONE_CLASS[utilization.tone]"
          :style="{ width: `${utilization.barPercent}%` }"
        />
      </div>
      <div class="mt-1 text-[11.5px] font-medium" :class="LABEL_TONE_CLASS[utilization.tone]">
        {{ utilization.label }}
      </div>
    </div>

    <div class="mt-2 flex items-center justify-between gap-2">
      <span class="flex min-w-0 items-center gap-1.5" :title="card.curator_name || 'Куратор не назначен'">
        <span
          :class="['inline-grid size-5 shrink-0 place-items-center rounded-full text-[9px] font-bold', avatarToneClass]"
          aria-hidden="true"
        >{{ initials }}</span>
        <span class="truncate text-[11.5px] text-slate-600">{{ card.curator_name || 'Без куратора' }}</span>
      </span>

      <span
        v-if="riskLabel"
        class="shrink-0 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700"
        :title="riskTitle"
      >
        {{ riskLabel }}
      </span>
      <span v-else class="shrink-0 text-[11px] text-slate-400">{{ activityLabel }}</span>
    </div>

    <div class="mt-2 flex flex-wrap items-center gap-1 border-t border-slate-100 pt-2">
      <button
        v-if="canOpenSpa && card.project_item_id"
        type="button"
        class="rounded-md px-1.5 py-1 text-[11px] font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
        title="Открыть карточку смарт-процесса в Битрикс24"
        @click.stop="emit('open-spa', card)"
      >
        Карточка
      </button>
      <button
        type="button"
        class="rounded-md px-1.5 py-1 text-[11px] font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
        title="Отчёт по проекту за период"
        @click.stop="emit('open-report', card)"
      >
        Отчёт
      </button>
      <button
        type="button"
        class="rounded-md px-1.5 py-1 text-[11px] font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
        title="Открыть рабочую группу проекта"
        @click.stop="emit('open-group', card)"
      >
        Группа
      </button>
      <span class="ml-auto text-[10.5px] text-slate-300">#{{ card.project_id }}</span>
    </div>
  </article>
</template>
