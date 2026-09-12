<script setup lang="ts">
/**
 * Колонка стадии на доске проектов.
 *
 * Что изменилось против прежней версии:
 *  - в заголовке не только счётчик карточек, но и что в стадии стоит: часы
 *    факт/план и деньги плана (buildBoardColumnStats). Раньше «В работе: 7»
 *    ничего не говорило о нагрузке стадии;
 *  - подсказка «перетащите сюда / статус автоматический» больше не занимает
 *    строку под заголовком: она ушла в подсказку у метки «авто» и в подсветку
 *    зоны во время перетаскивания. Строка съедала место у каждой из семи
 *    колонок постоянно, а нужна была две секунды в год;
 *  - длинная колонка сворачивается до VISIBLE_LIMIT карточек. Причина —
 *    фрейм приложения НЕ прокручивается сам: его высота подгоняется под
 *    контент (requestIframeAutoHeight в layouts/default.vue). Колонка на
 *    40 карточек растянула бы весь фрейм на несколько тысяч пикселей, и
 *    заголовки колонок уехали бы далеко вверх за пределы экрана портала.
 *
 * Заголовок помечен sticky top-0: внутри фрейма с автовысотой это ничего не
 * меняет (прокрутки нет и прилипать не к чему), но в слайдере портала и в
 * любом контейнере с собственной прокруткой заголовок останется на месте.
 */

import { computed, ref, watch } from 'vue'
import ProjectBoardCard from '~/components/projects/ProjectBoardCard.vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import type { ProjectBoardColumnModel } from '~/utils/projectBoardView'

const props = defineProps<{
  column: ProjectBoardColumnModel
  canOpenSpa?: boolean
  /** Идёт перетаскивание карточки: колонки-приёмники подсвечиваются заранее. */
  isDragging?: boolean
}>()

const emit = defineEmits<{
  (event: 'edit' | 'open-spa' | 'open-report' | 'open-group', card: ProjectBoardCardRecord): void
  (event: 'dragstart', projectId: string): void
  (event: 'drop-card', payload: { projectId: string, stage: string }): void
}>()

/** Сколько карточек показываем без «Показать ещё». Восемь — примерно экран портала. */
const VISIBLE_LIMIT = 8

const isDragOver = ref(false)
const isExpanded = ref(false)

const visibleCards = computed(() =>
  isExpanded.value ? props.column.cards : props.column.cards.slice(0, VISIBLE_LIMIT)
)

const hiddenCount = computed(() => Math.max(0, props.column.cards.length - visibleCards.value.length))

// Сменились фильтры — колонка снова сворачивается: развёрнутый хвост от
// прошлого отбора к новому отношения не имеет.
watch(() => props.column.cards.length, () => {
  isExpanded.value = false
})

function handleDragOver() {
  if (!props.column.canDrop) {
    return
  }

  isDragOver.value = true
}

function handleDragLeave() {
  isDragOver.value = false
}

function handleDrop(event: DragEvent) {
  isDragOver.value = false
  if (!props.column.canDrop) {
    return
  }

  const projectId = event.dataTransfer?.getData('text/plain')
  if (!projectId) {
    return
  }

  emit('drop-card', {
    projectId,
    stage: props.column.id,
  })
}
</script>

<template>
  <section
    :class="[
      'flex w-[264px] shrink-0 flex-col rounded-2xl border bg-slate-50 transition',
      isDragOver ? 'border-[#0075ff] bg-[#e8f3ff] shadow-md' : 'border-slate-200',
      isDragging && !column.canDrop ? 'opacity-60' : '',
    ]"
    @dragover.prevent="handleDragOver"
    @dragleave="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <header class="sticky top-0 z-10 rounded-t-2xl border-b border-slate-200 bg-slate-50/95 px-3 py-2 backdrop-blur">
      <div class="flex items-center gap-2">
        <span :class="['size-2 shrink-0 rounded-full', column.dotClass]" aria-hidden="true" />
        <h3 class="truncate text-[12.5px] font-semibold text-slate-900" :title="column.title">{{ column.title }}</h3>
        <span
          v-if="!column.canDrop"
          class="shrink-0 rounded bg-slate-200 px-1 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-slate-600"
          title="Стадия ставится автоматической проверкой списаний, перетащить сюда нельзя"
        >
          авто
        </span>
        <span class="ml-auto shrink-0 text-[12px] font-semibold text-slate-500">{{ column.stats.count }}</span>
      </div>

      <div class="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
        <span class="truncate">{{ column.stats.summaryLabel || 'Часы не списывались' }}</span>
        <span
          v-if="column.stats.riskCount > 0"
          class="ml-auto shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700"
          :title="`${column.stats.riskCount} проектов под риском: нет списаний 30+ дней или перерасход бюджета`"
        >
          риск {{ column.stats.riskCount }}
        </span>
      </div>
    </header>

    <div class="flex flex-col gap-2 p-2">
      <ProjectBoardCard
        v-for="card in visibleCards"
        :key="card.project_id"
        :card="card"
        :can-open-spa="canOpenSpa"
        @edit="emit('edit', $event)"
        @dragstart="emit('dragstart', $event)"
        @open-spa="emit('open-spa', $event)"
        @open-report="emit('open-report', $event)"
        @open-group="emit('open-group', $event)"
      />

      <button
        v-if="hiddenCount > 0"
        type="button"
        class="rounded-xl border border-dashed border-slate-300 px-3 py-2 text-[11.5px] font-medium text-slate-500 transition hover:border-[#0075ff] hover:text-[#0075ff]"
        @click="isExpanded = true"
      >
        Показать ещё {{ hiddenCount }}
      </button>

      <div
        v-if="column.stats.count === 0"
        class="rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center text-[11.5px] text-slate-400"
      >
        {{ column.canDrop ? 'Пусто. Перетащите проект сюда' : 'Пусто — и это хорошо' }}
      </div>
    </div>
  </section>
</template>
